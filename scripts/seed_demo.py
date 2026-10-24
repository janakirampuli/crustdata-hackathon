"""Seeds a finished demo campaign into forms.db: an approved survey with its brief, invite template and audience,
80 fictional invitees with their emails, opens, follow-ups, opt-outs and 24 responses (2 of them planted fakes that
fail verification, 1 flagged), then the findings report. Nothing is sent: emails are written to the outbox only.

    uv run python scripts/seed_demo.py              # into data/forms.db (or FORMS_DB)
    uv run python scripts/seed_demo.py --no-report  # skip the findings report (one model call)

People and companies are fictional and their addresses use the reserved .example domain.
"""

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from skills.form_builder import personalize, store  # noqa: E402
from skills.form_builder.schema import Audience, CampaignConfig, Survey  # noqa: E402
from skills.form_builder.tools import base_url  # noqa: E402

SURVEY = {
    "title": "How Bengaluru AI teams source outside data for agents",
    "research_question": "How are Bengaluru AI builders choosing the outside data their agents depend on?",
    "audience": "Engineering and AI leaders at Bengaluru software companies with agents in development or production",
    "intro": ("We're a small research team studying how AI teams in Bengaluru get company and people data into "
              "their agents. It's 7 questions and takes about 3 minutes. Answers are used only for this research, "
              "never for sales, and you can skip anything."),
    "estimated_minutes": 3,
    "questions": [
        {"id": "role", "type": "single_choice",
         "prompt": "Which best describes your role in choosing data infrastructure for your AI agents?",
         "options": ["I make the final call", "I shape the decision", "I use it but don't choose", "Not involved"]},
        {"id": "stage", "type": "single_choice", "prompt": "How far along are your AI agents?",
         "options": ["Prototyping", "Internal tools in production", "Customer-facing in production"]},
        {"id": "sources", "type": "multi_choice",
         "prompt": "Where do your agents get outside data on companies and people today?",
         "help": "Select all that apply.", "allow_other": True,
         "options": ["Our own web scrapers", "Web search APIs", "B2B data providers", "The LLM's own knowledge",
                     "Only our internal data"]},
        {"id": "stale_pain", "type": "scale",
         "prompt": "How much does stale or wrong outside data hurt your agents' output?",
         "scale_min": 1, "scale_max": 5, "min_label": "Not a problem", "max_label": "A top problem"},
        {"id": "top_criterion", "type": "single_choice",
         "prompt": "What matters most when you pick a data source for agents?",
         "options": ["Freshness", "Coverage of Indian companies", "Price per call", "Latency",
                     "Clean, structured fields"]},
        {"id": "monthly_spend", "type": "number",
         "prompt": "About how much do you spend a month on outside data for agents, in USD?"},
        {"id": "blocked", "type": "text", "required": False,
         "prompt": "What's one thing your agents can't do today because of data?"},
    ],
    "email": {
        "subject": "{first_name}, 3 minutes on how {company} sources data for agents?",
        "body": ("Hi {first_name},\n\nWould you be open to a {survey_minutes}-minute research survey on how AI teams "
                 "in Bengaluru get outside data into their agents?\n\n{personal_line}\n\nWe're hearing from a "
                 "small, hand-picked group, so your answers carry real weight. They're used only for this "
                 "research.\n\n{link}\n\nThanks,\nThe Verified Research team"),
        "personal_line_rule": ("One sentence linking their role and company size to why their view on agent data "
                               "matters. Professional facts only."),
        "fallback_line": "We're hearing from engineering and AI leaders at Bengaluru teams like {company}.",
    },
}

BRIEF = """**Objective.** Learn how Bengaluru AI teams get outside company and people data into their agents, and what \
makes them pick one source over another.

**Decision it informs.** Whether to position an agent-ready B2B data API on freshness or on price, and which team \
size to sell to first.

**Key questions**
- Where does outside data come from today: scrapers, search APIs, B2B providers, or the model itself?
- How much does stale data hurt?
- What decides the choice of source?
- What do teams spend each month?

**Hypotheses**
- H1: Most teams still run their own scrapers.
- H2: Freshness matters more than price.
- H3: Larger companies (200+ people) already buy from B2B data providers; startups don't.

**Persona.** CTOs, VPs and heads of engineering or AI at Bengaluru software companies of 11–1,000 people that \
build agents. Crustdata finds about 1,240.

**Sample.** 20 verified responses. **Method.** A 3-minute survey, one personal link per verified person."""

AUDIENCE = {
    "description": "Engineering and AI leaders at Bengaluru software companies, 11–1,000 people, building agents",
    "plan": {"titles": ["CTO", "VP Engineering", "Head of AI", "Director of Engineering", "Engineering Manager"],
             "region": "Bengaluru, Karnataka, India", "company_headcount": {"min": 11, "max": 1000},
             "keywords": ["AI agents", "LLM", "RAG"]},
    "effective_filters": {"op": "and", "conditions": [
        {"column": "current_employers.title", "type": "in",
         "value": ["CTO", "VP Engineering", "Head of AI", "Director of Engineering", "Engineering Manager"]},
        {"column": "region", "type": "(.)", "value": "Bengaluru"},
        {"column": "current_employers.company_headcount_latest", "type": "=>", "value": 11},
        {"column": "current_employers.company_headcount_latest", "type": "=<", "value": 1000},
        {"column": "headline", "type": "(.)", "value": "agents|LLM|RAG"}]},
    "total_count": 1240,
}

COMPANIES = [  # fictional: name, domain stem, headcount
    ("Lumora Labs", "lumoralabs", 34), ("Quillstack", "quillstack", 58), ("Tarkash AI", "tarkash", 22),
    ("Vellum Grid", "vellumgrid", 140), ("Nirvaha", "nirvaha", 410), ("Orbitflux", "orbitflux", 76),
    ("Saptak Systems", "saptak", 820), ("Kavach Cloud", "kavachcloud", 260), ("Indigo Ledger", "indigoledger", 95),
    ("Parallax Health", "parallaxhealth", 180), ("Mithra Analytics", "mithra", 47), ("Tejas Robotics", "tejasrobotics", 330),
    ("Bluefin Pay", "bluefinpay", 560), ("Anvaya", "anvaya", 18), ("Dhruva Data", "dhruvadata", 120),
    ("Corvid Labs", "corvidlabs", 29), ("Samyak Retail Tech", "samyak", 690), ("Helix Freight", "helixfreight", 240),
    ("Prism Legal AI", "prismlegal", 41), ("Kalpa Insurance Tech", "kalpa", 450), ("Nimbus Hire", "nimbushire", 66),
    ("Arka Energy Software", "arka", 150), ("Seva Commerce", "sevacommerce", 980), ("Zephyr Docs", "zephyrdocs", 25),
]
FIRST = ["Aditi", "Rohan", "Kavya", "Arjun", "Meera", "Vikram", "Sneha", "Karthik", "Ananya", "Siddharth", "Pooja",
         "Rahul", "Divya", "Nikhil", "Shreya", "Aravind", "Ishita", "Varun", "Lakshmi", "Pranav", "Nandini", "Harsha",
         "Tanvi", "Manoj", "Ritika", "Suresh", "Deepa", "Akash", "Gayatri", "Vivek"]
LAST = ["Rao", "Iyer", "Nair", "Reddy", "Menon", "Shetty", "Kulkarni", "Bhat", "Hegde", "Krishnan", "Pillai",
        "Gowda", "Sharma", "Murthy", "Desai", "Kamath", "Naidu", "Prasad", "Joshi", "Subramanian"]
ROLES = [  # title, seniority, function
    ("CTO", "CXO", "Engineering"), ("Co-founder & CTO", "CXO", "Engineering"), ("VP Engineering", "VP", "Engineering"),
    ("Head of AI", "Director", "AI / ML"), ("Director of Engineering", "Director", "Engineering"),
    ("Head of Data Science", "Director", "AI / ML"), ("Engineering Manager", "Manager", "Engineering"),
    ("ML Engineering Lead", "Manager", "AI / ML"),
]
TEXT = [
    "Tell a rep that their champion just changed jobs. Our data is months behind.",
    "Answer basic questions about Indian private companies. Global providers barely cover them.",
    "Run research agents at scale. Scraping breaks every week and we babysit it.",
    "Trust the headcount numbers. They're wrong often enough that we hide them.",
    "Enrich a lead in under a second. Our pipeline takes minutes, so the agent waits.",
    "Find the right person in a 400-person account without a human checking LinkedIn.",
    "Explain where a fact came from. Customers ask and we can't show a source.",
    "Watch for funding and hiring signals daily. We batch it weekly because of cost.",
    "Cover tier-2 city companies at all.",
    "Get structured fields instead of HTML we have to parse with another LLM call.",
    "Know if an email is still valid before the agent sends anything.",
    "Keep cost per lookup predictable. One busy day blew our monthly budget.",
]
GROUNDED_LINES = [
    ("As {title} at a {headcount}-person team, you decide what data your agents can trust.",
     ["title", "company_headcount"]),
    ("Running engineering as {title} at {company}, you see where agent data breaks first.", ["title", "company"]),
    ("A {headcount}-person company like {company} is exactly the stage this study is about.",
     ["company_headcount", "company"]),
]
UNGROUNDED_LINE = ("Congrats on {company}'s Series B; teams at that stage feel data pain first.", ["company"])

FAKES = {  # invite index -> (verified, reason, answer overrides)
    5: ("fail", "Crustdata shows this person left Orbitflux in Aug 2026; the profile we invited is out of date",
        {"role": "Not involved", "top_criterion": "Price per call"}),
    17: ("fail", "Same device and network as another respondent's submission 2 minutes earlier",
         {"top_criterion": "Price per call", "monthly_spend": 25000}),
    29: ("flag", "Finished in 22 seconds; the median is 2 min 40 s", {}),
}


class Clock:
    def __init__(self, start: datetime):
        self.t = start

    def at(self, t: datetime) -> None:
        self.t = t

    def iso(self) -> str:
        return self.t.isoformat(timespec="seconds")


def people(rng: random.Random) -> list[dict]:
    names = rng.sample([f"{f} {last}" for f in FIRST for last in LAST], 80)
    out = []
    for i, name in enumerate(names):
        company, stem, headcount = COMPANIES[i % len(COMPANIES)]
        title, seniority, function = ROLES[rng.randrange(len(ROLES))] if i >= 8 else ROLES[i % 3]
        first = name.split()[0].lower()
        out.append({"crustdata_person_id": 7_100_000 + i * 37, "name": name, "title": title, "company": company,
                    "company_domain": f"{stem}.example", "business_email": f"{first}@{stem}.example",
                    "seniority": seniority, "function": function, "company_headcount": headcount,
                    "location": "Bengaluru, Karnataka, India", "headline": f"{title} at {company}",
                    "linkedin_url": None, "why_qualified": f"you're {title} at a {headcount}-person team"})
    return out


def written_line(i: int, p: dict) -> dict | None:
    """The demo's stand-in for the writer model: mostly grounded lines, a few that the check rejects."""
    if i % 11 == 4:
        return None
    line, facts = UNGROUNDED_LINE if i % 13 == 6 else GROUNDED_LINES[i % len(GROUNDED_LINES)]
    return {"personal_line": line.format(title=p["title"], company=p["company"], headcount=p["company_headcount"]),
            "facts_used": facts}


def answers_for(rng: random.Random, p: dict, i: int) -> dict:
    big = p["company_headcount"] > 200
    stage = rng.choices(["Prototyping", "Internal tools in production", "Customer-facing in production"],
                        [1, 3, 4] if big else [3, 4, 2])[0]
    sources = [s for s, chance in [("Our own web scrapers", 0.45 if big else 0.8), ("Web search APIs", 0.55),
                                   ("B2B data providers", 0.7 if big else 0.2), ("The LLM's own knowledge", 0.35),
                                   ("Only our internal data", 0.1)] if rng.random() < chance] or ["Web search APIs"]
    if i % 9 == 3:
        sources.append("Other: GitHub and job-board APIs")
    criterion = rng.choices(["Freshness", "Coverage of Indian companies", "Price per call", "Latency",
                             "Clean, structured fields"], [5, 3, 1 if big else 2.5, 1, 1.5])[0]
    pain = min(5, max(1, round(rng.gauss(3.9 if stage != "Prototyping" else 2.8, 0.8))))
    spend = round(rng.lognormvariate(7.4 if big else 5.6, 0.6) / 50) * 50
    role = rng.choices(["I make the final call", "I shape the decision", "I use it but don't choose"],
                       [5, 3, 1] if p["seniority"] in ("CXO", "VP") else [2, 5, 2])[0]
    return {"role": role, "stage": stage, "sources": sources, "stale_pain": pain, "top_criterion": criterion,
            "monthly_spend": spend}


def seed(report: bool) -> str:
    rng = random.Random(7)
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=3, minutes=10)
    clock = Clock(t0 - timedelta(minutes=25))
    store._now = clock.iso  # every store write below is stamped with the demo's clock

    survey = Survey.model_validate(SURVEY)
    survey_id = store.create_survey(survey, BRIEF)
    targets = people(rng)
    samples = targets[:3]
    preview_emails = [personalize.render(survey, p, f"{base_url()}/s/<personal link>", written_line(i, p))
                      for i, p in enumerate(samples)]
    store.set_email_preview(survey_id, {"samples": samples, "emails": preview_emails})
    clock.at(t0 - timedelta(minutes=12))
    store.set_status(survey_id, "approved")

    clock.at(t0 - timedelta(minutes=2))
    config = CampaignConfig(max_invites=80, target_responses=20, deadline_minutes=240, followup_after_minutes=60,
                            max_followups=1)
    store.set_config(survey_id, config)
    store.log_event(survey_id, "config", detail=config.model_dump())
    store.set_audience(survey_id, Audience.model_validate({**AUDIENCE, "brief": BRIEF}))

    clock.at(t0)
    store.mark_launched(survey_id, config.deadline_minutes)
    store.log_event(survey_id, "launched", detail={"max_invites": 80, "target_responses": 20})
    invites = store.create_invites(survey_id, targets)
    for i, (p, inv) in enumerate(zip(targets, invites)):
        clock.at(t0 + timedelta(seconds=2 * i))
        email = personalize.render(survey, p, f"{base_url()}/s/{inv['token']}", written_line(i, p))
        store.add_outbox(survey_id, inv["token"], "invite", p["business_email"], email["subject"], email["body"])
        store.mark_contacted(inv["token"], p["business_email"], followup=False)
        store.log_event(survey_id, "invited", inv["token"],
                        {"email": p["business_email"], "personalized": email["personalized"]})

    # Who does what, and when (minutes after launch). Responders mostly answer within minutes of opening.
    order = list(range(80))
    rng.shuffle(order)
    responders = list(FAKES) + [i for i in order if i not in FAKES][:21]
    rest = [i for i in order if i not in responders]
    openers_only, opt_outs = rest[:22], rest[22:24]
    timeline = []
    for i in responders:
        late = rng.random() < 0.3
        opened = rng.uniform(64, 150) if late else rng.expovariate(1 / 22)
        took = 0.4 if FAKES.get(i, ("",))[0] == "flag" else rng.uniform(2, 5)
        timeline += [(opened, "open", i), (opened + took, "respond", i)]
    for i in openers_only:
        timeline.append((rng.uniform(3, 160), "open", i))
    for i in opt_outs:
        timeline.append((rng.uniform(5, 90), "opt_out", i))
    timeline.append((60.5, "followups", None))

    responded = set()
    for minutes, kind, i in sorted(timeline, key=lambda e: e[0]):
        clock.at(t0 + timedelta(minutes=minutes))
        if kind == "followups":
            for j, (p, inv) in enumerate(zip(targets, invites)):
                if j in responded or j in opt_outs:
                    continue
                link = f"{base_url()}/s/{inv['token']}"
                store.add_outbox(survey_id, inv["token"], "followup", p["business_email"],
                                 f"Re: {p['name'].split()[0]}, 3 minutes on how {p['company']} sources data for agents?",
                                 f"Hi {p['name'].split()[0]},\n\nA quick nudge in case this got buried. Your view "
                                 f"would really help, and it takes about 3 minutes:\n{link}\n\nNo worries if not. "
                                 f"This is the last reminder.\n\nOpt out: {link}/opt-out\n")
                store.mark_contacted(inv["token"], p["business_email"], followup=True)
                store.log_event(survey_id, "followup", inv["token"], {"n": 1})
            continue
        inv = {**invites[i], "survey_id": survey_id}
        if kind == "open" and store.mark_opened(inv["token"]):
            store.log_event(survey_id, "opened", inv["token"])
        elif kind == "opt_out" and store.opt_out(inv["token"]):
            store.log_event(survey_id, "opted_out", inv["token"])
        elif kind == "respond":
            verified, reason, overrides = FAKES.get(i, ("ok", None, {}))
            answers = {**answers_for(rng, targets[i], i), **overrides}
            if len(responded) % 2 == 0 and verified == "ok":  # about half write the optional text answer
                answers["blocked"] = TEXT[len(responded) // 2 % len(TEXT)]
            # Time and typing counts feed the quality score; fake 29 is the 22-second speeder its reason describes.
            duration = 22 if i == 29 else rng.randint(95, 260)
            text = answers.get("blocked")
            typing = {"active_s": duration,
                      "fields": {"blocked": {"keys": len(text) + rng.randint(0, 12), "pastes": 0}} if text else {}}
            store.save_response(inv, answers, "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Safari/605.1.15",
                                duration, typing)
            _set_verification(inv["token"], verified, reason)
            store.log_event(survey_id, "responded", inv["token"])
            if verified != "ok":
                store.log_event(survey_id, "verification", inv["token"], {"verified": verified, "reason": reason})
            responded.add(i)

    clock.at(clock.t + timedelta(seconds=30))
    store.close_survey(survey_id, "target reached")
    store.log_event(survey_id, "closed", detail={"reason": "target reached"})
    from skills.campaign import quality

    quality.rescore(survey_id)  # rules only; the model review of open text runs from the workspace's Rescore

    if report:
        from skills.campaign import insights

        clock.at(clock.t + timedelta(minutes=1))
        result = insights.generate(survey_id)
        print(result.get("error") or f"Findings written from {result['n']} responses ({result['model']}).")
    return survey_id


def _set_verification(token: str, verified: str, reason: str | None) -> None:
    with store.connect() as conn:
        conn.execute("UPDATE responses SET verified = ?, reason = ? WHERE token = ?", (verified, reason, token))


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-report", action="store_true", help="Skip writing the findings report.")
    args = parser.parse_args()
    survey_id = seed(report=not args.no_report)
    print(f"Seeded survey {survey_id}: {base_url()}/surveys/{survey_id}?tab=analytics")


if __name__ == "__main__":
    main()
