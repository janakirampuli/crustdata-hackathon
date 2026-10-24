"""LangChain tools for running a survey campaign: configure, launch, monitor, nudge, close, report."""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from skills.form_builder import store
from skills.form_builder.schema import Audience, CampaignConfig
from skills.form_builder.tools import Target, base_url

from . import insights, service


def _workspace(survey_id: str, tab: str = "progress") -> str:
    return f"{base_url()}/surveys/{survey_id}?tab={tab}"


class ConfigureInput(BaseModel):
    survey_id: str
    max_invites: int | None = Field(None, ge=1, le=500)
    target_responses: int | None = Field(None, ge=1, le=500)
    deadline_minutes: int | None = Field(None, ge=5)
    followup_after_minutes: int | None = Field(None, ge=1)
    max_followups: int | None = Field(None, ge=0, le=3)


@tool("campaign_configure", args_schema=ConfigureInput)
def configure(survey_id: str, **changes) -> dict:
    """Set fieldwork settings for a survey: max_invites (send cap), target_responses (auto-close when reached),
    deadline_minutes (auto-close after launch), followup_after_minutes and max_followups. Only pass what changes.
    The user can also edit these in the survey workspace."""
    row = store.get_survey(survey_id)
    if row is None:
        return {"error": "not_found", "survey_id": survey_id}
    if row["status"] == "closed":
        return {"error": "closed"}
    config = CampaignConfig.model_validate({**row["config"].model_dump(), **{k: v for k, v in changes.items() if v is not None}})
    store.set_config(survey_id, config)
    store.log_event(survey_id, "config", detail=config.model_dump())
    return {"survey_id": survey_id, "config": config.model_dump(), "workspace_url": _workspace(survey_id, "progress")}


class LaunchInput(BaseModel):
    survey_id: str
    targets: list[Target] = Field(min_length=1, max_length=500, description="Verified targets with business_email. "
                                  "Copy seniority, function, company_headcount and location from the search results "
                                  "so the analysis can split by them.")
    audience: Audience = Field(description="The persona and the exact Crustdata plan, effective_filters and "
                               "total_count behind these targets, plus the confirmed brief.")


@tool("campaign_launch", args_schema=LaunchInput)
def launch(survey_id: str, targets: list[Target], audience: Audience) -> dict:
    """Start (or add people to) fieldwork for an APPROVED survey: creates one personal link per target and emails
    each an invite. Respects the survey's max_invites. Targets without a business email are skipped. Calling it
    again later adds a new batch to the same campaign."""
    targets = [t if isinstance(t, Target) else Target.model_validate(t) for t in targets]
    audience = audience if isinstance(audience, Audience) else Audience.model_validate(audience)
    result = service.launch(survey_id, [t.model_dump() for t in targets], audience)
    if "error" not in result:
        result["workspace_url"] = _workspace(survey_id, "participants")
    return result


class SurveyIdInput(BaseModel):
    survey_id: str


@tool("campaign_status", args_schema=SurveyIdInput)
def status(survey_id: str) -> dict:
    """Fieldwork progress: invited / opened / responded / opted out, pace against target and deadline, and a
    recommendation (on track, invite more, or widen the audience)."""
    if store.get_survey(survey_id) is None:
        return {"error": "not_found", "survey_id": survey_id}
    return {"survey_id": survey_id, **service.status(survey_id), "workspace_url": _workspace(survey_id)}


@tool("campaign_nudge", args_schema=SurveyIdInput)
def nudge(survey_id: str) -> dict:
    """Send the follow-up email now to everyone who hasn't answered (within max_followups)."""
    sent = service.send_followups(survey_id, force=True)
    return {"survey_id": survey_id, "followups_sent": len(sent), "to": sent}


class CloseInput(BaseModel):
    survey_id: str
    reason: str = Field("closed by agent", description="Why fieldwork ended.")


@tool("campaign_close", args_schema=CloseInput)
def close(survey_id: str, reason: str = "closed by agent") -> dict:
    """End fieldwork: links stop accepting answers. Do this before generating the final report."""
    if store.get_survey(survey_id) is None:
        return {"error": "not_found", "survey_id": survey_id}
    closed = service.close(survey_id, reason)
    return {"survey_id": survey_id, "closed": closed, **service.status(survey_id)}


@tool("campaign_report", args_schema=SurveyIdInput)
def report(survey_id: str) -> dict:
    """Analyse the responses (funnel, per-question stats, segment splits) and write the findings report. Returns
    the report markdown and the analytics page URL."""
    if store.get_survey(survey_id) is None:
        return {"error": "not_found", "survey_id": survey_id}
    result = insights.generate(survey_id)
    if "error" not in result:
        result["analytics_url"] = _workspace(survey_id, "analytics")
    return result


TOOLS = [configure, launch, status, nudge, close, report]
