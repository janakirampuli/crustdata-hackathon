"""Invite and follow-up emails. EMAIL_MODE=log (the only mode for now) writes every email to the outbox table,
which the survey workspace shows; real sending plugs in here later."""

import os

from skills.form_builder import store
from skills.form_builder.schema import Survey
from skills.form_builder.tools import base_url


def mode() -> str:
    return os.environ.get("EMAIL_MODE", "log")


def _first_name(target: dict) -> str:
    return (target.get("name") or "there").split(" ")[0]


def _why(target: dict) -> str:
    if target.get("why_qualified"):
        return target["why_qualified"].rstrip(".")
    role = " at ".join(x for x in (target.get("title"), target.get("company")) if x)
    return f"of your role as {role}" if role else "of your role"


def _subject(survey: Survey, target: dict) -> str:
    return f"{_first_name(target)}, a {survey.estimated_minutes}-minute survey: {survey.title}"


def invite(survey_id: str, survey: Survey, token: str, target: dict) -> dict:
    link, opt = f"{base_url()}/s/{token}", f"{base_url()}/s/{token}/opt-out"
    n = len(survey.questions)
    subject = _subject(survey, target)
    body = (
        f"Hi {_first_name(target)},\n\n"
        f"Would you be open to sharing your view in a short research survey? If not, ignore this email or opt out "
        f"below and we won't contact you again.\n\n"
        f"We're reaching out because {_why(target)}. {survey.intro}\n\n"
        f"It's {n} questions and takes about {survey.estimated_minutes} minutes:\n{link}\n\n"
        f"This link is personal to you and works once. Answers are used for this research only, never for sales.\n\n"
        f"Opt out: {opt}\n"
    )
    return _deliver(survey_id, token, "invite", target.get("business_email"), subject, body)


def followup(survey_id: str, survey: Survey, token: str, target: dict) -> dict:
    link, opt = f"{base_url()}/s/{token}", f"{base_url()}/s/{token}/opt-out"
    subject = "Re: " + _subject(survey, target)
    body = (
        f"Hi {_first_name(target)},\n\n"
        f"A quick nudge in case this got buried. Your view would really help, and it takes about "
        f"{survey.estimated_minutes} minutes:\n{link}\n\n"
        f"No worries if not. This is the last reminder.\n\nOpt out: {opt}\n"
    )
    return _deliver(survey_id, token, "followup", target.get("business_email"), subject, body)


def _deliver(survey_id: str, token: str, kind: str, to: str | None, subject: str, body: str) -> dict:
    store.add_outbox(survey_id, token, kind, to, subject, body, status="logged")
    return {"kind": kind, "to": to, "status": "logged"}
