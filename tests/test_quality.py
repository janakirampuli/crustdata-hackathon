import json

import pytest
from fastapi.testclient import TestClient

from skills.campaign import quality
from skills.campaign import tools as ct
from skills.form_builder import store
from skills.form_builder.schema import Survey
from skills.form_builder.server import app

SURVEY = {
    "title": "Agent data infra", "research_question": "How do builders choose agent data infra?",
    "audience": "Engineering leads", "intro": "Research only.", "estimated_minutes": 3,
    "questions": [
        {"id": "role", "type": "single_choice", "prompt": "Your role?", "options": ["Decide", "Recommend", "Not involved"]},
        {"id": "pain", "type": "scale", "prompt": "How painful?", "scale_min": 1, "scale_max": 5},
        {"id": "trust", "type": "scale", "prompt": "How much do you trust vendors?", "scale_min": 1, "scale_max": 5},
        {"id": "spend", "type": "number", "prompt": "Monthly spend, USD?", "required": False},
        {"id": "gap", "type": "text", "prompt": "Biggest gap?", "required": False},
    ],
}
GOOD_TEXT = "We still scrape LinkedIn pages for job changes because no vendor gives us fresh data for Indian startups"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMS_DB", str(tmp_path / "forms.db"))
    monkeypatch.setenv("FORMS_BASE_URL", "http://test")


@pytest.fixture
def campaign():
    survey_id = store.create_survey(Survey.model_validate(SURVEY))  # no email template: built-in invite, no model call
    store.set_status(survey_id, "approved")
    targets = [{"crustdata_person_id": i, "name": f"P{i}", "business_email": f"p{i}@x{i}.com"} for i in range(8)]
    result = ct.launch.invoke({"survey_id": survey_id, "targets": targets, "audience": {"description": "x"}})
    return survey_id, [p["token"] for p in result["invited"]]


def submit(token, answers, active_s=120, typed=True, ua="ua-1"):
    meta = {"active_s": active_s, "fields": {}}
    if answers.get("gap"):
        n = len(answers["gap"])
        meta["fields"]["gap"] = {"keys": n if typed else 2, "pastes": 0 if typed else 1, "pasted_chars": 0 if typed else n}
    data = {k: [str(x) for x in v] if isinstance(v, list) else str(v) for k, v in answers.items()}
    TestClient(app).post(f"/s/{token}", data={**data, "__meta": json.dumps(meta)}, headers={"user-agent": ua})


def by_token(survey_id):
    return {r["token"]: r for r in store.list_responses(survey_id)}


@pytest.mark.parametrize("text, bad", [("asdf asdf jkl", True), ("aaaaaaa", True), ("ok", True), ("xzq vbn tkl prt", True),
                                       ("Fresher data for Indian startups", False), ("Price.", False)])
def test_gibberish(text, bad):
    assert quality.is_gibberish(text) is bad


def test_ranking_separates_genuine_from_spam(campaign):
    survey_id, t = campaign
    submit(t[0], {"role": "Decide", "pain": 4, "trust": 2, "spend": 800, "gap": GOOD_TEXT})        # genuine typer
    submit(t[1], {"role": "Decide", "pain": 3, "trust": 3}, active_s=12)                             # speeder
    submit(t[2], {"role": "Decide", "pain": 5, "trust": 5, "gap": "asdf qwer zxcv"}, ua="ua-2")      # mash
    submit(t[3], {"role": "Recommend", "pain": 4, "trust": 2, "gap": GOOD_TEXT}, typed=False, ua="ua-3")  # copy of t0
    r = by_token(survey_id)
    assert r[t[0]]["quality_tier"] == "high" and r[t[0]]["quality_score"] >= 80
    codes = {k: {f["code"] for f in v["quality_flags"]} for k, v in r.items()}
    assert {"thoughtful", "typed", "optional", "paced"} <= codes[t[0]]
    assert r[t[1]]["quality_tier"] == "spam" and "speeder" in codes[t[1]]
    assert r[t[2]]["quality_tier"] == "spam" and {"gibberish", "straightline"} <= codes[t[2]]
    assert r[t[3]]["quality_tier"] == "spam" and {"duplicate_text", "pasted"} <= codes[t[3]]


def test_not_involved_and_outlier_lower_the_score(campaign):
    survey_id, t = campaign
    for i, spend in enumerate([500, 600, 700, 800]):
        submit(t[i], {"role": "Decide", "pain": 3, "trust": 4, "spend": spend}, ua=f"ua-{i}")
    submit(t[4], {"role": "Not involved", "pain": 2, "trust": 4, "spend": 90000}, ua="ua-x")
    r = by_token(survey_id)[t[4]]
    assert {"not_involved", "outlier"} <= {f["code"] for f in r["quality_flags"]}
    assert r["quality_score"] <= 54 and r["quality_tier"] == "low"


def test_mash_typed_by_hand_earns_no_effort_points(campaign):
    survey_id, t = campaign
    submit(t[0], {"role": "Decide", "pain": 3, "trust": 4, "gap": "asdf qwer zxcv"})
    codes = {f["code"] for f in by_token(survey_id)[t[0]]["quality_flags"]}
    assert "gibberish" in codes and not codes & {"typed", "optional", "thoughtful"}


def test_model_review_adjusts_the_score(campaign):
    survey_id, t = campaign
    submit(t[0], {"role": "Decide", "pain": 4, "trust": 2, "gap": "Better data quality and coverage overall would help"})
    before = by_token(survey_id)[t[0]]["quality_score"]
    store.set_quality_llm(t[0], {"answers": [{"id": "gap", "relevance": 1, "specificity": 0, "ai_like": True,
                                              "note": "generic wish list"}]})
    quality.rescore(survey_id)
    after = by_token(survey_id)[t[0]]
    assert after["quality_score"] == before - 5 - 10
    assert any(f["label"] == "Q5: generic wish list" for f in after["quality_flags"])


def test_summary_counts_tiers(campaign):
    survey_id, t = campaign
    submit(t[0], {"role": "Decide", "pain": 4, "trust": 2, "spend": 800, "gap": GOOD_TEXT})
    submit(t[1], {"role": "Decide", "pain": 3, "trust": 3}, active_s=5)
    mix = quality.summary(survey_id)
    assert mix["tiers"]["high"] == 1 and mix["tiers"]["spam"] == 1 and mix["total"] == 2
