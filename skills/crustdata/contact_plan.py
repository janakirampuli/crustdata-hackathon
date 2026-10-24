"""Typed contact-search plan -> Crustdata /person/search filter DSL.

Ported from Kris@Work's CrustDataSearchService.buildPeopleFilters. Friendly fields compile to the exact
operator/field pairs Crustdata accepts; raw ``filters`` are validated against the person filter catalog.
Invalid raw filters are dropped and reported back as warnings so the agent can correct them.
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import countries

CATALOG = json.loads((Path(__file__).parent / "reference" / "person_filter_catalog.json").read_text())
FIELDS: dict[str, dict] = CATALOG["fields"]
OPERATOR_SETS: dict[str, list[str]] = CATALOG["operatorSets"]

MAX_TITLE_PHRASES = 300
RECENTLY_CHANGED_JOBS = "recently_changed_jobs"
VALUELESS_OPERATORS = {"is_null", "is_not_null"}
NEGATIVE_OPERATORS = {"!=", "not_in", "(!)", "geo_exclude"}
POSITIVE_TEXT_OPERATORS = {"(.)", "[.]"}
LIST_OPERATORS = {"in", "not_in", "has_all"}
GEO_OPERATORS = {"geo_distance", "geo_exclude"}
GEO_FIELD = "professional_network.location.raw"
SORTABLE_FIELDS = {name for name, spec in FIELDS.items() if spec.get("sortable")} | {RECENTLY_CHANGED_JOBS}
SORT_ALIASES = {"updated_at": "metadata.updated_at"}
DEFAULT_SORTS = [
    {"field": RECENTLY_CHANGED_JOBS, "order": "desc"},
    {"field": "professional_network.connections", "order": "desc"},
]
DEFAULT_PERSON_FIELDS = ["basic_profile", "experience", "social_handles", "contact"]

OPEN_TO_CODES = {"CAREER_INTEREST", "HIRING_MANAGER", "VOLUNTEERING"}
OPEN_TO_ALIASES = {
    **dict.fromkeys(
        ["hiring", "actively hiring", "hiring_manager", "hiring manager", "open to hiring", "open-to-hiring"],
        "HIRING_MANAGER",
    ),
    **dict.fromkeys(
        ["career interest", "career_interest", "open to work", "opentowork", "open-to-work",
         "open to new opportunities"],
        "CAREER_INTEREST",
    ),
    **dict.fromkeys(["volunteering", "volunteer", "open to volunteer work"], "VOLUNTEERING"),
}

Seniority = Literal[
    "CXO", "Vice President", "Director", "Senior", "Entry Level", "Entry Level Manager",
    "Experienced Manager", "In Training", "Owner / Partner", "Strategic",
]
FunctionCategory = Literal[
    "Sales", "Engineering", "Marketing", "Finance", "Operations", "Consulting", "Research",
    "Customer Success and Support", "Arts and Design", "Human Resources", "Legal", "Product Management",
]


class Sort(BaseModel):
    field: str
    type: Literal["asc", "desc"] = "desc"


class ContactSearchPlan(BaseModel):
    """One Crustdata person search. Emit only constraints the brief states or clearly implies."""

    currentJobTitles: list[str] | None = Field(
        None, description="PRIMARY lever. OR-group of all-words contains (.) on the current title. Keep concise: "
        "'VP Sales' matches 'Co-Founder and VP of Sales'.")
    seniorityLevels: list[Seniority] | None = Field(None, description="Exact current seniority_level.")
    functionCategories: list[FunctionCategory] | None = Field(None, description="Exact current function_category.")
    companyIndustries: list[str] | None = Field(
        None, description="Broad employer-industry tokens matched as contains (.) on current.company_industries. "
        "For exact taxonomy labels use a raw filter with 'in'.")
    minHeadcount: int | None = Field(None, description="Inclusive lower bound on current employer headcount.")
    maxHeadcount: int | None = Field(None, description="Inclusive upper bound on current employer headcount.")
    companyNames: list[str] | None = Field(
        None, description="EXACT, case-sensitive canonical employer name. Resolve via crustdata_identify_company "
        "unless unambiguous. Never AND with companyDomains for the same company.")
    companyIds: list[int] | None = Field(None, description="Exact current employer crustdata company ids.")
    companyDomains: list[str] | None = Field(
        None, description="Exact employer PRIMARY domain only; alias domains match zero. Resolve via "
        "crustdata_identify_company. Never guess sibling TLDs.")
    companyLinkedInUrls: list[str] | None = Field(None, description="Exact employer LinkedIn company URLs.")
    companyHeadquartersCountries: list[str] | None = Field(
        None, description="Current employer HQ country (ISO-3 or full name; both spellings are sent).")
    companyHeadquartersStates: list[str] | None = Field(
        None, description="Employer HQ state/region full names, approximate (.) match on company_hq_location.")
    personCountries: list[str] | None = Field(
        None, description="Person's OWN country, full name ('United States', not 'USA'). Results are also "
        "post-filtered to these countries.")
    personStates: list[str] | None = Field(None, description="Person's own state/region, exact full name.")
    personCities: list[str] | None = Field(None, description="Person's own city, exact.")
    openToCards: list[str] | None = Field(None, description="CAREER_INTEREST | HIRING_MANAGER | VOLUNTEERING.")
    activelyHiring: bool | None = Field(
        None, description="Person has the HIRING_MANAGER profile signal. Not 'their company has open jobs'.")
    recentlyChangedJobs: bool | None = Field(
        None, description="Past role ended within ~90 days. Role-ending signal, not proof a new role started. "
        "Only applied alongside another narrowing filter.")
    currentRoleStartDateFrom: str | None = Field(None, description="YYYY-MM-DD inclusive; recent-hire intent.")
    currentRoleStartDateTo: str | None = Field(None, description="YYYY-MM-DD inclusive.")
    minYearsAtCurrentCompany: float | None = None
    maxYearsAtCurrentCompany: float | None = None
    minYearsOfExperience: float | None = None
    maxYearsOfExperience: float | None = None
    minConnections: int | None = None
    minFollowers: int | None = None
    filters: list[dict[str, Any]] | None = Field(
        None, description="Raw catalog conditions {field,type,value} or groups {op:and|or|all_of,conditions}, "
        "ANDed with everything above. Use for skills, past employers, education, exclusions, geo radius.")
    sorts: list[Sort] | None = Field(None, description="[{field,type}] on sortable catalog fields. Set explicitly.")


def _condition(field: str, op: str, value: Any = None, *, valueless: bool = False) -> dict:
    return {"field": field, "type": op} if valueless else {"field": field, "type": op, "value": value}


def _group(op: str, conditions: list[dict]) -> dict:
    return {"op": op, "conditions": conditions}


def _clean_strings(values: list | None) -> list:
    return [v.strip() if isinstance(v, str) else v for v in (values or []) if v is not None and str(v).strip()]


def _add_in(conditions: list, field: str, values: list | None) -> bool:
    clean = _clean_strings(values)
    if not clean:
        return False
    conditions.append(_condition(field, "in", clean))
    return True


def _text_group(field: str, op: str, values: list | None, cap: int) -> dict | None:
    phrases = [v for v in _clean_strings(values) if isinstance(v, str)][:cap]
    if not phrases:
        return None
    ors = [_condition(field, op, p) for p in phrases]
    return ors[0] if len(ors) == 1 else _group("or", ors)


def _add_contains(conditions: list, field: str, values: list | None, cap: int = 10_000) -> bool:
    group = _text_group(field, "(.)", values, cap)
    if group is None:
        return False
    conditions.append(group)
    return True


def _add_bound(conditions: list, field: str, op: str, value) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return False
    conditions.append(_condition(field, op, value.strip() if isinstance(value, str) else value))
    return True


def normalize_open_to(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    trimmed = str(value).strip()
    code = trimmed.upper().replace("-", "_").replace(" ", "_")
    if code in OPEN_TO_CODES:
        return code
    return OPEN_TO_ALIASES.get(trimmed.lower())


def _add_open_to(conditions: list, plan: ContactSearchPlan, warnings: list[str]) -> bool:
    codes: list[str] = []
    for raw in plan.openToCards or []:
        code = normalize_open_to(raw)
        if code is None:
            warnings.append(f"openToCards value '{raw}' is not a Crustdata code; skipped")
        elif code not in codes:
            codes.append(code)
    if plan.activelyHiring and "HIRING_MANAGER" not in codes:
        codes.append("HIRING_MANAGER")
    if not codes:
        return False
    conditions.append(_condition("professional_network.open_to_cards", "in", codes))
    return True


def _normalize_value(field: str, op: str, value: Any) -> Any:
    if op in GEO_OPERATORS:
        if not isinstance(value, dict) or not isinstance(value.get("distance"), (int, float)):
            return None
        if not value.get("location") and not value.get("lat_lng"):
            return None
        return {k: v for k, v in value.items() if k in {"location", "lat_lng", "distance", "unit"}}
    if field == "professional_network.open_to_cards":
        if isinstance(value, list):
            return [c for c in dict.fromkeys(normalize_open_to(v) for v in value) if c]
        return normalize_open_to(value)
    if countries.is_country_field(field):
        value = countries.normalize_for_field(field, value)
    if op in LIST_OPERATORS:
        items = value if isinstance(value, list) else [value]
        items = [v for v in items if v is not None and not (isinstance(v, str) and not v.strip())]
        return items or None
    return value


def _expand_text_list(condition: dict) -> list[dict]:
    """A list value on (.)/[.] becomes an OR of single-phrase conditions; on (!) each phrase is ANDed."""
    value, op = condition.get("value"), condition["type"]
    if not isinstance(value, list) or op not in POSITIVE_TEXT_OPERATORS | {"(!)"}:
        return [condition]
    expanded = [_condition(condition["field"], op, str(v).strip()) for v in value if v is not None and str(v).strip()]
    if len(expanded) <= 1 or op == "(!)":
        return expanded
    return [_group("or", expanded)]


def normalize_raw_filter(node: Any, warnings: list[str]) -> list[dict]:
    """Validates one raw filter node against the catalog. Returns [] (with a warning) when it is unusable."""
    if not isinstance(node, dict):
        warnings.append(f"filter {node!r} is not an object; skipped")
        return []
    if "op" in node or "conditions" in node:
        if any(k in node for k in ("field", "type", "value")):
            warnings.append(f"filter {node} mixes a group with a leaf; skipped")
            return []
        op = str(node.get("op") or "").strip()
        children = node.get("conditions") or []
        if op not in {"and", "or", "all_of"} or not children:
            warnings.append(f"filter group op '{op}' is invalid or has no conditions; skipped")
            return []
        normalized = []
        for child in children:
            result = normalize_raw_filter(child, warnings)
            if not result:
                warnings.append(f"group {op} dropped because a child was invalid")
                return []
            normalized.append(result[0] if len(result) == 1 else _group("and", result))
        return [_group(op, normalized)]

    field = str(node.get("field") or "").strip()
    op = str(node.get("type") or "").strip()
    if not field or not op:
        warnings.append(f"filter {node} needs field and type; skipped")
        return []
    spec = FIELDS.get(field)
    if spec is None:
        warnings.append(f"filter field '{field}' is not in the person filter catalog; skipped")
        return []
    allowed = set(OPERATOR_SETS.get(spec.get("operatorSet"), []))
    if spec.get("geoCapable"):
        allowed |= GEO_OPERATORS
    if op not in allowed:
        warnings.append(f"operator '{op}' is not allowed on '{field}' (allowed: {sorted(allowed)}); skipped")
        return []
    if op in GEO_OPERATORS and field != GEO_FIELD:
        warnings.append(f"geo operator only works on {GEO_FIELD}; skipped '{field}'")
        return []
    if op in VALUELESS_OPERATORS:
        return [_condition(field, op, None)]
    value = _normalize_value(field, op, node.get("value"))
    if value is None or value == []:
        warnings.append(f"filter on '{field}' with '{op}' has no usable value; skipped")
        return []
    return _expand_text_list(_condition(field, op, value))


def _is_narrowing(condition: dict) -> bool:
    if isinstance(condition.get("conditions"), list):
        return any(_is_narrowing(c) for c in condition["conditions"] if isinstance(c, dict))
    return condition.get("field") != RECENTLY_CHANGED_JOBS and condition.get("type") not in NEGATIVE_OPERATORS


def _expand_employer_country_aliases(node: dict) -> None:
    """Employer HQ country has been seen matching 'United States' while 'USA' fails: send both spellings."""
    if isinstance(node.get("conditions"), list):
        for child in node["conditions"]:
            _expand_employer_country_aliases(child)
        return
    if node.get("field") != "experience.employment_details.current.company_headquarters_country":
        return
    op = node.get("type")
    if op not in {"in", "not_in", "=", "!="} or node.get("value") is None:
        return
    raw = node["value"] if isinstance(node["value"], list) else [node["value"]]
    expanded: list[str] = []
    for country in raw:
        if country is None or not str(country).strip():
            continue
        iso3 = countries.to_iso3(str(country))
        for spelling in (iso3, countries.to_full(iso3)):
            if spelling and spelling not in expanded:
                expanded.append(spelling)
    node["type"] = "not_in" if op == "!=" else "in" if op == "=" else op
    node["value"] = expanded


def compile_filters(plan: ContactSearchPlan) -> tuple[dict | None, list[str]]:
    """Returns (filters, warnings). filters is None when nothing narrows the search: never run unbounded."""
    warnings: list[str] = []
    conditions: list[dict] = []
    cur = "experience.employment_details.current."

    titles = _text_group(cur + "title", "(.)", plan.currentJobTitles, MAX_TITLE_PHRASES)
    if plan.currentJobTitles and len(_clean_strings(plan.currentJobTitles)) > MAX_TITLE_PHRASES:
        warnings.append(f"only the first {MAX_TITLE_PHRASES} title phrases were used")
    narrowing = titles is not None
    if titles is not None:
        conditions.append(titles)
    narrowing |= _add_in(conditions, cur + "seniority_level", plan.seniorityLevels)
    narrowing |= _add_in(conditions, cur + "function_category", plan.functionCategories)
    narrowing |= _add_contains(conditions, cur + "company_industries", plan.companyIndustries)
    narrowing |= _add_bound(conditions, cur + "company_headcount_latest", "=>", plan.minHeadcount)
    narrowing |= _add_bound(conditions, cur + "company_headcount_latest", "=<", plan.maxHeadcount)
    narrowing |= _add_in(conditions, cur + "company_name", plan.companyNames)
    narrowing |= _add_in(conditions, cur + "company_id", plan.companyIds)
    narrowing |= _add_in(conditions, cur + "company_website_domain", plan.companyDomains)
    narrowing |= _add_in(conditions, cur + "company_professional_network_profile_url", plan.companyLinkedInUrls)
    narrowing |= _add_in(conditions, cur + "company_headquarters_country",
                         [countries.to_iso3(c) for c in _clean_strings(plan.companyHeadquartersCountries)])
    narrowing |= _add_contains(conditions, cur + "company_hq_location", plan.companyHeadquartersStates)
    narrowing |= _add_in(conditions, "basic_profile.location.country",
                         [countries.to_full(c) for c in _clean_strings(plan.personCountries)])
    narrowing |= _add_in(conditions, "basic_profile.location.state", plan.personStates)
    narrowing |= _add_in(conditions, "basic_profile.location.city", plan.personCities)
    narrowing |= _add_open_to(conditions, plan, warnings)
    narrowing |= _add_bound(conditions, cur + "start_date", "=>", plan.currentRoleStartDateFrom)
    narrowing |= _add_bound(conditions, cur + "start_date", "=<", plan.currentRoleStartDateTo)
    narrowing |= _add_bound(conditions, cur + "years_at_company_raw", "=>", plan.minYearsAtCurrentCompany)
    narrowing |= _add_bound(conditions, cur + "years_at_company_raw", "=<", plan.maxYearsAtCurrentCompany)
    narrowing |= _add_bound(conditions, "years_of_experience_raw", "=>", plan.minYearsOfExperience)
    narrowing |= _add_bound(conditions, "years_of_experience_raw", "=<", plan.maxYearsOfExperience)
    narrowing |= _add_bound(conditions, "professional_network.connections", "=>", plan.minConnections)
    narrowing |= _add_bound(conditions, "professional_network.followers", "=>", plan.minFollowers)
    for raw in plan.filters or []:
        for condition in normalize_raw_filter(raw, warnings):
            conditions.append(condition)
            narrowing |= _is_narrowing(condition)

    if plan.recentlyChangedJobs:
        if narrowing:
            conditions.append(_condition(RECENTLY_CHANGED_JOBS, "=", True))
        else:
            warnings.append("recentlyChangedJobs alone does not narrow a search; add a real filter")
    for condition in conditions:
        _expand_employer_country_aliases(condition)

    if not narrowing:
        warnings.append("no positive narrowing filter: search not run (exclusions alone are unbounded)")
        return None, warnings
    return (conditions[0] if len(conditions) == 1 else _group("and", conditions)), warnings


def compile_sorts(plan: ContactSearchPlan, warnings: list[str]) -> list[dict]:
    sorts = []
    for sort in plan.sorts or []:
        field = SORT_ALIASES.get(sort.field.strip(), sort.field.strip())
        if field not in SORTABLE_FIELDS:
            warnings.append(f"sort field '{field}' is not sortable; skipped")
            continue
        sorts.append({"field": field, "order": sort.type})
    return sorts or DEFAULT_SORTS


def person_country(row: dict) -> str | None:
    profile = row.get("basic_profile") if isinstance(row, dict) else None
    if not isinstance(profile, dict):
        return None
    location = profile.get("location")
    if isinstance(location, dict) and str(location.get("country") or "").strip():
        return str(location["country"]).strip()
    value = profile.get("location_country")
    return str(value).strip() if value and str(value).strip() else None


def enforce_person_countries(rows: list[dict], requested: list[str] | None) -> tuple[list[dict], int]:
    """Crustdata has returned rows outside basic_profile.location.country; a country ask is a hard filter."""
    allowed = {countries.to_full(c).lower() for c in _clean_strings(requested)}
    if not allowed:
        return rows, 0
    kept = [r for r in rows if (c := person_country(r)) and countries.to_full(c).lower() in allowed]
    return kept, len(rows) - len(kept)
