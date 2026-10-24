import importlib.util
from pathlib import Path

from skills.campaign import analytics
from skills.form_builder import store

spec = importlib.util.spec_from_file_location("seed_demo", Path(__file__).parents[1] / "scripts" / "seed_demo.py")
seed_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_demo)


def test_seeded_campaign_is_closed_with_verified_and_planted_answers(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMS_DB", str(tmp_path / "forms.db"))
    monkeypatch.setattr(store, "_now", store._now)  # the seed swaps in its own clock
    survey_id = seed_demo.seed(report=False)
    row = store.get_survey(survey_id)
    assert row["status"] == "closed" and row["brief"] and row["audience"].total_count == 1240
    stats = analytics.compute(survey_id)
    assert stats["funnel"]["invited"] == 80 and stats["funnel"]["responded"] == 24
    v = stats["verification"]
    assert (v["verified"], v["flagged"], v["excluded"], v["pending"]) == (21, 1, 2, 0)
    assert stats["funnel"]["counted"] == 22
