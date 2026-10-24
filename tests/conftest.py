import pytest


@pytest.fixture(autouse=True)
def isolated_forms_db(tmp_path, monkeypatch):
    """Every test gets its own forms.db, so no test can write into data/forms.db (modules may still override)."""
    monkeypatch.setenv("FORMS_DB", str(tmp_path / "forms.db"))


@pytest.fixture(autouse=True)
def no_model_review(monkeypatch):
    """Quality review calls a model in the background; tests score with rules only."""
    monkeypatch.setenv("QUALITY_REVIEW", "off")
