import pytest


@pytest.fixture(autouse=True)
def no_model_review(monkeypatch):
    """Quality review calls a model in the background; tests score with rules only."""
    monkeypatch.setenv("QUALITY_REVIEW", "off")
