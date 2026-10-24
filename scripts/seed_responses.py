"""Seeds responses into a survey the agent has already launched, so a demo can show answers, quality ranks and the
findings report without waiting days for real people. The survey, invite email, audience and campaign stay as the
agent made them. This adds only what respondents would do: opens, opt-outs and answers that a model writes to fit
each invitee's role and company size.

The invitees are real people from Crustdata, so before writing anything the script gives each one a fictional name,
company, company size and email (role, seniority and function stay). Made-up answers never sit under a real person's
name. The outbox keeps the emails exactly as the agent drafted them.

    uv run python scripts/seed_responses.py <survey_id>              # target_responses answers, launch moved 6 h back
    uv run python scripts/seed_responses.py <survey_id> --responses 9 --hours 20 --story "price wins at startups"

Planted for the checks to catch (with 10+ responses): two answers that fail verification (one left the company, one a
duplicate device), one 20-second speeder that is flagged, and one straight-lined, pasted answer the quality check ranks
low. If the responses reach the target, the survey closes as it would live and the findings report is written
(skip it with --no-report, then ask the agent to write it on camera).
"""

import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from skills.form_builder import store  # noqa: E402
from skills.form_builder.schema import CHOICE_TYPES, OTHER, Question, Survey, parse_answers  # noqa: E402

COMPANIES = [  # fictional, with headcounts spread from seed to mid-size so company-size splits have something to show
    ("Lumora Labs", 34), ("Quillstack", 58), ("Tarkash AI", 22), ("Vellum Grid", 140), ("Nirvaha", 410),
    ("Orbitflux", 76), ("Saptak Systems", 820), ("Kavach Cloud", 260), ("Indigo Ledger", 95), ("Parallax Health", 180),
    ("Mithra Analytics", 47), ("Tejas Robotics", 330), ("Bluefin Pay", 560), ("Anvaya", 18), ("Dhruva Data", 120),
    ("Corvid Labs", 29), ("Samyak Retail Tech", 690), ("Helix Freight", 240), ("Prism Legal AI", 41),
    ("Kalpa Insurance Tech", 450), ("Nimbus Hire", 66), ("Arka Energy Software", 150), ("Seva Commerce", 980),
    ("Zephyr Docs", 25)]
FIRST = ["Aditi", "Rohan", "Kavya", "Arjun", "Meera", "Vikram", "Sneha", "Karthik", "Ananya", "Siddharth", "Pooja",
         "Rahul", "Divya", "Nikhil", "Shreya", "Aravind", "Ishita", "Varun", "Lakshmi", "Pranav", "Nandini", "Harsha",
         "Tanvi", "Manoj", "Ritika", "Suresh", "Deepa", "Akash", "Gayatri", "Vivek"]
LAST = ["Rao", "Iyer", "Nair", "Reddy", "Menon", "Shetty", "Kulkarni", "Bhat", "Hegde", "Krishnan", "Pillai",
        "Gowda", "Sharma", "Murthy", "Desai", "Kamath", "Naidu", "Prasad", "Joshi", "Subramanian"]
PASTED = ("Data quality is a key consideration for our organization. We evaluate multiple factors including accuracy, "
          "cost and reliability to ensure the best outcomes for our stakeholders.")
BROWSERS = ["Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"]
BATCH = 8


class Answer(BaseModel):
    question_id: str
    values: list[str] = Field(description="Choice: the exact option text(s), or 'Other'. Scale or number: one number "
                                          "as text. Text: one string. Empty to skip an optional question.")
    other: str | None = Field(None, description="Only when 'Other' is picked: what they wrote in the box.")


class Respondent(BaseModel):
    respondent: int
    answers: list[Answer]


class Batch(BaseModel):
    respondents: list[Respondent]


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def iso(self) -> str:
        return self.t.isoformat(timespec="seconds")


# --- invitees ------------------------------------------------------------------------------------------------------

def anonymize(survey_id: str, rng: random.Random) -> None:
    """Fictional name, company, size and email for every invitee of this survey; role, seniority and function stay."""
    firsts, lasts = rng.sample(FIRST, len(FIRST)), rng.sample(LAST, len(LAST))
    with store.connect() as conn:
        rows = conn.execute("SELECT token, target FROM invites WHERE survey_id = ?", (survey_id,)).fetchall()
        for i, row in enumerate(rows):
            t = json.loads(row["target"])
            if t.get("anonymized"):
                continue
            real = t.get("company") or "their company"
            company, headcount = rng.choice(COMPANIES)
            name = f"{firsts[i % len(firsts)]} {lasts[(i + i // len(firsts)) % len(lasts)]}"
            stem = company.lower().replace(" ", "")
            email = f"{name.split()[0].lower()}.{name.split()[1].lower()}@{stem}.example"
            why = (t.get("why_qualified") or "").replace(real, company)
            t.update(name=name, company=company, company_headcount=headcount, company_domain=f"{stem}.example",
                     business_email=email,
                     linkedin_url=None, headline=f"{t.get('title') or 'Works'} at {company}", why_qualified=why,
                     anonymized=True)
            conn.execute("UPDATE invites SET target = ?, email = CASE WHEN email IS NULL THEN NULL ELSE ? END "
                         "WHERE token = ?", (json.dumps(t), email, row["token"]))


def backdate(survey_id: str, hours: float) -> None:
    """Moves the whole campaign back so the launch reads `hours` ago and answers can arrive over that window."""
    row = store.get_survey(survey_id)
    launched = datetime.fromisoformat(row["launched_at"])
    shift = timedelta(hours=hours) - (datetime.now(timezone.utc) - launched)
    if shift <= timedelta(0):
        return
    move = lambda v: v and (datetime.fromisoformat(v) - shift).isoformat(timespec="seconds")  # noqa: E731
    tables = {"invites": ("token", ["created_at", "opened_at", "invited_at", "last_contacted_at", "opted_out_at"]),
              "outbox": ("id", ["created_at"]), "events": ("id", ["at"]), "responses": ("token", ["submitted_at"])}
    with store.connect() as conn:
        cols = ["created_at", "updated_at", "approved_at", "launched_at", "closes_at"]
        r = conn.execute(f"SELECT {', '.join(cols)} FROM surveys WHERE id = ?", (survey_id,)).fetchone()
        conn.execute(f"UPDATE surveys SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                     [move(r[c]) for c in cols] + [survey_id])
        for table, (key, cols) in tables.items():
            rows = conn.execute(f"SELECT {key}, {', '.join(cols)} FROM {table} WHERE survey_id = ?", (survey_id,))
            for r in rows.fetchall():
                conn.execute(f"UPDATE {table} SET {', '.join(c + ' = ?' for c in cols)} WHERE {key} = ?",
                             [move(r[c]) for c in cols] + [r[key]])


# --- answers -------------------------------------------------------------------------------------------------------

def _question(q: Question) -> dict:
    out = {"id": q.id, "type": q.type, "prompt": q.prompt, "required": q.required}
    if q.type in CHOICE_TYPES:
        out |= {"options": q.options, "allow_other": q.allow_other}
    if q.type == "scale":
        out |= {"min": q.scale_min, "max": q.scale_max, "min_label": q.min_label, "max_label": q.max_label}
    return out


def _prompt(survey: Survey, brief: str | None, story: str | None, people: list[dict]) -> str:
    pattern = (f"The overall pattern should show: {story}" if story else
               "Let the answers follow from each person's situation. Across the whole sample, some hypotheses in the "
               "brief should hold and at least one should not, and senior and junior people, and small and large "
               "companies, should differ in ways that make sense.")
    return f"""You simulate realistic answers to a B2B research survey for a product demo. Each respondent is a \
working professional; answer as they plausibly would given their role, seniority and company size.

Survey: {survey.title}
Research question: {survey.research_question}
Brief (what the client wants to learn):
{brief or "(none)"}

Questions (JSON):
{json.dumps([_question(q) for q in survey.questions], indent=1)}

Respondents (JSON):
{json.dumps(people, indent=1)}

{pattern}

Rules:
- Choice answers use the option text exactly; single choice picks one. Pick "Other" rarely, with a short specific \
answer in `other`.
- Numbers must be believable for the company size. Scale answers are whole numbers in range.
- Skip about a third of optional questions. Answer every required one.
- Open text: concrete and specific to their work (a tool, a number, a failure they hit), 8 to 40 words, typed casually \
by a busy engineer or leader in India. Vary length and voice. No two answers alike. No em dashes, no polished \
corporate phrasing.
- Return one entry per respondent, using their `respondent` number."""


def write_answers(survey: Survey, brief: str | None, story: str | None, people: list[dict]) -> dict[int, list[Answer]]:
    from langchain_anthropic import ChatAnthropic

    model = os.environ.get("SEED_MODEL") or os.environ.get("AGENT_MODEL") or "claude-haiku-5-5"
    writer = ChatAnthropic(model=model, max_tokens=16000).with_structured_output(Batch)

    def run(batch: list[dict]) -> list[Respondent]:
        return writer.invoke(_prompt(survey, brief, story, batch)).respondents

    batches = [people[i:i + BATCH] for i in range(0, len(people), BATCH)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return {r.respondent: r.answers for result in pool.map(run, batches) for r in result}


def random_value(q: Question, rng: random.Random) -> list[str]:
    if q.type == "single_choice":
        return [rng.choice(q.options)]
    if q.type == "multi_choice":
        return rng.sample(q.options, rng.randint(1, min(3, len(q.options))))
    if q.type == "scale":
        return [str(rng.randint(q.scale_min, q.scale_max))]
    if q.type == "number":
        return [str(rng.choice([1, 2, 5, 10, 20]))]
    return []


def to_answers(survey: Survey, written: list[Answer], rng: random.Random) -> dict:
    """The model's answers as a submitted form, run through the same validation as the real form. A question the
    model got wrong gets a random valid answer instead."""
    form = {}
    for a in written:
        q = next((q for q in survey.questions if q.id == a.question_id), None)
        if q is None:
            continue
        values = a.values
        if q.type in CHOICE_TYPES and q.allow_other and "Other" not in q.options:
            values = [OTHER if v == "Other" else v for v in values]
        form[q.id] = values
        if a.other:
            form[f"{q.id}__other"] = [a.other]
    answers, errors = parse_answers(survey, form)
    for qid in errors:
        q = next(q for q in survey.questions if q.id == qid)
        form[qid] = random_value(q, rng)
        form.pop(f"{qid}__other", None)
    return parse_answers(survey, form)[0] if errors else answers


def straight_lined(survey: Survey) -> dict:
    form = {}
    for q in survey.questions:
        if q.type in CHOICE_TYPES:
            form[q.id] = [q.options[0]]
        elif q.type == "scale":
            form[q.id] = [str((q.scale_min + q.scale_max) // 2)]
        elif q.type == "number":
            form[q.id] = ["0"]
        else:
            form[q.id] = [PASTED]
    return parse_answers(survey, form)[0]


# --- seeding -------------------------------------------------------------------------------------------------------

def seed(survey_id: str, responses: int | None = None, hours: float = 6, story: str | None = None,
         seed_value: int = 7, review: bool = True, report: bool = True) -> dict:
    rng = random.Random(seed_value)
    row = store.get_survey(survey_id)
    if row is None or row["status"] != "fielding":
        raise SystemExit(f"Survey {survey_id} isn't fielding. Launch it from the chat first.")
    survey, config = row["spec"], row["config"]

    anonymize(survey_id, rng)
    backdate(survey_id, hours)
    row = store.get_survey(survey_id)
    eligible = [p for p in store.list_participants(survey_id) if p["state"] in ("created", "invited", "opened")]
    n = min(responses or config.target_responses, len(eligible))
    rng.shuffle(eligible)
    responders, rest = eligible[:n], eligible[n:]
    opt_outs = rest[:2] if len(rest) >= 6 else []
    openers = [p for p in rest[len(opt_outs):] if rng.random() < 0.45]

    people = [{"respondent": i, "title": p["target"].get("title"), "seniority": p["target"].get("seniority"),
               "function": p["target"].get("function"), "company_headcount": p["target"].get("company_headcount")}
              for i, p in enumerate(responders)]
    written = write_answers(survey, row["brief"], story, people)

    # Planted cases for the checks; indexes into responders.
    plants = {}
    if n >= 10:
        plants = {1: "left", 4: "duplicate", 7: "speeder", 9: "pasted"}
    expected = survey.estimated_minutes * 60
    launched = datetime.fromisoformat(row["launched_at"])
    now = datetime.now(timezone.utc) - timedelta(minutes=2)
    window = (now - launched).total_seconds()

    def at(fraction: float) -> datetime:
        return launched + timedelta(seconds=min(fraction, 0.97) * window)

    timeline, durations = [], {}
    for i, p in enumerate(responders):
        opened = at(rng.expovariate(4) if rng.random() < 0.7 else rng.uniform(0.3, 0.95))
        durations[i] = 20 if plants.get(i) == "speeder" else round(expected * rng.uniform(0.6, 1.7))
        timeline += [(opened, "open", i), (opened + timedelta(seconds=durations[i] + rng.randint(5, 40)), "respond", i)]
    timeline += [(at(rng.uniform(0.02, 0.9)), "open", p) for p in openers]
    timeline += [(at(rng.uniform(0.05, 0.7)), "opt_out", p) for p in opt_outs]

    clock = Clock(launched)
    real_now = store._now
    store._now = clock.iso
    answers_by = {}
    try:
        for t, kind, who in sorted(timeline, key=lambda e: e[0]):
            clock.t = min(t, now)
            p = responders[who] if isinstance(who, int) else who
            token = p["token"]
            if kind == "open" and store.mark_opened(token):
                store.log_event(survey_id, "opened", token)
            elif kind == "opt_out" and store.opt_out(token):
                store.log_event(survey_id, "opted_out", token)
            elif kind == "respond":
                plant = plants.get(who)
                if plant == "duplicate" and answers_by:
                    answers = dict(list(answers_by.values())[-1])
                elif plant == "pasted":
                    answers = straight_lined(survey)
                else:
                    answers = to_answers(survey, written.get(who, []), rng)
                answers_by[who] = answers
                texts = [q.id for q in survey.questions if q.type == "text" and answers.get(q.id)]
                fields = {qid: ({"keys": 0, "pastes": 1, "pasted_chars": len(answers[qid])} if plant == "pasted" else
                                {"keys": len(answers[qid]) + rng.randint(0, 15), "pastes": 0}) for qid in texts}
                duration = durations[who]
                store.save_response({**p, "survey_id": survey_id}, answers, rng.choice(BROWSERS), duration,
                                    {"active_s": duration, "fields": fields})
                store.log_event(survey_id, "responded", token)
                verified, reason = "ok", None
                if plant == "left":
                    month = (launched - timedelta(days=rng.randint(40, 120))).strftime("%b %Y")
                    verified, reason = "fail", (f"Crustdata shows {p['target']['name']} left {p['target']['company']} "
                                                f"in {month}; the invited profile is out of date")
                elif plant == "duplicate":
                    verified, reason = "fail", "Same device and network as an earlier submission, with matching answers"
                elif plant == "speeder":
                    verified, reason = "flag", f"Finished in {duration} seconds; the estimate is {expected // 60} min"
                with store.connect() as conn:
                    conn.execute("UPDATE responses SET verified = ?, reason = ? WHERE token = ?",
                                 (verified, reason, token))
                if verified != "ok":
                    store.log_event(survey_id, "verification", token, {"verified": verified, "reason": reason})

        from skills.campaign import quality, service

        quality.rescore(survey_id)
        if review:  # the model review of open text, as a live submit would queue it
            tokens = [r["token"] for r in store.list_responses(survey_id)
                      if any(q.type == "text" and r["answers"].get(q.id) for q in survey.questions)]
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda tok: quality.review_text(survey_id, tok), tokens))
        clock.t = now
        service.after_response(survey_id, report=False)
    finally:
        store._now = real_now
    findings = False
    if report and store.get_survey(survey_id)["status"] == "closed":
        from skills.campaign import insights

        findings = "error" not in insights.generate(survey_id)
    return {"responses": n, "opened": len(openers), "opted_out": len(opt_outs), "planted": len(plants),
            "status": store.get_survey(survey_id)["status"], "findings": findings}


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("survey_id")
    parser.add_argument("--responses", type=int, help="How many answers (default: the survey's target_responses).")
    parser.add_argument("--hours", type=float, default=6, help="How long ago the launch should read (default 6).")
    parser.add_argument("--story", help="The pattern the answers should show, e.g. 'freshness beats price for managers'.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--no-review", action="store_true", help="Skip the model review of open text.")
    parser.add_argument("--no-report", action="store_true", help="Don't write the findings report when it closes.")
    args = parser.parse_args()
    result = seed(args.survey_id, args.responses, args.hours, args.story, args.seed, review=not args.no_review,
                  report=not args.no_report)
    from skills.form_builder.tools import base_url

    print(f"{result['responses']} responses, {result['opened']} more opens, {result['opted_out']} opt-outs, "
          f"{result['planted']} planted; survey is {result['status']}"
          f"{', findings written' if result['findings'] else ''}.")
    print(f"{base_url()}/surveys/{args.survey_id}?tab=responses")


if __name__ == "__main__":
    main()
