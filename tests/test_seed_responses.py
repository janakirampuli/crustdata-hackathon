import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from skills.campaign import analytics
from skills.form_builder import store
from tests.test_campaign import approved_survey, launch, target

spec = importlib.util.spec_from_file_location("seed_responses",
                                              Path(__file__).parents[1] / "scripts" / "seed_responses.py")
seed_responses = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_responses)
Answer = seed_responses.Answer


def fake_writer(survey, brief, story, people):
    """Valid answers for most, one invalid choice and one skipped question that fall back to random valid ones."""
    out = {}
    for p in people:
        i = p["respondent"]
        out[i] = [Answer(question_id="role", values=["Decide" if i % 3 else "Maybe"]),
                  Answer(question_id="pain", values=[str(1 + i % 5)]),
                  Answer(question_id="gap", values=[f"Respondent {i}: our enrichment vendor lags by about {i} weeks."])]
    return out


def test_seeds_answers_into_the_agents_campaign_with_fictional_names(monkeypatch):
    monkeypatch.setattr(seed_responses, "write_answers", fake_writer)
    survey_id = approved_survey(max_invites=30, target_responses=12)
    launch(survey_id, [target(i) for i in range(20)])
    real_names = {f"Person {i}" for i in range(20)}

    result = seed_responses.seed(survey_id, responses=12, hours=6, review=False)

    row = store.get_survey(survey_id)
    assert result["responses"] == 12 and row["status"] == "closed" and row["close_reason"] == "target reached"
    launched = datetime.fromisoformat(row["launched_at"])
    assert (datetime.now(timezone.utc) - launched).total_seconds() > 5.5 * 3600
    participants = store.list_participants(survey_id)
    assert not real_names & {p["target"]["name"] for p in participants}
    assert all(p["target"]["business_email"].endswith(".example") for p in participants)
    assert all(m["to_email"].endswith(".com") for m in store.list_outbox(survey_id))  # the agent's emails stay as sent

    responses = store.list_responses(survey_id)
    assert all(r["answers"]["role"] in ("Decide", "Not involved") for r in responses)
    assert all(launched < datetime.fromisoformat(r["submitted_at"]) < datetime.now(timezone.utc) for r in responses)
    v = analytics.compute(survey_id)["verification"]
    assert (v["verified"], v["flagged"], v["excluded"]) == (9, 1, 2)
    assert min(r["quality_score"] for r in responses) < 60  # the straight-lined, pasted answer ranks low
