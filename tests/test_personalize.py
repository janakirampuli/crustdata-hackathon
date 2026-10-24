import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent.web import app
from skills.campaign import tools as campaign_tools
from skills.form_builder import personalize, store, tools
from skills.form_builder.schema import EmailTemplate, Survey
from tests.test_form_builder import SURVEY

EMAIL = {
    "subject": "A quick question for {company}",
    "body": "Hi {first_name},\n\nWould you be open to a {survey_minutes}-minute survey?\n\n{personal_line}\n\n{link}",
    "personal_line_rule": "One sentence linking their role and company size to agent data infra.",
    "fallback_line": "We're hearing from engineering leads at AI startups like {company}.",
}
ASHA = {"crustdata_person_id": 42, "name": "Asha Rao", "title": "CTO", "company": "Acme AI", "company_headcount": 120,
        "role_start_date": "2023-04-01", "business_email": "asha@acme.ai", "location": "Bengaluru"}
RAVI = {"crustdata_person_id": 7, "name": "Ravi Iyer", "title": "VP Engineering", "company": "Zeta"}
SURVEY_WITH_EMAIL = {**SURVEY, "email": EMAIL}
SURVEY_NO_EMAIL = {k: v for k, v in SURVEY.items() if k != "email"}


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMS_DB", str(tmp_path / "forms.db"))
    monkeypatch.setenv("FORMS_BASE_URL", "http://test")


@pytest.fixture
def writer(monkeypatch):
    """Asha gets a grounded line; Ravi gets one with an invented funding round."""
    lines = {"42": {"personal_line": "As CTO of a 120-person team at Acme AI since 2023, your view sets the bar.",
                    "facts_used": ["title", "company_headcount", "company", "role_start_date"]},
             "7": {"personal_line": "Congrats on Zeta's Series B.", "facts_used": ["company"]}}
    calls = []

    def fake(survey, targets):
        calls.append([str(t["crustdata_person_id"]) for t in targets])
        return {str(t["crustdata_person_id"]): lines[str(t["crustdata_person_id"])] for t in targets}

    monkeypatch.setattr(personalize, "write_lines", fake)
    return calls


def survey() -> Survey:
    return Survey.model_validate(SURVEY_WITH_EMAIL)


@pytest.mark.parametrize("change, message", [
    ({"body": "Hi {first_name}, {personal_line}"}, "{link}"),
    ({"body": "{link} {link} {personal_line}"}, "{link}"),
    ({"body": "Hi {nickname} {link} {personal_line}"}, "nickname"),
    ({"subject": "Survey {link}"}, "subject"),
    ({"fallback_line": "Take it here: {link} please"}, "fallback_line"),
])
def test_template_rejects_bad_placeholders(change, message):
    with pytest.raises(ValidationError, match=message):
        EmailTemplate.model_validate({**EMAIL, **change})


@pytest.mark.parametrize("line, facts, reason", [
    ("As CTO at Acme AI, your view matters.", ["title", "company"], None),
    ("Your 120-person team at Acme AI is the stage we study.", ["company_headcount", "company"], None),
    ("Congrats on the Series B at Acme AI.", ["company"], "Series"),
    ("Leading 300 engineers at Acme AI matters here.", ["company"], "300"),
    ("As CTO at Acme AI, your view matters.", ["seniority"], "seniority"),
    ("As CTO at Acme AI, your view matters.", [], "cites no facts"),
])
def test_personal_line_must_trace_to_profile(line, facts, reason):
    result = personalize.ungrounded(line, facts, ASHA, survey())
    assert result is None if reason is None else reason in result


def test_render_fills_placeholders_and_falls_back():
    good = personalize.render(survey(), ASHA, "http://test/s/abc",
                              {"personal_line": "As CTO at Acme AI, your view matters.", "facts_used": ["title"]})
    assert good["subject"] == "A quick question for Acme AI" and good["to"] == "asha@acme.ai"
    assert good["body"].startswith("Hi Asha,") and "3-minute" in good["body"] and "http://test/s/abc" in good["body"]
    assert "As CTO at Acme AI" in good["body"] and good["body"].endswith("Opt out: http://test/s/abc/opt-out") and good["personalized"]

    fallback = personalize.render(survey(), RAVI, "http://test/s/def", None)
    assert not fallback["personalized"] and "engineering leads at AI startups like Zeta." in fallback["body"]


def test_draft_stores_preview_for_review(writer):
    created = tools.create_survey.invoke({"survey": SURVEY_WITH_EMAIL, "sample_targets": [ASHA, RAVI]})
    assert [p["personal_line_ok"] for p in created["email_preview"]] == [True, False]
    preview = store.get_survey(created["survey_id"])["email_preview"]
    assert preview["samples"][0]["name"] == "Asha Rao" and "<personal link>" in preview["emails"][0]["body"]

    canvas = TestClient(app).get(f"/api/surveys/{created['survey_id']}/canvas").text
    assert "Personal line" in canvas and "Fallback" in canvas and "name not in the profile: Series" in canvas
    assert '<span class="ph">{personal_line}</span>' in canvas

    tools.revise_survey.invoke({"survey_id": created["survey_id"], "survey": SURVEY_WITH_EMAIL})
    assert writer[-1] == ["42", "7"]  # a revision without samples re-fills the earlier ones


def test_draft_and_revision_need_a_template():
    assert tools.create_survey.invoke({"survey": SURVEY_NO_EMAIL})["error"] == "email_template_required"
    survey_id = tools.create_survey.invoke({"survey": SURVEY_WITH_EMAIL})["survey_id"]
    revised = tools.revise_survey.invoke({"survey_id": survey_id, "survey": SURVEY_NO_EMAIL})
    assert revised["error"] == "email_template_required" and store.get_survey(survey_id)["version"] == 1


AUDIENCE = {"description": "Eng leads", "plan": {}}


def launch(survey_id, targets):
    return campaign_tools.launch.invoke({"survey_id": survey_id, "targets": targets, "audience": AUDIENCE})


def test_launch_sends_the_template_filled_per_person(writer):
    survey_id = tools.create_survey.invoke({"survey": SURVEY_WITH_EMAIL})["survey_id"]
    store.set_status(survey_id, "approved")
    result = launch(survey_id, [ASHA, {**RAVI, "business_email": "ravi@zeta.io"}])
    assert result["emails"]["personalized"] == 1 and result["emails"]["fallback"] == 1
    assert [p["personalized"] for p in result["invited"]] == [True, False]
    asha = next(m for m in store.list_outbox(survey_id) if m["to_email"] == "asha@acme.ai")
    assert asha["subject"] == "A quick question for Acme AI" and "As CTO of a 120-person team" in asha["body"]
    assert f"/s/{result['invited'][0]['token']}/opt-out" in asha["body"]

    again = launch(survey_id, [ASHA])
    assert again["invited"] == [] and writer[-1] == ["42", "7"]  # nobody new, so no new lines written


def test_launch_without_a_template_uses_the_built_in_invite(writer):
    survey_id = store.create_survey(Survey.model_validate(SURVEY_NO_EMAIL))
    store.set_status(survey_id, "approved")
    result = launch(survey_id, [ASHA])
    assert isinstance(result["emails"], str) and "personalized" not in result["invited"][0] and writer == []
    assert "We're reaching out because" in store.list_outbox(survey_id)[0]["body"]
