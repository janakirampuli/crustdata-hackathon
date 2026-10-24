import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from skills.form_builder import store, tools
from skills.form_builder.schema import OTHER, Question, Survey, parse_answers
from skills.form_builder.server import app

SURVEY = {
    "title": "Agent data infra",
    "research_question": "How do builders choose agent data infra?",
    "audience": "Engineering leads at AI startups",
    "intro": "Two minutes, research only.",
    "questions": [
        {"id": "role", "type": "single_choice", "prompt": "Your role in choosing?", "options": ["Decide", "Not involved"]},
        {"id": "sources", "type": "multi_choice", "prompt": "Sources used?", "options": ["Web", "B2B data"],
         "allow_other": True},
        {"id": "pain", "type": "scale", "prompt": "How painful?", "scale_min": 1, "scale_max": 5},
        {"id": "spend", "type": "number", "prompt": "Monthly spend, USD?", "required": False},
        {"id": "gap", "type": "text", "prompt": "Biggest gap?", "required": False},
    ],
    "email": {"subject": "Agent data infra at {company}", "body": "Hi {first_name}, {personal_line} {link}",
              "personal_line_rule": "One sentence on their role.", "fallback_line": "We're asking AI builders."},
}
TARGET = {"crustdata_person_id": 42, "name": "Asha Rao", "title": "CTO", "company": "Acme",
          "business_email": "asha@acme.ai"}


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMS_DB", str(tmp_path / "forms.db"))
    monkeypatch.setenv("FORMS_BASE_URL", "http://test")


@pytest.fixture
def client():
    return TestClient(app)


def approved_link() -> tuple[str, str]:
    survey_id = tools.create_survey.invoke({"survey": SURVEY})["survey_id"]
    store.set_status(survey_id, "approved")
    link = tools.create_invite_links.invoke({"survey_id": survey_id, "targets": [TARGET]})["links"][0]
    return survey_id, link["token"]


def test_choice_question_needs_options():
    with pytest.raises(ValidationError):
        Question(id="x", type="single_choice", prompt="Pick one", options=["only"])


def test_duplicate_question_ids_rejected():
    spec = {**SURVEY, "questions": [SURVEY["questions"][0], SURVEY["questions"][0]]}
    with pytest.raises(ValidationError):
        Survey.model_validate(spec)


def test_parse_answers_types_and_other():
    survey = Survey.model_validate(SURVEY)
    answers, errors = parse_answers(survey, {
        "role": ["Decide"], "sources": ["Web", OTHER], "sources__other": ["Internal wiki"],
        "pain": ["4"], "spend": ["1200"], "gap": [""],
    })
    assert errors == {}
    assert answers == {"role": "Decide", "sources": ["Web", "Other: Internal wiki"], "pain": 4, "spend": 1200.0,
                       "gap": None}


def test_parse_answers_rejects_missing_and_out_of_range():
    survey = Survey.model_validate(SURVEY)
    _, errors = parse_answers(survey, {"role": ["Not an option"], "sources": [OTHER], "pain": ["9"]})
    assert set(errors) == {"role", "sources", "pain"}


def test_invalid_survey_is_rejected_by_args_schema():
    bad = {**SURVEY, "questions": [{"id": "Bad Id", "type": "text", "prompt": "Hi?"}]}
    with pytest.raises(ValidationError):
        tools.create_survey.invoke({"survey": bad})


def test_links_refused_until_approved():
    survey_id = tools.create_survey.invoke({"survey": SURVEY})["survey_id"]
    result = tools.create_invite_links.invoke({"survey_id": survey_id, "targets": [TARGET]})
    assert result["error"] == "not_approved"


def test_reinviting_same_person_reuses_token():
    survey_id, token = approved_link()
    again = tools.create_invite_links.invoke({"survey_id": survey_id, "targets": [TARGET]})["links"][0]
    assert again["token"] == token and again["reused"]


def test_revise_locked_once_invites_exist():
    survey_id, _ = approved_link()
    assert tools.revise_survey.invoke({"survey_id": survey_id, "survey": SURVEY})["error"] == "locked"


def test_review_page_approve_and_request_changes(client):
    survey_id = tools.create_survey.invoke({"survey": SURVEY})["survey_id"]
    assert "Agent data infra" in client.get("/surveys").text
    client.post(f"/surveys/{survey_id}/request-changes", data={"feedback": "Drop the spend question"})
    state = tools.get_survey.invoke({"survey_id": survey_id})
    assert state["status"] == "changes_requested" and state["feedback"] == "Drop the spend question"
    tools.revise_survey.invoke({"survey_id": survey_id, "survey": SURVEY})
    client.post(f"/surveys/{survey_id}/approve")
    assert tools.get_survey.invoke({"survey_id": survey_id})["status"] == "approved"


def test_respondent_submits_once(client):
    survey_id, token = approved_link()
    page = client.get(f"/s/{token}")
    assert page.status_code == 200 and "Hi Asha" in page.text
    form = {"role": "Decide", "sources": ["Web", "B2B data"], "pain": "3"}
    assert "Thank you" in client.post(f"/s/{token}", data=form).text
    assert "Already answered" in client.post(f"/s/{token}", data=form).text

    result = tools.get_responses.invoke({"survey_id": survey_id})
    assert result["stats"] == {"invited": 1, "opened": 1, "responded": 1, "opted_out": 0}
    response = result["responses"][0]
    assert response["crustdata_person_id"] == "42"
    assert response["answers"]["sources"] == ["Web", "B2B data"]
    assert response["verified"] == "pending"


def test_invalid_submission_rerenders_with_errors(client):
    _, token = approved_link()
    response = client.post(f"/s/{token}", data={"sources": "Web"})
    assert response.status_code == 422 and "This question is required." in response.text


def test_unknown_token_and_closed_survey(client):
    assert client.get("/s/nope").status_code == 404
    survey_id, token = approved_link()
    client.post(f"/surveys/{survey_id}/close")
    assert "closed" in client.get(f"/s/{token}").text
