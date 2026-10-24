"""LangChain tools for the Crustdata skill.

Every tool returns a JSON-serializable dict. Provider errors come back as {"error": ...} rather than
raising, so the agent can read Crustdata's 400 message and fix its query.
"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .client import CrustdataError, get_client
from .contact_plan import (
    DEFAULT_PERSON_FIELDS,
    ContactSearchPlan,
    compile_filters,
    compile_sorts,
    enforce_person_countries,
)

DEFAULT_ENRICH_FIELDS = ["basic_profile", "experience", "social_handles"]
DEFAULT_COMPANY_FIELDS = ["crustdata_company_id", "basic_info", "headcount", "locations", "social_profiles"]
DEFAULT_JOB_FIELDS = ["crustdata_job_id", "job_details", "company", "location", "content", "metadata"]
MAX_LIMIT = 1000


def _call(fn, *args) -> tuple[Any, dict | None]:
    try:
        return fn(*args), None
    except CrustdataError as e:
        return None, {"error": f"HTTP {e.status}", "detail": e.body}
    except Exception as e:  # network/timeout: surface to the agent instead of killing the run
        return None, {"error": type(e).__name__, "detail": str(e)}


def _first(items):
    return items[0] if isinstance(items, list) and items else {}


def compact_person(row: dict) -> dict:
    """Interface-sized view of a person row: what targeting and outreach need, nothing else."""
    profile = row.get("basic_profile") or {}
    location = profile.get("location") or {}
    current = _first(((row.get("experience") or {}).get("employment_details") or {}).get("current"))
    social = row.get("social_handles") or {}
    linkedin = (social.get("professional_network_identifier") or {}).get("profile_url")
    contact = row.get("contact") or {}
    return {
        "crustdata_person_id": row.get("crustdata_person_id"),
        "name": profile.get("name"),
        "headline": profile.get("headline"),
        "title": current.get("title") or profile.get("current_title"),
        "company": current.get("name") or current.get("company_name"),
        "company_website": current.get("company_website") or current.get("company_website_domain"),
        "crustdata_company_id": current.get("crustdata_company_id") or current.get("company_id"),
        "seniority": current.get("seniority_level"),
        "function": current.get("function_category"),
        "company_headcount_range": current.get("company_headcount_range"),
        "role_start_date": current.get("start_date"),
        "location": ", ".join(str(v) for v in (location.get("city"), location.get("state"), location.get("country")) if v)
        if isinstance(location, dict) else location,
        "linkedin_url": linkedin,
        "has_business_email": contact.get("has_business_email"),
        "business_emails": contact.get("business_emails") or contact.get("business_email"),
    }


class SearchPeopleInput(BaseModel):
    plan: ContactSearchPlan
    limit: int = Field(25, ge=1, le=MAX_LIMIT, description="Profiles in this page. ~0.03 credits each.")
    cursor: str | None = Field(None, description="next_cursor from the previous page of the SAME plan.")
    fields: list[str] | None = Field(
        None, description="Whole sections only (basic_profile, experience, social_handles, contact, education, "
        "skills). Leaf paths like basic_profile.first_name return HTTP 400.")
    raw: bool = Field(False, description="Return full provider rows instead of the compact view.")


@tool("crustdata_search_people", args_schema=SearchPeopleInput)
def search_people(plan: ContactSearchPlan, limit: int = 25, cursor: str | None = None,
                  fields: list[str] | None = None, raw: bool = False) -> dict:
    """Find people via Crustdata /person/search from a typed plan. The plan compiles to Crustdata's filter
    DSL (exact vocabularies, country spellings, contains-groups). Returns profiles, total_count, next_cursor,
    the effective filters sent, and warnings for any plan part that was dropped. Page with cursor."""
    if isinstance(plan, dict):
        plan = ContactSearchPlan.model_validate(plan)
    filters, warnings = compile_filters(plan)
    if filters is None:
        return {"error": "not_run", "warnings": warnings}
    sorts = compile_sorts(plan, warnings)
    body = {"filters": filters, "limit": limit, "fields": fields or DEFAULT_PERSON_FIELDS, "sorts": sorts}
    if cursor:
        body["cursor"] = cursor.strip()
    data, error = _call(get_client().search_people, body)
    if error:
        return {**error, "effective_filters": filters, "sorts": sorts, "warnings": warnings}
    rows, dropped = enforce_person_countries(data.get("profiles") or [], plan.personCountries)
    rows = rows[:limit]
    return {
        "total_count": data.get("total_count"),
        "total_count_relation": data.get("total_count_relation"),
        "returned": len(rows),
        "dropped_outside_person_countries": dropped,
        "next_cursor": data.get("next_cursor"),
        "effective_filters": filters,
        "sorts": sorts,
        "warnings": warnings,
        "profiles": rows if raw else [compact_person(r) for r in rows],
    }


class EnrichPersonInput(BaseModel):
    professionalNetworkProfileUrls: list[str] | None = Field(None, description="LinkedIn profile URLs.")
    businessEmails: list[str] | None = Field(None, description="Business emails to resolve to a person.")
    fields: list[str] | None = Field(
        None, description="Sections to return. Defaults to basic_profile, experience, social_handles. "
        "Without sections only name + id come back.")


@tool("crustdata_enrich_person", args_schema=EnrichPersonInput)
def enrich_person(professionalNetworkProfileUrls: list[str] | None = None, businessEmails: list[str] | None = None,
                  fields: list[str] | None = None) -> Any:
    """Resolve and enrich people by exact identifier (LinkedIn URL or business email) via /person/enrich.
    Use to verify a specific person's current employer and title. Billed per match."""
    if not professionalNetworkProfileUrls and not businessEmails:
        return {"error": "pass professionalNetworkProfileUrls or businessEmails"}
    body: dict = {"fields": fields or DEFAULT_ENRICH_FIELDS}
    if professionalNetworkProfileUrls:
        body["professional_network_profile_urls"] = professionalNetworkProfileUrls
    if businessEmails:
        body["business_emails"] = businessEmails
    data, error = _call(get_client().enrich_person, body)
    return error or data


class IdentifyCompanyInput(BaseModel):
    domains: list[str] | None = Field(None, description="Company website domains. Most reliable.")
    names: list[str] | None = Field(None, description="Company names; ambiguous names match with low confidence.")
    professionalNetworkProfileUrls: list[str] | None = Field(None, description="LinkedIn company page URLs.")
    crustdataCompanyIds: list[int] | None = Field(None, description="Known Crustdata company ids.")


@tool("crustdata_identify_company", args_schema=IdentifyCompanyInput)
def identify_company(domains: list[str] | None = None, names: list[str] | None = None,
                     professionalNetworkProfileUrls: list[str] | None = None,
                     crustdataCompanyIds: list[int] | None = None) -> Any:
    """FREE. Resolve companies to their canonical Crustdata identity (company_name, primary_domain,
    crustdata_company_id). Call before filtering people by employer name/domain. Max 25 identifiers.
    Returns only a bucketed employee_count_range, not exact headcount."""
    body = {k: v for k, v in {
        "domains": domains,
        "names": names,
        "professional_network_profile_urls": professionalNetworkProfileUrls,
        "crustdata_company_ids": crustdataCompanyIds,
    }.items() if v}
    if not body:
        return {"error": "pass at least one identifier list"}
    if sum(len(v) for v in body.values()) > 25:
        return {"error": "max 25 identifiers per call"}
    data, error = _call(get_client().identify_company, body)
    return error or data


class SearchCompaniesInput(BaseModel):
    filters: dict[str, Any] = Field(
        description="Company filter DSL: {field,type,value} or {op:and|or,conditions:[...]}. Company-side countries "
        "are ISO-3 ('USA'). Operators: = != < =< > => in not_in (.) [.] (no fuzzy negation).")
    sorts: list[dict[str, str]] | None = Field(None, description="[{field, order}], e.g. headcount.total desc.")
    fields: list[str] | None = Field(None, description="Whole sections; defaults to identity/basic_info/headcount/"
                                     "locations/social_profiles.")
    limit: int = Field(25, ge=1, le=MAX_LIMIT)
    cursor: str | None = None


@tool("crustdata_search_companies", args_schema=SearchCompaniesInput)
def search_companies(filters: dict[str, Any], sorts: list[dict[str, str]] | None = None,
                     fields: list[str] | None = None, limit: int = 25, cursor: str | None = None) -> Any:
    """Search companies by firmographics via /company/search (industry, headcount, HQ, revenue, funding,
    technologies). Use when people need an employer constraint the person index lacks (revenue, funding,
    tech stack): find companies first, then search people by crustdata company id."""
    body: dict = {"filters": filters, "fields": fields or DEFAULT_COMPANY_FIELDS, "limit": limit}
    if sorts:
        body["sorts"] = sorts
    if cursor:
        body["cursor"] = cursor
    data, error = _call(get_client().search_companies, body)
    return error or data


class SearchJobsInput(BaseModel):
    filters: dict[str, Any] = Field(description="Job filter DSL, e.g. {field:'job_details.title',type:'(.)',"
                                    "value:'Data Engineer'}. workplace_type values: Remote, On-site, Hybrid.")
    sorts: list[dict[str, str]] | None = Field(None, description="[{field, order}], default metadata.date_added desc.")
    fields: list[str] | None = None
    aggregations: list[dict[str, Any]] | None = Field(
        None, description="e.g. [{type:'group_by',field:'company.basic_info.company_id',agg:'count',size:100}]. "
        "Use limit 0 for aggregation-only queries.")
    limit: int = Field(25, ge=0, le=MAX_LIMIT)
    cursor: str | None = None


@tool("crustdata_search_jobs", args_schema=SearchJobsInput)
def search_jobs(filters: dict[str, Any], sorts: list[dict[str, str]] | None = None, fields: list[str] | None = None,
                aggregations: list[dict[str, Any]] | None = None, limit: int = 25, cursor: str | None = None) -> Any:
    """Search job postings via /job/search. Proves a COMPANY is hiring for a role; it says nothing about
    whether a given person is a hiring manager."""
    body: dict = {
        "filters": filters,
        "fields": fields or DEFAULT_JOB_FIELDS,
        "sorts": sorts or [{"field": "metadata.date_added", "order": "desc"}],
        "limit": limit,
    }
    if aggregations:
        body["aggregations"] = aggregations
    if cursor:
        body["cursor"] = cursor
    data, error = _call(get_client().search_jobs, body)
    return error or data


@tool("crustdata_get_credits")
def get_credits() -> Any:
    """Remaining Crustdata credit balance. Zero-credit call."""
    data, error = _call(get_client().get_credits)
    return error or data


TOOLS = [search_people, enrich_person, identify_company, search_companies, search_jobs, get_credits]
