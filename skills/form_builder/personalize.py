"""Invite emails from the approved template. Code fills the data placeholders; a small model writes {personal_line}
per person, and a line that cites anything outside that person's Crustdata facts falls back to the template's
fallback_line. EMAIL_MODEL picks the model (default claude-haiku-5-5).
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from .schema import PERSONAL_LINE, Survey

# Professional facts a personal line may use. Location and other roles stay out: too personal for a cold email.
FACTS = ("title", "company", "headline", "seniority", "function", "company_headcount", "role_start_date")
FOOTER = ("This link is personal to you and works once. Answers are used for this research only, never for sales.\n\n"
          "Opt out: {link}/opt-out")
BATCH = 10
MAX_LINE = 240


class PersonalLine(BaseModel):
    crustdata_person_id: str
    personal_line: str = Field(description="One sentence, at most 30 words.")
    facts_used: list[str] = Field(description=f"Which facts the sentence relies on, from: {', '.join(FACTS)}.")


class PersonalLines(BaseModel):
    lines: list[PersonalLine]


def facts_of(target: dict) -> dict:
    return {k: target[k] for k in FACTS if target.get(k) not in (None, "", [])}


def _prompt(survey: Survey, people: list[dict]) -> str:
    return f"""You write one sentence per person for a research survey invitation. It goes where the email says \
{{{PERSONAL_LINE}}}, after the greeting.

Study: {survey.title}
Research question: {survey.research_question}
Audience: {survey.audience}
Rule for the sentence (approved by the client): {survey.email.personal_line_rule}

Use only the facts given for that person. Never add a number, company, product, event or name that isn't in their
facts or in the study description above. No flattery, no "I saw your profile", no greeting, no link. List in
facts_used every fact the sentence relies on.

People (JSON):
{json.dumps(people, default=str, indent=1)}"""


def write_lines(survey: Survey, targets: list[dict]) -> dict[str, dict]:
    """crustdata_person_id -> {personal_line, facts_used}. People the model skips are simply missing."""
    if not targets:
        return {}
    from langchain_anthropic import ChatAnthropic

    llm = ChatAnthropic(model=os.environ.get("EMAIL_MODEL") or "claude-haiku-5-5", max_tokens=4000)
    writer = llm.with_structured_output(PersonalLines)
    people = [{"crustdata_person_id": str(t["crustdata_person_id"]), "name": t.get("name"), **facts_of(t)}
              for t in targets]

    def run(batch: list[dict]) -> list[PersonalLine]:
        try:
            return writer.invoke(_prompt(survey, batch)).lines
        except Exception:  # a failed batch falls back to fallback_line rather than blocking the launch
            return []

    batches = [people[i:i + BATCH] for i in range(0, len(people), BATCH)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        lines = [line for result in pool.map(run, batches) for line in result]
    return {line.crustdata_person_id: line.model_dump() for line in lines}


def ungrounded(line: str, facts_used: list[str], target: dict, survey: Survey) -> str | None:
    """Why a personal line can't be sent, or None. Every number and proper noun must come from this person's facts
    or the study description, so the model can't invent a funding round, an award or a mutual contact."""
    line = (line or "").strip()
    facts = facts_of(target)
    if not line:
        return "empty"
    if len(line) > MAX_LINE or "\n" in line or "{" in line or "}" in line:
        return "too long or malformed"
    if not facts_used:
        return "cites no facts"
    if missing := [f for f in facts_used if f not in facts]:
        return f"cites facts not in the profile: {', '.join(missing)}"
    known = " ".join([str(v) for v in facts.values()] + [str(target.get("name") or ""), survey.title,
                                                          survey.research_question, survey.audience])
    numbers = set(re.findall(r"\d+", known.replace(",", ""))) | {str(survey.estimated_minutes)}
    if stray := [n for n in re.findall(r"\d[\d,]*", line) if n.replace(",", "") not in numbers]:
        return f"number not in the profile: {stray[0]}"
    known = known.lower()
    for m in re.finditer(r"[A-Z][A-Za-z0-9&+.\-]*(['’]s)?", line):
        word = re.sub(r"(['’]s|[.\-]+)$", "", m.group())
        starts_sentence = m.start() == 0 or line[:m.start()].rstrip().endswith((".", "!", "?", ":"))
        if starts_sentence and re.fullmatch(r"[A-Z][a-z]+", m.group()):  # an ordinary word opening a sentence
            continue
        if word.lower() not in known:
            return f"name not in the profile: {word}"
    return None


def _fill(text: str, values: dict) -> str:
    return re.sub(r"\{([a-z_]+)\}", lambda m: str(values.get(m.group(1), m.group())), text)


def render(survey: Survey, target: dict, link: str, written: dict | None) -> dict:
    """One finished email. `written` is the model's {personal_line, facts_used} for this person, if any."""
    template = survey.email
    name = (target.get("name") or "").strip()
    values = {"first_name": name.split()[0] if name else "there", "name": name or "there",
              "title": target.get("title") or "your role", "company": target.get("company") or "your company",
              "survey_minutes": survey.estimated_minutes, "link": link}
    reason = "no line written" if not written else ungrounded(written["personal_line"], written["facts_used"],
                                                              target, survey)
    personal = written["personal_line"].strip() if reason is None else _fill(template.fallback_line, values)
    body = _fill(template.body, {**values, PERSONAL_LINE: personal})
    return {"to": target.get("business_email"), "subject": _fill(template.subject, values),
            "body": f"{body.rstrip()}\n\n{FOOTER.format(link=link)}", "personal_line": personal, "personalized": reason is None,
            "facts_used": written["facts_used"] if reason is None else [], "fallback_reason": reason}


def build_emails(survey: Survey, targets: list[dict], links: list[str]) -> list[dict]:
    """Emails for targets[i] with links[i], in order."""
    written = write_lines(survey, targets)
    return [render(survey, t, link, written.get(str(t["crustdata_person_id"]))) for t, link in zip(targets, links)]
