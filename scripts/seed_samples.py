"""Seeds three sample surveys, one per stage, so every screen has something to show:

  completed   the finished demo campaign from seed_demo.py (80 invited, 24 responses, closed, findings report)
  live        fielding now: launched 70 minutes ago, ~2h50m left, 42 of 60 invited, 9 of 20 responses so far
  ready       approved with its brief, audience, Crustdata filters, settings and email preview, nobody invited yet

    uv run python scripts/seed_samples.py              # into data/forms.db (or FORMS_DB)
    uv run python scripts/seed_samples.py --no-report  # skip the completed survey's findings report (one model call)

Rerunning replaces the samples it seeded before (ids kept in data/sample_surveys.json) and leaves other surveys alone.
People and companies are fictional and use the reserved .example domain. Nothing is sent.
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

import seed_demo  # noqa: E402
from skills.form_builder import personalize, store  # noqa: E402
from skills.form_builder.schema import Audience, CampaignConfig, Survey  # noqa: E402
from skills.form_builder.tools import base_url  # noqa: E402

REGISTRY = Path(__file__).resolve().parents[1] / "data" / "sample_surveys.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"

# ---------------------------------------------------------------- live: fintech observability, fielding now

LIVE_SURVEY = {
    "title": "How Indian fintech CTOs choose observability tools",
    "research_question": "How do engineering leaders at Indian fintechs pick and pay for observability, and what would make them switch?",
    "audience": "CTOs, VPs and Heads of Engineering at Indian fintech and payments companies with 50-2,000 people",
    "intro": "We're researching how fintech engineering teams in India choose observability tools. It takes about 3 minutes. "
             "Answers are used only for this research and shared back in aggregate, never for sales.",
    "estimated_minutes": 3,
    "questions": [
        {"id": "role", "type": "single_choice", "prompt": "What is your role in choosing observability tools?",
         "options": ["I make the final call", "I shape the decision", "I use what's chosen", "Not involved"]},
        {"id": "stack", "type": "multi_choice", "prompt": "Which tools does your team run in production today?",
         "options": ["Datadog", "Grafana + Prometheus", "New Relic", "Elastic", "Built in-house"], "allow_other": True},
        {"id": "criterion", "type": "single_choice", "prompt": "What matters most when you pick a tool?",
         "options": ["Price at our volume", "Data residency in India", "OpenTelemetry support", "Ease of setup",
                     "Alert quality"]},
        {"id": "bill_pain", "type": "scale", "prompt": "How painful is your observability bill today?",
         "scale_min": 1, "scale_max": 5, "min_label": "Not a concern", "max_label": "A top-3 cost problem"},
        {"id": "monthly_spend", "type": "number", "prompt": "Roughly what do you spend per month, in USD?",
         "required": False},
        {"id": "switch_trigger", "type": "text", "prompt": "What would make you switch tools in the next year?",
         "required": False},
    ],
    "email": {
        "subject": "{first_name}, 3 minutes on observability at {company}?",
        "body": "Hi {first_name},\n\nWould you be open to a 3-minute research survey on how fintech teams choose "
                "observability tools?\n\n{personal_line}\n\nIt's 6 questions:\n{link}\n\nThanks,\nThe research team",
        "personal_line_rule": "One sentence linking their role and team size to the observability question.",
        "fallback_line": "As {title} at {company}, your view on tooling and cost would really help.",
    },
}
LIVE_BRIEF = """**Objective.** Learn how Indian fintech engineering leaders choose and pay for observability.
**Decision it informs.** Which integrations our monitoring product builds first, and whether India data residency leads the pitch.
**Key questions.** Current stack; top selection criterion; how painful the bill is; what would trigger a switch.
**Hypotheses.** Datadog dominates at scale but its bill is the top pain; data residency matters more than at non-fintechs."""
LIVE_AUDIENCE = {
    "description": "CTOs, VPs and Heads of Engineering at Indian fintech and payments companies, 50-2,000 people",
    "plan": {"currentJobTitles": ["CTO", "VP Engineering", "Head of Engineering", "Head of Platform"],
             "currentSeniorityLevels": ["CXO", "Vice President", "Director"], "personCountries": ["India"],
             "minHeadcount": 50, "maxHeadcount": 2000, "companyIndustries": ["Financial Services", "Payments"]},
    "effective_filters": {"op": "and", "conditions": [
        {"op": "or", "conditions": [{"field": "experience.employment_details.current.title", "type": "(.)", "value": v}
                                    for v in ["CTO", "VP Engineering", "Head of Engineering", "Head of Platform"]]},
        {"field": "experience.employment_details.current.seniority_level", "type": "in",
         "value": ["CXO", "Vice President", "Director"]},
        {"field": "basic_profile.location.country", "type": "in", "value": ["India"]},
        {"field": "experience.employment_details.current.company_headcount_latest", "type": "=>", "value": 50},
        {"field": "experience.employment_details.current.company_headcount_latest", "type": "=<", "value": 2000},
        {"field": "experience.employment_details.current.company_industries", "type": "in",
         "value": ["Financial Services", "Payments"]}]},
    "total_count": 312,
}
LIVE_COMPANIES = [("Paylane", "paylane", 340), ("Ledgerly", "ledgerly", 120), ("Rupeeflow", "rupeeflow", 860),
                  ("Kredible", "kredible", 210), ("Settlewise", "settlewise", 1500), ("Tallybox", "tallybox", 75),
                  ("Fundmint", "fundmint", 430), ("Clearpay Labs", "clearpaylabs", 95), ("Vaultline", "vaultline", 640),
                  ("Lendora", "lendora", 180)]
LIVE_ROLES = [("CTO", "CXO"), ("VP Engineering", "Vice President"), ("Head of Engineering", "Director"),
              ("Head of Platform", "Director")]
SWITCH_TEXT = [
    "If the Datadog renewal goes up again by 30% we move logs to Grafana Cloud and keep APM only",
    "RBI data localisation audits; we need every trace stored in India with proof for the auditors",
    "Proper OpenTelemetry support so we stop paying per host for agents we don't control",
    "Alert noise. Our on-call gets 200 pages a week and half are duplicates across tools",
    "A tool that prices by data volume we can predict, not custom metrics that explode during sales",
    "Honestly nothing this year, the migration cost is higher than the bill savings",
]

# ---------------------------------------------------------------- ready: AI code review pricing, approved

READY_SURVEY = {
    "title": "Per-seat vs per-repo pricing for AI code review",
    "research_question": "Would engineering leaders at Indian SaaS companies rather pay for an AI code-review tool per seat or per repository?",
    "audience": "VPs and Directors of Engineering at Indian SaaS companies with 50-500 people",
    "intro": "We're researching how engineering teams want to buy AI code-review tools. It takes about 3 minutes. "
             "Answers are used only for this research, never for sales.",
    "estimated_minutes": 3,
    "questions": [
        {"id": "role", "type": "single_choice", "prompt": "What is your role in buying developer tools?",
         "options": ["I approve the budget", "I evaluate and recommend", "I use what's chosen", "Not involved"]},
        {"id": "uses_ai_review", "type": "single_choice", "prompt": "Does your team use an AI code-review tool today?",
         "options": ["Yes, paid", "Yes, free tier or trial", "Evaluating one", "No"]},
        {"id": "preferred_model", "type": "single_choice", "prompt": "Which pricing would you rather pay?",
         "options": ["Per seat (each developer)", "Per repository", "Per pull request reviewed", "Flat team plan"]},
        {"id": "seat_too_expensive", "type": "number", "prompt": "At what price per developer per month, in USD, "
                                                                 "would it be too expensive to consider?"},
        {"id": "bargain", "type": "number", "prompt": "At what price per developer per month, in USD, "
                                                      "would it feel like a bargain?"},
        {"id": "deal_breaker", "type": "text", "prompt": "What would stop you from buying one?", "required": False},
    ],
    "email": {
        "subject": "{first_name}, how should AI code review be priced?",
        "body": "Hi {first_name},\n\nWould you be open to a 3-minute research survey on how teams want to pay for "
                "AI code review?\n\n{personal_line}\n\nIt's 6 questions:\n{link}\n\nThanks,\nThe research team",
        "personal_line_rule": "One sentence tying their role and team size to how they buy developer tools.",
        "fallback_line": "As {title} at {company}, you're exactly who we'd like to hear from.",
    },
}
READY_BRIEF = """**Objective.** Find out whether Indian SaaS engineering leaders prefer per-seat or per-repo pricing for AI code review.
**Decision it informs.** Our launch price model and the price point for the team plan.
**Key questions.** Current use of AI review; preferred pricing unit; price thresholds (Van Westendorp: too expensive, bargain); deal breakers.
**Hypotheses.** Teams with many small repos prefer per-seat; the "too expensive" line sits near $30 per developer."""
READY_AUDIENCE = {
    "description": "VPs and Directors of Engineering at Indian SaaS companies with 50-500 employees",
    "plan": {"currentJobTitles": ["VP Engineering", "Director of Engineering", "Head of Engineering"],
             "currentSeniorityLevels": ["Vice President", "Director"], "personCountries": ["India"],
             "minHeadcount": 50, "maxHeadcount": 500, "companyIndustries": ["Software Development"]},
    "effective_filters": {"op": "and", "conditions": [
        {"op": "or", "conditions": [{"field": "experience.employment_details.current.title", "type": "(.)", "value": v}
                                    for v in ["VP Engineering", "Director of Engineering", "Head of Engineering"]]},
        {"field": "experience.employment_details.current.seniority_level", "type": "in",
         "value": ["Vice President", "Director"]},
        {"field": "basic_profile.location.country", "type": "in", "value": ["India"]},
        {"field": "experience.employment_details.current.company_headcount_latest", "type": "=>", "value": 50},
        {"field": "experience.employment_details.current.company_headcount_latest", "type": "=<", "value": 500},
        {"field": "experience.employment_details.current.company_industries", "type": "in",
         "value": ["Software Development"]}]},
    "total_count": 486,
}
READY_SAMPLES = [
    {"crustdata_person_id": 9_200_001, "name": "Nikhil Bhat", "title": "VP Engineering", "company": "Stackwell",
     "company_headcount": 220, "business_email": "nikhil@stackwell.example", "seniority": "Vice President"},
    {"crustdata_person_id": 9_200_002, "name": "Shreya Pillai", "title": "Director of Engineering", "company": "Formloop",
     "company_headcount": 140, "business_email": "shreya@formloop.example", "seniority": "Director"},
    {"crustdata_person_id": 9_200_003, "name": "Aman Kulkarni", "title": "Head of Engineering", "company": "Billdesk Cloud",
     "company_headcount": 410, "business_email": "aman@billdeskcloud.example", "seniority": "Director"},
]


class Clock(seed_demo.Clock):
    pass


def _live_people(rng: random.Random, n: int) -> list[dict]:
    names = rng.sample([f"{f} {last}" for f in seed_demo.FIRST for last in seed_demo.LAST], n)
    out = []
    for i, name in enumerate(names):
        company, stem, headcount = LIVE_COMPANIES[i % len(LIVE_COMPANIES)]
        title, seniority = LIVE_ROLES[rng.randrange(len(LIVE_ROLES))]
        out.append({"crustdata_person_id": 8_300_000 + i * 41, "name": name, "title": title, "company": company,
                    "company_domain": f"{stem}.example", "business_email": f"{name.split()[0].lower()}@{stem}.example",
                    "seniority": seniority, "function": "Engineering", "company_headcount": headcount,
                    "location": "Bengaluru, Karnataka, India" if i % 3 else "Mumbai, Maharashtra, India",
                    "why_qualified": f"you run engineering as {title} at a {headcount}-person fintech"})
    return out


def _live_answers(rng: random.Random, p: dict, k: int) -> dict:
    """k is the respondent's position; each written answer is used once, as real people don't repeat each other."""
    big = p["company_headcount"] > 400
    stack = [s for s, chance in [("Datadog", 0.75 if big else 0.4), ("Grafana + Prometheus", 0.55), ("New Relic", 0.2),
                                 ("Elastic", 0.3), ("Built in-house", 0.15)] if rng.random() < chance] or ["Grafana + Prometheus"]
    answers = {
        "role": rng.choices(["I make the final call", "I shape the decision", "I use what's chosen"],
                            [5, 3, 1] if p["seniority"] == "CXO" else [2, 5, 1])[0],
        "stack": stack,
        "criterion": rng.choices(["Price at our volume", "Data residency in India", "OpenTelemetry support",
                                  "Ease of setup", "Alert quality"], [4, 3.5 if big else 2, 2, 1, 1.5])[0],
        "bill_pain": min(5, max(1, round(rng.gauss(4.0 if "Datadog" in stack else 2.9, 0.8)))),
        "monthly_spend": round(rng.lognormvariate(9.1 if big else 7.8, 0.5) / 100) * 100,
    }
    if k < len(SWITCH_TEXT):
        answers["switch_trigger"] = SWITCH_TEXT[k]
    return answers


def seed_live() -> str:
    from skills.campaign import quality

    rng = random.Random(23)
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=70)
    clock = Clock(t0 - timedelta(minutes=40))
    store._now = clock.iso

    survey = Survey.model_validate(LIVE_SURVEY)
    survey_id = store.create_survey(survey, LIVE_BRIEF)
    targets = _live_people(rng, 42)
    store.set_email_preview(survey_id, {"samples": targets[:3], "emails": [
        personalize.render(survey, p, f"{base_url()}/s/<personal link>", None) for p in targets[:3]]})
    clock.at(t0 - timedelta(minutes=20))
    store.set_status(survey_id, "approved")
    clock.at(t0 - timedelta(minutes=3))
    config = CampaignConfig(max_invites=60, target_responses=20, deadline_minutes=240, followup_after_minutes=90,
                            max_followups=1)
    store.set_config(survey_id, config)
    store.log_event(survey_id, "config", detail=config.model_dump())
    store.set_audience(survey_id, Audience.model_validate({**LIVE_AUDIENCE, "brief": LIVE_BRIEF}))

    clock.at(t0)
    store.mark_launched(survey_id, config.deadline_minutes)
    store.log_event(survey_id, "launched", detail={"max_invites": 60, "target_responses": 20})
    invites = store.create_invites(survey_id, targets)
    for i, (p, inv) in enumerate(zip(targets, invites)):
        clock.at(t0 + timedelta(seconds=2 * i))
        email = personalize.render(survey, p, f"{base_url()}/s/{inv['token']}", None)
        store.add_outbox(survey_id, inv["token"], "invite", p["business_email"], email["subject"], email["body"])
        store.mark_contacted(inv["token"], p["business_email"], followup=False)
        store.log_event(survey_id, "invited", inv["token"], {"email": p["business_email"], "personalized": False})

    order = list(range(42))
    rng.shuffle(order)
    responders, openers, opt_out = order[:9], order[9:19], order[19]
    speeder = responders[4]
    timeline = [(rng.uniform(4, 60), "open", i) for i in openers] + [(rng.uniform(10, 50), "opt_out", opt_out)]
    for i in responders:
        opened = rng.uniform(2, 62)
        timeline += [(opened, "open", i), (opened + (0.3 if i == speeder else rng.uniform(2, 5)), "respond", i)]
    answered = 0
    for minutes, kind, i in sorted(timeline):
        clock.at(t0 + timedelta(minutes=minutes))
        inv = {**invites[i], "survey_id": survey_id}
        if kind == "open" and store.mark_opened(inv["token"]):
            store.log_event(survey_id, "opened", inv["token"])
        elif kind == "opt_out" and store.opt_out(inv["token"]):
            store.log_event(survey_id, "opted_out", inv["token"])
        elif kind == "respond":
            answers = _live_answers(rng, targets[i], answered)
            answered += 1
            if i == speeder:  # planted: rushes through with the first options and no text
                answers = {"role": "I make the final call", "stack": ["Datadog"], "criterion": "Price at our volume",
                           "bill_pain": 3}
            duration = 18 if i == speeder else rng.randint(100, 240)
            text = answers.get("switch_trigger")
            typing = {"active_s": duration,
                      "fields": {"switch_trigger": {"keys": len(text) + rng.randint(0, 10), "pastes": 0}} if text else {}}
            store.save_response(inv, answers, UA, duration, typing)
            store.log_event(survey_id, "responded", inv["token"])
    quality.rescore(survey_id)
    return survey_id


def seed_ready() -> str:
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=15)
    clock = Clock(t0)
    store._now = clock.iso
    survey = Survey.model_validate(READY_SURVEY)
    survey_id = store.create_survey(survey, READY_BRIEF)
    store.set_email_preview(survey_id, {"samples": READY_SAMPLES, "emails": [
        personalize.render(survey, p, f"{base_url()}/s/<personal link>", None) for p in READY_SAMPLES]})
    clock.at(t0 + timedelta(minutes=8))
    store.set_status(survey_id, "approved")
    clock.at(t0 + timedelta(minutes=10))
    config = CampaignConfig(max_invites=120, target_responses=25, deadline_minutes=360, followup_after_minutes=120,
                            max_followups=1)
    store.set_config(survey_id, config)
    store.log_event(survey_id, "config", detail=config.model_dump())
    store.set_audience(survey_id, Audience.model_validate({**READY_AUDIENCE, "brief": READY_BRIEF}))
    return survey_id


def _forget_previous() -> None:
    if not REGISTRY.exists():
        return
    ids = json.loads(REGISTRY.read_text()).get("surveys", [])
    with store.connect() as conn:
        for sid in ids:
            for table in ("responses", "invites", "events", "outbox", "insights"):
                conn.execute(f"DELETE FROM {table} WHERE survey_id = ?", (sid,))
            conn.execute("DELETE FROM surveys WHERE id = ?", (sid,))
    print(f"Removed {len(ids)} previously seeded sample surveys.")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-report", action="store_true", help="Skip the completed survey's findings report.")
    args = parser.parse_args()

    real_now = store._now
    _forget_previous()
    seeded = {}
    try:
        seeded["completed"] = seed_demo.seed(report=not args.no_report)
        store._now = real_now
        seeded["live"] = seed_live()
        store._now = real_now
        seeded["ready"] = seed_ready()
    finally:
        store._now = real_now
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps({"surveys": list(seeded.values())}, indent=1))
    for stage, sid in seeded.items():
        print(f"{stage:>9}: {base_url()}/surveys/{sid}")


if __name__ == "__main__":
    main()
