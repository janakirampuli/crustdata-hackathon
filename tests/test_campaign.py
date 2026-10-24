from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from skills.campaign import analytics, service, tools
from skills.form_builder import personalize, store
from skills.form_builder import tools as form_tools
from skills.form_builder.schema import CampaignConfig
from skills.form_builder.server import app

SURVEY = {
    "title": "Agent data infra",
    "research_question": "How do builders choose agent data infra?",
    "audience": "Engineering leads",
    "intro": "Two minutes, research only.",
    "questions": [
        {"id": "role", "type": "single_choice", "prompt": "Your role?", "options": ["Decide", "Not involved"]},
        {"id": "pain", "type": "scale", "prompt": "How painful?", "scale_min": 1, "scale_max": 5},
        {"id": "gap", "type": "text", "prompt": "Biggest gap?", "required": False},
    ],
    "email": {"subject": "Research on {company}", "body": "Hi {first_name},\n\n{personal_line}\n\n{link}",
              "personal_line_rule": "Their role.", "fallback_line": "We're hearing from leads like you."},
}
AUDIENCE = {"description": "Eng leads in Bengaluru", "plan": {"currentJobTitles": ["CTO"]},
            "effective_filters": {"field": "x", "type": "=", "value": 1}, "total_count": 120}


def target(i: int, email: bool = True, **extra) -> dict:
    return {"crustdata_person_id": i, "name": f"Person {i}", "title": "CTO", "company": f"Co {i}",
            "business_email": f"p{i}@co{i}.com" if email else None, "seniority": "CXO" if i % 2 else "Director",
            "company_headcount": 40 + i * 30, **extra}


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMS_DB", str(tmp_path / "forms.db"))
    monkeypatch.setenv("FORMS_BASE_URL", "http://test")
    monkeypatch.setattr(personalize, "write_lines", lambda survey, targets: {})


@pytest.fixture
def client():
    return TestClient(app)


def approved_survey(**config) -> str:
    survey_id = form_tools.create_survey.invoke({"survey": SURVEY})["survey_id"]
    store.set_status(survey_id, "approved")
    if config:
        store.set_config(survey_id, CampaignConfig(**config))
    return survey_id


def launch(survey_id: str, targets: list[dict]) -> dict:
    return tools.launch.invoke({"survey_id": survey_id, "targets": targets, "audience": AUDIENCE})


def test_launch_requires_approval():
    survey_id = form_tools.create_survey.invoke({"survey": SURVEY})["survey_id"]
    assert launch(survey_id, [target(1)])["error"] == "not_approved"


def test_launch_caps_invites_skips_missing_emails_and_writes_outbox():
    survey_id = approved_survey(max_invites=2)
    result = launch(survey_id, [target(1), target(2, email=False), target(3), target(4)])
    assert [p["name"] for p in result["invited"]] == ["Person 1", "Person 3"]
    reasons = {s["name"]: s["reason"] for s in result["skipped"]}
    assert reasons == {"Person 2": "no business email", "Person 4": "max_invites (2) reached"}
    assert result["status"] == "fielding" and result["invites_left"] == 0
    outbox = store.list_outbox(survey_id)
    assert {m["to_email"] for m in outbox} == {"p1@co1.com", "p3@co3.com"}
    assert all("/opt-out" in m["body"] and "http://test/s/" in m["body"] for m in outbox)
    assert store.get_survey(survey_id)["audience"].total_count == 120


def test_second_batch_adds_people_without_reinviting():
    survey_id = approved_survey()
    launch(survey_id, [target(1)])
    result = launch(survey_id, [target(1), target(2)])
    assert [p["name"] for p in result["invited"]] == ["Person 2"]
    assert result["skipped"][0]["reason"] == "already invited"


def test_followups_respect_delay_and_max():
    survey_id = approved_survey(followup_after_minutes=30, max_followups=1)
    launch(survey_id, [target(1)])
    assert service.send_followups(survey_id) == []           # too early
    assert len(service.send_followups(survey_id, force=True)) == 1
    assert service.send_followups(survey_id, force=True) == []  # max reached
    assert [m["kind"] for m in store.list_outbox(survey_id)] == ["followup", "invite"]


def test_response_reaching_target_closes_survey(client):
    survey_id = approved_survey(target_responses=1)
    token = launch(survey_id, [target(1), target(2)])["invited"][0]["token"]
    client.post(f"/s/{token}", data={"role": "Decide", "pain": "4"})
    row = store.get_survey(survey_id)
    assert row["status"] == "closed" and row["close_reason"] == "target reached"
    states = {p["crustdata_person_id"]: p["state"] for p in store.list_participants(survey_id)}
    assert states == {"1": "responded", "2": "expired"}


def test_opt_out_stops_link(client):
    survey_id = approved_survey()
    token = launch(survey_id, [target(1)])["invited"][0]["token"]
    client.post(f"/s/{token}/opt-out")
    assert "opted out" in client.get(f"/s/{token}").text
    assert store.invite_stats(survey_id)["opted_out"] == 1


def test_tick_closes_at_deadline():
    survey_id = approved_survey(deadline_minutes=5)
    launch(survey_id, [target(1)])
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    with store.connect() as conn:
        conn.execute("UPDATE surveys SET closes_at = ? WHERE id = ?", (past, survey_id))
    service.tick()
    assert store.get_survey(survey_id)["close_reason"] == "deadline"


def test_analytics_counts_and_segments(client):
    survey_id = approved_survey()
    tokens = [p["token"] for p in launch(survey_id, [target(i) for i in range(1, 5)])["invited"]]
    for token, (role, pain) in zip(tokens, [("Decide", "5"), ("Decide", "4"), ("Not involved", "2")]):
        client.post(f"/s/{token}", data={"role": role, "pain": pain, "gap": "Freshness"})
    stats = analytics.compute(survey_id)
    assert stats["funnel"]["responded"] == 3 and stats["response_rate_pct"] == 75.0
    role = stats["questions"][0]
    assert [(o["label"], o["count"]) for o in role["options"]] == [("Decide", 2), ("Not involved", 1)]
    assert stats["questions"][1]["mean"] == pytest.approx(3.67, abs=0.01)
    assert stats["segments"]["seniority"]["mix"] == {"CXO": 2, "Director": 1}
    assert stats["questions"][2]["answers"][0]["who"] == "CTO · Co 1"


def test_config_form_and_every_tab_render(client):
    survey_id = approved_survey()
    client.post(f"/surveys/{survey_id}/config", data={"max_invites": "7", "target_responses": "3",
                                                     "deadline_minutes": "60", "followup_after_minutes": "10",
                                                     "max_followups": "2"})
    assert store.get_survey(survey_id)["config"].max_invites == 7
    token = launch(survey_id, [target(1), target(2)])["invited"][0]["token"]
    client.post(f"/s/{token}", data={"role": "Decide", "pain": "3"})
    for tab in ("progress", "participants", "survey", "audience", "analytics", "activity"):
        page = client.get(f"/surveys/{survey_id}?tab={tab}")
        assert page.status_code == 200, tab
    assert "p1@co1.com" in client.get(f"/surveys/{survey_id}?tab=participants").text
    assert "120" in client.get(f"/surveys/{survey_id}?tab=audience").text
