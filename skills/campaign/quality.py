"""Response quality: ranks every response by how genuine it looks. Nothing is excluded; low-quality and likely spam
responses sink to the bottom and carry plain-language reasons.

Rules run on every submit (and rescore the whole survey, since duplicates depend on peers). In the background, open
text gets a judgment review that feeds the same score: Jev (TypeSafe's decision model: typed yes/no and score
questions with calibrated confidence) when TYPESAFE_API_KEY is set, otherwise a small Claude model.
"""

import json
import os
import re
import threading
from statistics import median

from langchain_anthropic import ChatAnthropic

from skills.form_builder import store
from skills.form_builder.schema import Survey

BASE = 60
TIERS = ((80, "high"), (55, "ok"), (35, "low"), (0, "spam"))
KEYBOARD_RUNS = ("qwer", "asdf", "zxcv", "hjkl", "uiop", "1234", "abcd")


def tier_for(score: int, hard_spam: bool) -> str:
    if hard_spam:
        return "spam"
    return next(name for floor, name in TIERS if score >= floor)


def _flag(flags: list, code: str, label: str, delta: int, hard: bool = False) -> None:
    flags.append({"code": code, "label": label, "delta": delta, **({"hard": True} if hard else {})})


def is_gibberish(text: str) -> bool:
    letters = re.sub(r"[^a-z]", "", text.lower())
    if len(letters) < 3:
        return True
    if re.search(r"(.)\1{3,}", letters) or any(run in letters for run in KEYBOARD_RUNS):
        return True
    words = re.findall(r"[a-zA-Z]+", text)
    no_vowel = [w for w in words if len(w) > 2 and not re.search(r"[aeiouy]", w.lower())]
    vowel_share = len(re.findall(r"[aeiouy]", letters)) / len(letters)
    return vowel_share < 0.2 or (words and len(no_vowel) / len(words) > 0.4)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def score_response(survey: Survey, r: dict, peers: list[dict]) -> tuple[int, str, list[dict]]:
    flags: list[dict] = []
    answers, typing = r["answers"], r.get("typing") or {}
    questions = {q.id: q for q in survey.questions}

    # Time taken versus the survey's own estimate. Client-measured active time wins over server timestamps.
    expected = survey.estimated_minutes * 60
    duration = typing.get("active_s") or r.get("duration_s")
    if duration:
        ratio = duration / expected
        if ratio < 0.15:
            _flag(flags, "speeder", f"Finished in {duration:.0f}s, under 15% of the ~{expected // 60} min estimate", -40, hard=True)
        elif ratio < 0.3:
            _flag(flags, "rushed", f"Finished in {duration:.0f}s, well under the ~{expected // 60} min estimate", -20)
        elif ratio <= 4:
            _flag(flags, "paced", "Took a normal amount of time", 5)

    # Straight-lining: the same scale value everywhere, or always the first option.
    scales = [answers.get(q.id) for q in survey.questions if q.type == "scale" and answers.get(q.id) is not None]
    if len(scales) >= 2 and len(set(scales)) == 1:
        _flag(flags, "straightline", f"Gave every scale question the same score ({scales[0]})", -15)
    singles = [(q, answers.get(q.id)) for q in survey.questions if q.type == "single_choice" and answers.get(q.id)]
    if len(singles) >= 3 and all(a == q.options[0] for q, a in singles):
        _flag(flags, "first_option", "Picked the first option on every choice question", -10)

    # Open text: the strongest signal. Typed, specific answers earn points; mash, empties and pastes lose them.
    texts = [(q, answers.get(q.id)) for q in survey.questions if q.type == "text" and answers.get(q.id)]
    gibberish = [q for q, a in texts if is_gibberish(a)]
    good = [q for q, a in texts if q not in gibberish and len(a.split()) >= 8]
    for q in gibberish:
        _flag(flags, "gibberish", f"Q{survey.questions.index(q) + 1}: text looks like keyboard mash", -20)
    if texts and len(gibberish) == len(texts):
        flags[-1]["hard"] = True
    if good:
        _flag(flags, "thoughtful", f"Wrote {len(good)} detailed open answer{'s' if len(good) > 1 else ''}", min(8 * len(good), 16))
    fields = typing.get("fields") or {}
    typed = pasted = 0
    for q, a in texts:
        if q in gibberish:  # typing mash by hand earns nothing
            continue
        f = fields.get(q.id) or {}
        if f.get("pastes") and f.get("keys", 0) < len(a) * 0.3:
            pasted += 1
        elif f.get("keys", 0) >= len(a) * 0.6:
            typed += 1
    if typed:
        _flag(flags, "typed", "Typed the open answers by hand", 6)
    if pasted:
        _flag(flags, "pasted", f"Pasted {pasted} open answer{'s' if pasted > 1 else ''} instead of typing", -8)

    optional_answered = sum(1 for q in survey.questions if not q.required and answers.get(q.id) not in (None, "", [])
                            and q not in gibberish)
    if optional_answered:
        _flag(flags, "optional", f"Answered {optional_answered} optional question{'s' if optional_answered > 1 else ''}",
              min(3 * optional_answered, 6))

    # Consistency with itself and with the rest of the sample.
    for q, a in singles:
        if isinstance(a, str) and a.lower().startswith("not involved"):
            _flag(flags, "not_involved", f"Q{survey.questions.index(q) + 1}: said they're not involved in the decision", -15)
            flags[-1]["cap"] = 54  # off-target for the study, however careful the answers: low priority at best
    for q in survey.questions:
        if q.type != "number" or answers.get(q.id) is None:
            continue
        others = [p["answers"].get(q.id) for p in peers if p["token"] != r["token"] and p["answers"].get(q.id) is not None]
        if len(others) >= 4 and (m := median(others)) > 0 and answers[q.id] > 10 * m:
            _flag(flags, "outlier", f"Q{survey.questions.index(q) + 1}: {answers[q.id]:,.0f} is over 10x the median ({m:,.0f})", -8)
    for q in survey.questions:
        a = answers.get(q.id)
        if q.type == "multi_choice" and isinstance(a, list) and len(a) > 1 and any(x.lower().startswith("none") for x in a):
            _flag(flags, "contradiction", f"Q{survey.questions.index(q) + 1}: picked 'None' together with other options", -8)

    # Duplicates: the same open text, or the identical answer set from the same browser, as an earlier response.
    # Peers arrive in submission order (timestamp, then insert order), so "earlier" survives same-second submits.
    position = next((i for i, p in enumerate(peers) if p["token"] == r["token"]), len(peers))
    earlier = peers[:position]
    for q, a in texts:
        if len(a.split()) >= 4 and any(_norm(p["answers"].get(q.id) or "") == _norm(a) for p in earlier):
            _flag(flags, "duplicate_text", f"Q{survey.questions.index(q) + 1}: same text as an earlier response", -30, hard=True)
            break
    if any(p["answers"] == answers and p.get("user_agent") == r.get("user_agent") for p in earlier):
        _flag(flags, "duplicate", "Identical answers from the same browser as an earlier response", -40, hard=True)

    # Judgment review of the open text (Jev or Claude), when it has run.
    review = r.get("quality_llm") or {}
    if review.get("profile_fit") is not None and review["profile_fit"] < 0.25:
        _flag(flags, "profile_mismatch", f"Answers don't fit their profile (Jev: {review['profile_fit']:.0%} consistent)", -8)
    for item in review.get("answers", []):
        q = questions.get(item.get("id"))
        n = survey.questions.index(q) + 1 if q else "?"
        delta = (int(item.get("relevance", 1)) + int(item.get("specificity", 1)) - 2) * 5
        if delta:
            _flag(flags, "llm_quality", f"Q{n}: {item.get('note') or ('specific and on topic' if delta > 0 else 'vague or off topic')}", delta)
        if item.get("ai_like"):
            _flag(flags, "ai_like", f"Q{n}: reads like machine-written text", -10)

    score = max(0, min(100, BASE + sum(f["delta"] for f in flags), *[f["cap"] for f in flags if "cap" in f]))
    return score, tier_for(score, any(f.get("hard") for f in flags)), flags


def rescore(survey_id: str) -> list[dict]:
    row = store.get_survey(survey_id)
    responses = store.list_responses(survey_id)
    out = []
    for r in responses:
        score, tier, flags = score_response(row["spec"], r, responses)
        store.set_quality(r["token"], score, tier, flags)
        out.append({"token": r["token"], "score": score, "tier": tier})
    return out


REVIEW_PROMPT = """You review open-text answers to a B2B research survey for quality. For each answer, rate:
- relevance: 0 = off topic or nonsense, 1 = loosely related, 2 = answers the question
- specificity: 0 = empty or generic filler, 1 = some detail, 2 = concrete detail only a practitioner would give
- ai_like: true only if it reads like generic machine-written text (polished, hedged, no concrete detail)
- note: at most 8 words explaining the rating

Reply with JSON only: {{"answers": [{{"id": "...", "relevance": 0-2, "specificity": 0-2, "ai_like": false, "note": "..."}}]}}

Survey: {title}
Respondent: {who}
Answers:
{answers}
"""


# ---- Jev: narrow typed questions, combined in code (TypeSafe's composite-scoring pattern) ----

RELEVANCE = ["Off topic, nonsense or no real answer", "Loosely related to the question", "Directly answers the question"]
SPECIFICITY = ["Empty, generic filler or a platitude", "Some concrete detail",
               "Concrete detail only a practitioner would know (tools, numbers, situations)"]
MIN_CONFIDENCE = 0.5  # below this a Score verdict counts as neutral (confidence routing)


def jev_enabled() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY")) and os.environ.get("QUALITY_REVIEWER", "auto") in ("auto", "jev")


def _jev_client():
    from typesafe_sdk import TypeSafeClient

    return TypeSafeClient(model=os.environ.get("JEV_MODEL", "jev-latest"))


def _level(answer, levels: int) -> int:
    """Score answer -> 0..levels-1, or the middle level when Jev isn't confident."""
    if answer is None or answer.confidence < MIN_CONFIDENCE:
        return (levels - 1) // 2
    return max(0, min(levels - 1, round(answer.score)))


def _review_with_jev(survey: Survey, response: dict, texts: list[dict]) -> dict:
    from typesafe_sdk import Noul, Score

    t = response["target"]
    profile = {k: t.get(k) for k in ("title", "seniority", "function", "company", "company_headcount") if t.get(k)}
    state = json.dumps({"survey": survey.title, "respondent_profile": profile,
                        "answers": {q.prompt: response["answers"].get(q.id) for q in survey.questions
                                    if response["answers"].get(q.id) not in (None, "", [])}}, ensure_ascii=False)
    questions = {"profile_fit": Noul(instructions="The respondent's answers are plausible for someone with this job "
                                                  "title, seniority and company size")}
    for x in texts:
        about = f'the answer to "{x["question"]}" (the answer is: "{x["answer"]}")'
        questions[f'{x["id"]}.relevance'] = Score(instructions=f"How directly {about} addresses that question",
                                                  criteria=RELEVANCE)
        questions[f'{x["id"]}.specificity'] = Score(instructions=f"How specific and concrete {about} is",
                                                    criteria=SPECIFICITY)
        questions[f'{x["id"]}.gibberish'] = Noul(instructions=f"{about[0].upper() + about[1:]} is gibberish, keyboard "
                                                              "mash or placeholder text")
        questions[f'{x["id"]}.machine'] = Noul(instructions=f"{about[0].upper() + about[1:]} reads like generic "
                                                            "machine-written text rather than a person's own words")
    with _jev_client() as client:
        result = client.system_one(state=state, questions=questions)

    answers = []
    for x in texts:
        rel, spec = result.scores.get(f'{x["id"]}.relevance'), result.scores.get(f'{x["id"]}.specificity')
        gib, mach = result.nouls.get(f'{x["id"]}.gibberish'), result.nouls.get(f'{x["id"]}.machine')
        relevance, specificity = _level(rel, len(RELEVANCE)), _level(spec, len(SPECIFICITY))
        if gib is not None and gib.noul >= 0.8:
            relevance = specificity = 0
        conf = min(a.confidence for a in (rel, spec) if a is not None) if rel or spec else 0
        note = ("gibberish" if relevance == specificity == 0 and gib is not None and gib.noul >= 0.8 else
                f"{['off topic', 'loosely on topic', 'on topic'][relevance]}, "
                f"{['generic', 'some detail', 'concrete detail'][specificity]}")
        answers.append({"id": x["id"], "relevance": relevance, "specificity": specificity,
                        "ai_like": bool(mach is not None and mach.noul >= 0.75),
                        "note": f"Jev: {note} ({conf:.0%} confident)"})
    fit = result.nouls.get("profile_fit")
    return {"provider": "jev", "model": result.model, "answers": answers,
            "profile_fit": round(fit.noul, 3) if fit is not None else None,
            "raw": {k: v.model_dump(exclude={"legend", "probabilities"}) for k, v in result.answers.items()}}


def review_text(survey_id: str, token: str) -> dict | None:
    """One judgment call per response with open text (Jev if configured, else Claude). Stores it and rescores."""
    row = store.get_survey(survey_id)
    response = next((r for r in store.list_responses(survey_id) if r["token"] == token), None)
    if row is None or response is None:
        return None
    texts = [{"id": q.id, "question": q.prompt, "answer": response["answers"][q.id]}
             for q in row["spec"].questions if q.type == "text" and response["answers"].get(q.id)]
    if not texts:
        return None
    if jev_enabled():
        review = _review_with_jev(row["spec"], response, texts)
        store.set_quality_llm(token, review)
        rescore(survey_id)
        return review
    t = response["target"]
    who = " · ".join(x for x in (t.get("title"), t.get("seniority"), t.get("company")) if x) or "unknown"
    model = os.environ.get("QUALITY_MODEL", "claude-haiku-5-5")
    message = ChatAnthropic(model=model, max_tokens=800).invoke(
        REVIEW_PROMPT.format(title=row["spec"].title, who=who, answers=json.dumps(texts, ensure_ascii=False, indent=1)))
    raw = message.content if isinstance(message.content, str) else "".join(
        b.get("text", "") for b in message.content if isinstance(b, dict))
    match = re.search(r"\{.*\}", raw, re.S)
    review = json.loads(match.group(0)) if match else {"answers": []}
    review.update(model=model, provider="claude")
    store.set_quality_llm(token, review)
    rescore(survey_id)
    return review


def review_in_background(survey_id: str, token: str) -> None:
    def run():
        try:
            review_text(survey_id, token)
        except Exception as e:  # rules-only score stays in place
            print(f"[quality] review failed for {token}: {type(e).__name__}: {e}")

    threading.Thread(target=run, name="quality-review", daemon=True).start()


def summary(survey_id: str) -> dict:
    responses = store.list_responses(survey_id)
    mix = {name: 0 for _, name in TIERS}
    for r in responses:
        if r.get("quality_tier"):
            mix[r["quality_tier"]] += 1
    return {"tiers": mix, "scored": sum(mix.values()), "total": len(responses)}
