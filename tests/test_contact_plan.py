from skills.crustdata import countries
from skills.crustdata.contact_plan import (
    DEFAULT_SORTS,
    ContactSearchPlan,
    compile_filters,
    compile_sorts,
    enforce_person_countries,
)

CUR = "experience.employment_details.current."


def plan(**kwargs) -> ContactSearchPlan:
    return ContactSearchPlan.model_validate(kwargs)


def test_titles_become_or_contains_group_anded_with_person_country():
    filters, warnings = compile_filters(plan(currentJobTitles=["VP Sales", "Director of Sales"],
                                             personCountries=["USA"]))
    assert warnings == []
    assert filters == {"op": "and", "conditions": [
        {"op": "or", "conditions": [
            {"field": CUR + "title", "type": "(.)", "value": "VP Sales"},
            {"field": CUR + "title", "type": "(.)", "value": "Director of Sales"},
        ]},
        {"field": "basic_profile.location.country", "type": "in", "value": ["United States"]},
    ]}


def test_single_condition_is_not_wrapped():
    filters, _ = compile_filters(plan(currentJobTitles=["CTO"]))
    assert filters == {"field": CUR + "title", "type": "(.)", "value": "CTO"}


def test_employer_hq_country_sends_both_spellings():
    filters, _ = compile_filters(plan(currentJobTitles=["CTO"], companyHeadquartersCountries=["India"]))
    hq = filters["conditions"][1]
    assert hq == {"field": CUR + "company_headquarters_country", "type": "in", "value": ["IND", "India"]}


def test_no_narrowing_filter_refuses_to_search():
    filters, warnings = compile_filters(plan(recentlyChangedJobs=True, filters=[
        {"field": CUR + "title", "type": "(!)", "value": "intern"}]))
    assert filters is None
    assert any("no positive narrowing" in w for w in warnings)


def test_recently_changed_jobs_only_added_alongside_real_filter():
    filters, _ = compile_filters(plan(currentJobTitles=["CTO"], recentlyChangedJobs=True))
    assert filters["conditions"][-1] == {"field": "recently_changed_jobs", "type": "=", "value": True}


def test_headcount_bounds_and_actively_hiring():
    filters, _ = compile_filters(plan(minHeadcount=20, maxHeadcount=200, activelyHiring=True,
                                      openToCards=["open to work"]))
    assert filters["conditions"] == [
        {"field": CUR + "company_headcount_latest", "type": "=>", "value": 20},
        {"field": CUR + "company_headcount_latest", "type": "=<", "value": 200},
        {"field": "professional_network.open_to_cards", "type": "in", "value": ["CAREER_INTEREST", "HIRING_MANAGER"]},
    ]


def test_raw_filters_are_validated_against_catalog():
    filters, warnings = compile_filters(plan(currentJobTitles=["CTO"], filters=[
        {"field": "education.degrees.name", "type": "in", "value": ["MBA"]},
        {"field": CUR + "company_industries", "type": "(.)", "value": ["Software", "SaaS"]},
        {"field": "skills.professional_network_skills", "type": "in", "value": "Python"},
    ]))
    assert any("education.degrees.name" in w for w in warnings)
    conditions = filters["conditions"]
    assert conditions[1] == {"op": "or", "conditions": [
        {"field": CUR + "company_industries", "type": "(.)", "value": "Software"},
        {"field": CUR + "company_industries", "type": "(.)", "value": "SaaS"},
    ]}
    assert conditions[2] == {"field": "skills.professional_network_skills", "type": "in", "value": ["Python"]}


def test_geo_only_on_raw_location():
    filters, warnings = compile_filters(plan(filters=[
        {"field": "professional_network.location.raw", "type": "geo_distance",
         "value": {"location": "Bengaluru, India", "distance": 30, "unit": "km"}},
        {"field": "basic_profile.location.city", "type": "geo_distance", "value": {"location": "x", "distance": 1}},
    ]))
    assert filters == {"field": "professional_network.location.raw", "type": "geo_distance",
                       "value": {"location": "Bengaluru, India", "distance": 30, "unit": "km"}}
    assert len(warnings) == 1


def test_all_of_group_over_past_roles():
    filters, warnings = compile_filters(plan(filters=[{"op": "all_of", "conditions": [
        {"field": "experience.employment_details.company_name", "type": "in", "value": ["Oracle"]},
        {"field": "experience.employment_details.end_date", "type": "=>", "value": "2025-01-01"},
    ]}]))
    assert warnings == []
    assert filters["op"] == "all_of" and len(filters["conditions"]) == 2


def test_raw_country_filter_is_normalized_per_field():
    filters, _ = compile_filters(plan(filters=[
        {"field": "basic_profile.location.country", "type": "in", "value": ["IND", "uk"]}]))
    assert filters["value"] == ["India", "United Kingdom"]


def test_sorts_default_and_validation():
    warnings: list[str] = []
    assert compile_sorts(plan(currentJobTitles=["x"]), warnings) == DEFAULT_SORTS
    sorts = compile_sorts(plan(sorts=[{"field": "updated_at", "type": "asc"}, {"field": "bogus"}]), warnings)
    assert sorts == [{"field": "metadata.updated_at", "order": "asc"}]
    assert any("bogus" in w for w in warnings)


def test_person_country_post_filter():
    rows = [
        {"basic_profile": {"location": {"country": "India"}}},
        {"basic_profile": {"location": {"country": "United States"}}},
        {"basic_profile": {}},
    ]
    kept, dropped = enforce_person_countries(rows, ["IND"])
    assert kept == rows[:1] and dropped == 2


def test_country_vocabularies():
    assert countries.to_iso3("United States") == "USA"
    assert countries.to_iso3("gb") == "GBR"
    assert countries.to_full("KOR") == "South Korea"
    assert countries.to_full("Atlantis") == "Atlantis"
