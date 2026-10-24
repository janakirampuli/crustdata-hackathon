"""LangChain tools for the form-builder skill. Every tool returns a JSON-serializable dict; refusals come back as
{"error": ...} so the agent can read them and adjust.
"""

import os

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from . import personalize, store
from .schema import Survey


def base_url() -> str:
    return os.environ.get("FORMS_BASE_URL", "http://localhost:8000").rstrip("/")


def _review_url(survey_id: str) -> str:
    return f"{base_url()}/surveys/{survey_id}"


def _survey(survey) -> Survey:
    return Survey.model_validate(survey) if isinstance(survey, dict) else survey


class Target(BaseModel):
    crustdata_person_id: str | int
    name: str
    title: str | None = None
    company: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    business_email: str | None = None
    why_qualified: str | None = Field(None, description="One clause for the invite email, e.g. 'you lead platform "
                                      "engineering at a 120-person fintech'.")
    location: str | None = None
    # Profile facts from crustdata_search_people; the only material a personal line may use.
    headline: str | None = None
    seniority: str | None = None
    function: str | None = None
    company_headcount: int | None = None
    role_start_date: str | None = None


SAMPLES_HELP = ("Up to 3 real people from your Crustdata search for this audience, as target records with their "
                "profile facts. The review page shows the email template filled in for them.")


def _targets(targets) -> list[Target]:
    return [t if isinstance(t, Target) else Target.model_validate(t) for t in targets]


def _email_preview(survey_id: str, survey: Survey, samples: list[Target] | None) -> dict:
    """Fills the template for the sample people and stores it for the review page. None keeps the earlier samples."""
    if samples is None:
        samples = (store.get_survey(survey_id)["email_preview"] or {}).get("samples") or []
    samples = [t.model_dump() if isinstance(t, Target) else t for t in samples]
    emails = personalize.build_emails(survey, samples, [f"{base_url()}/s/<personal link>"] * len(samples))
    preview = {"samples": samples, "emails": emails}
    store.set_email_preview(survey_id, preview)
    return preview


NO_TEMPLATE = {"error": "email_template_required",
               "detail": "survey.email is missing: the invite email template is approved together with the survey."}


def _email_summary(preview: dict | None) -> dict:
    if not preview or not preview["samples"]:
        return {"email_preview": "none: pass sample_targets so the reviewer sees filled-in emails"}
    return {"email_preview": [{"to": s["name"], "personal_line_ok": e["personalized"],
                               "fallback_reason": e["fallback_reason"]}
                              for s, e in zip(preview["samples"], preview["emails"])]}


class CreateSurveyInput(BaseModel):
    survey: Survey
    sample_targets: list[Target] = Field(default_factory=list, max_length=3, description=SAMPLES_HELP)


@tool("form_create_survey", args_schema=CreateSurveyInput)
def create_survey(survey: Survey, sample_targets: list[Target] | None = None) -> dict:
    """Save a survey draft, with its invite email template, and get its review URL. The draft is NOT live: a
    human must approve it (survey and email template together) before any invite link works."""
    survey = _survey(survey)
    if survey.email is None:
        return NO_TEMPLATE
    survey_id = store.create_survey(survey)
    preview = _email_preview(survey_id, survey, _targets(sample_targets or []))
    return {"survey_id": survey_id, "status": "draft", "review_url": _review_url(survey_id),
            "questions": len(survey.questions), **_email_summary(preview)}


class ReviseSurveyInput(BaseModel):
    survey_id: str
    survey: Survey = Field(description="The full revised survey. It replaces the previous version.")
    sample_targets: list[Target] | None = Field(None, max_length=3,
                                                description=SAMPLES_HELP + " Omit to reuse the earlier ones.")


@tool("form_revise_survey", args_schema=ReviseSurveyInput)
def revise_survey(survey_id: str, survey: Survey, sample_targets: list[Target] | None = None) -> dict:
    """Replace a survey (questions and email template) with a revised version, e.g. after the reviewer
    requested changes. The survey goes back to draft and needs approval again. Refused once invite links exist."""
    survey = _survey(survey)
    if survey.email is None:
        return NO_TEMPLATE
    try:
        store.revise_survey(survey_id, survey)
    except KeyError:
        return {"error": "not_found", "survey_id": survey_id}
    except ValueError as e:
        return {"error": "locked", "detail": str(e)}
    preview = _email_preview(survey_id, survey, _targets(sample_targets) if sample_targets else None)
    return {"survey_id": survey_id, "status": "draft", "review_url": _review_url(survey_id),
            **_email_summary(preview)}


class SurveyIdInput(BaseModel):
    survey_id: str


@tool("form_get_survey", args_schema=SurveyIdInput)
def get_survey(survey_id: str) -> dict:
    """Approval state of a survey: status (draft | changes_requested | approved | closed), the reviewer's
    feedback if changes were requested, the current spec, and invite/response counts."""
    row = store.get_survey(survey_id)
    if row is None:
        return {"error": "not_found", "survey_id": survey_id}
    return {"survey_id": survey_id, "status": row["status"], "feedback": row["feedback"], "version": row["version"],
            "review_url": _review_url(survey_id), "stats": store.invite_stats(survey_id),
            "survey": row["spec"].model_dump()}


@tool("form_list_surveys")
def list_surveys() -> dict:
    """All surveys with status and invite/response counts, newest first."""
    return {"surveys": [{"survey_id": s["id"], "title": s["spec"].title, "status": s["status"],
                         "invites": s["invites"], "responses": s["responses"], "review_url": _review_url(s["id"])}
                        for s in store.list_surveys()]}


class CreateInviteLinksInput(BaseModel):
    survey_id: str
    targets: list[Target] = Field(min_length=1, max_length=500)


@tool("form_create_invite_links", args_schema=CreateInviteLinksInput)
def create_invite_links(survey_id: str, targets: list[Target]) -> dict:
    """Mint one unique survey link per verified target, without sending anything (campaign_launch sends the
    invites). Each link is bound to that Crustdata person and works once. Only works for an approved survey.
    Inviting the same person again returns their existing link."""
    row = store.get_survey(survey_id)
    if row is None:
        return {"error": "not_found", "survey_id": survey_id}
    if row["status"] not in ("approved", "fielding"):
        return {"error": "not_approved", "status": row["status"], "feedback": row["feedback"],
                "review_url": _review_url(survey_id)}
    targets = _targets(targets)
    invites = store.create_invites(survey_id, [t.model_dump() for t in targets])
    return {"survey_id": survey_id, "links": [
        {"crustdata_person_id": i["crustdata_person_id"], "name": t.name, "business_email": t.business_email,
         "url": f"{base_url()}/s/{i['token']}", "token": i["token"], "reused": i["reused"]}
        for t, i in zip(targets, invites)]}


@tool("form_get_responses", args_schema=SurveyIdInput)
def get_responses(survey_id: str) -> dict:
    """Submitted answers for a survey, each with the Crustdata target it was bound to and its verification
    state, plus invited/opened/responded counts."""
    if store.get_survey(survey_id) is None:
        return {"error": "not_found", "survey_id": survey_id}
    return {"survey_id": survey_id, "stats": store.invite_stats(survey_id), "responses": [
        {"token": r["token"], "crustdata_person_id": r["crustdata_person_id"], "answers": r["answers"],
         "submitted_from_email": r["submitted_from_email"], "verified": r["verified"], "reason": r["reason"],
         "submitted_at": r["submitted_at"],
         "target": {k: r["target"].get(k) for k in ("name", "title", "company", "company_domain")}}
        for r in store.list_responses(survey_id)]}


TOOLS = [create_survey, revise_survey, get_survey, list_surveys, create_invite_links, get_responses]
