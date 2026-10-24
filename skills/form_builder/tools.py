"""LangChain tools for the form-builder skill. Every tool returns a JSON-serializable dict; refusals come back as
{"error": ...} so the agent can read them and adjust.
"""

import os

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from . import store
from .schema import Survey


def base_url() -> str:
    return os.environ.get("FORMS_BASE_URL", "http://localhost:8000").rstrip("/")


def _review_url(survey_id: str) -> str:
    return f"{base_url()}/surveys/{survey_id}"


def _survey(survey) -> Survey:
    return Survey.model_validate(survey) if isinstance(survey, dict) else survey


class CreateSurveyInput(BaseModel):
    survey: Survey


@tool("form_create_survey", args_schema=CreateSurveyInput)
def create_survey(survey: Survey) -> dict:
    """Save a survey draft and get its review URL. The draft is NOT live: a human must open review_url and
    approve it before any invite link works. Share review_url with the user and wait for approval."""
    survey = _survey(survey)
    survey_id = store.create_survey(survey)
    return {"survey_id": survey_id, "status": "draft", "review_url": _review_url(survey_id),
            "questions": len(survey.questions)}


class ReviseSurveyInput(BaseModel):
    survey_id: str
    survey: Survey = Field(description="The full revised survey. It replaces the previous version.")


@tool("form_revise_survey", args_schema=ReviseSurveyInput)
def revise_survey(survey_id: str, survey: Survey) -> dict:
    """Replace a survey with a revised version (e.g. after the reviewer requested changes). The survey goes
    back to draft and needs approval again. Refused once invite links exist."""
    try:
        store.revise_survey(survey_id, _survey(survey))
    except KeyError:
        return {"error": "not_found", "survey_id": survey_id}
    except ValueError as e:
        return {"error": "locked", "detail": str(e)}
    return {"survey_id": survey_id, "status": "draft", "review_url": _review_url(survey_id)}


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
    seniority: str | None = None
    function: str | None = None
    company_headcount: int | None = None
    location: str | None = None


class CreateInviteLinksInput(BaseModel):
    survey_id: str
    targets: list[Target] = Field(min_length=1, max_length=500)


@tool("form_create_invite_links", args_schema=CreateInviteLinksInput)
def create_invite_links(survey_id: str, targets: list[Target]) -> dict:
    """Mint one unique survey link per verified target. Each link is bound to that Crustdata person and works
    once. Only works for an approved survey. Inviting the same person again returns their existing link."""
    row = store.get_survey(survey_id)
    if row is None:
        return {"error": "not_found", "survey_id": survey_id}
    if row["status"] not in ("approved", "fielding"):
        return {"error": "not_approved", "status": row["status"], "feedback": row["feedback"],
                "review_url": _review_url(survey_id)}
    targets = [t if isinstance(t, Target) else Target.model_validate(t) for t in targets]
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
