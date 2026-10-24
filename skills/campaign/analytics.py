"""Deterministic survey statistics: funnel, per-question summaries and segment splits by Crustdata fields.
Responses marked verified=fail are excluded; everything else counts."""

from collections import Counter
from statistics import mean, median, quantiles

from skills.form_builder import store
from skills.form_builder.schema import Survey

SEGMENTS = {
    "seniority": "Seniority",
    "function": "Function",
    "company_size": "Company size",
}


def company_size(headcount) -> str | None:
    try:
        n = int(headcount)
    except (TypeError, ValueError):
        return None
    for limit, label in ((50, "1–50"), (200, "51–200"), (1000, "201–1,000")):
        if n <= limit:
            return label
    return "1,000+"


def segment_value(target: dict, segment: str) -> str:
    if segment == "company_size":
        return company_size(target.get("company_headcount")) or "Unknown"
    return target.get(segment) or "Unknown"


def _choice_key(value: str) -> str:
    return "Other" if isinstance(value, str) and value.startswith("Other: ") else value


def summarize_question(q, answers: list) -> dict:
    values = [a for a in answers if a not in (None, [], "")]
    out = {"id": q.id, "type": q.type, "prompt": q.prompt, "n": len(values)}
    if q.type == "single_choice":
        counts = Counter(_choice_key(v) for v in values)
        options = q.options + (["Other"] if q.allow_other else [])
        out["options"] = [{"label": o, "count": counts.get(o, 0), "pct": _pct(counts.get(o, 0), len(values))} for o in options]
        out["other_text"] = [v[7:] for v in values if isinstance(v, str) and v.startswith("Other: ")]
    elif q.type == "multi_choice":
        counts = Counter(_choice_key(x) for v in values for x in v)
        options = q.options + (["Other"] if q.allow_other else [])
        out["options"] = sorted(({"label": o, "count": counts.get(o, 0), "pct": _pct(counts.get(o, 0), len(values))}
                                 for o in options), key=lambda o: -o["count"])
        out["other_text"] = [x[7:] for v in values for x in v if isinstance(x, str) and x.startswith("Other: ")]
    elif q.type == "scale":
        nums = [int(v) for v in values]
        counts = Counter(nums)
        out["distribution"] = [{"label": str(k), "count": counts.get(k, 0), "pct": _pct(counts.get(k, 0), len(nums))}
                               for k in range(q.scale_min, q.scale_max + 1)]
        out["min_label"], out["max_label"] = q.min_label, q.max_label
        if nums:
            out["mean"] = round(mean(nums), 2)
        if nums and q.scale_min == 0 and q.scale_max == 10:
            promoters, detractors = sum(n >= 9 for n in nums), sum(n <= 6 for n in nums)
            out["nps"] = round((promoters - detractors) / len(nums) * 100)
    elif q.type == "number":
        nums = sorted(float(v) for v in values)
        if nums:
            out.update(min=nums[0], max=nums[-1], median=median(nums), mean=round(mean(nums), 2))
            if len(nums) >= 4:
                q1, _, q3 = quantiles(nums, n=4)
                out.update(p25=q1, p75=q3)
    else:
        out["answers"] = [str(v) for v in values]
    return out


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def compute(survey_id: str) -> dict:
    row = store.get_survey(survey_id)
    survey: Survey = row["spec"]
    every = store.list_responses(survey_id)
    responses = [r for r in every if r["verified"] != "fail"]
    st = store.invite_stats(survey_id)
    participants = store.list_participants(survey_id)
    questions = [summarize_question(q, [r["answers"].get(q.id) for r in responses]) for q in survey.questions]
    for qs, r_text in zip(questions, survey.questions):
        if qs["type"] == "text":
            qs["answers"] = [{"text": r["answers"][r_text.id], "who": _who(r["target"])}
                             for r in responses if r["answers"].get(r_text.id)]

    segments = {}
    for seg in SEGMENTS:
        mix = Counter(segment_value(r["target"], seg) for r in responses)
        splits = {}
        for q in survey.questions:
            if q.type not in ("single_choice", "multi_choice"):
                continue
            table = {}
            for value in mix:
                group = [r["answers"].get(q.id) for r in responses if segment_value(r["target"], seg) == value]
                table[value] = summarize_question(q, group)["options"]
            splits[q.id] = table
        segments[seg] = {"label": SEGMENTS[seg], "mix": dict(mix.most_common()), "splits": splits}

    return {
        "survey_id": survey_id,
        "title": survey.title,
        "funnel": {"selected": len(participants), "invited": st["invited"], "opened": st["opened"],
                   "responded": st["responded"], "opted_out": st["opted_out"], "counted": len(responses)},
        "verification": _verification(every),
        "response_rate_pct": _pct(st["responded"], st["invited"]),
        "questions": questions,
        "segments": segments,
    }


def _verification(responses: list[dict]) -> dict:
    """How many answers passed the identity checks. Failed ones are excluded from every number above."""
    counts = Counter(r["verified"] for r in responses)
    notes = lambda state: [{"who": _who(r["target"]), "reason": r["reason"]} for r in responses if r["verified"] == state]
    return {"verified": counts["ok"], "flagged": counts["flag"], "pending": counts["pending"],
            "excluded": counts["fail"], "flagged_reasons": notes("flag"), "excluded_reasons": notes("fail")}


def _who(target: dict) -> str:
    return " · ".join(x for x in (target.get("title"), target.get("company")) if x) or "Respondent"
