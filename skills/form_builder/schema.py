"""Survey spec the LLM writes, plus server-side answer validation for submitted forms."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

QuestionType = Literal["single_choice", "multi_choice", "scale", "text", "number"]
CHOICE_TYPES = ("single_choice", "multi_choice")
OTHER = "__other__"


class Question(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$", description="snake_case key for this answer, e.g. 'current_vendor'.")
    type: QuestionType
    prompt: str = Field(min_length=3, max_length=300)
    help: str | None = Field(None, max_length=200, description="Optional one-line hint under the prompt.")
    options: list[str] = Field(default_factory=list, description="Choice questions only: 2-10 mutually exclusive options.")
    allow_other: bool = Field(False, description="Choice questions only: add an 'Other' option with a text box.")
    scale_min: int = 1
    scale_max: int = 5
    min_label: str | None = Field(None, description="Scale only: label for the low end, e.g. 'Not at all likely'.")
    max_label: str | None = Field(None, description="Scale only: label for the high end, e.g. 'Extremely likely'.")
    required: bool = True

    @model_validator(mode="after")
    def _check(self):
        if self.type in CHOICE_TYPES:
            if not 2 <= len(self.options) <= 10:
                raise ValueError(f"{self.id}: choice questions need 2-10 options")
            if len(set(self.options)) != len(self.options):
                raise ValueError(f"{self.id}: duplicate options")
        elif self.options or self.allow_other:
            raise ValueError(f"{self.id}: options/allow_other only apply to choice questions")
        if self.type == "scale" and not (0 <= self.scale_min < self.scale_max and self.scale_max - self.scale_min <= 10):
            raise ValueError(f"{self.id}: scale needs 0 <= scale_min < scale_max with at most 11 points")
        return self


class Survey(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    research_question: str = Field(description="The client's question this survey answers. Not shown to respondents.")
    audience: str = Field(description="Who should answer, in plain words. Not shown to respondents.")
    intro: str = Field(max_length=800, description="Shown above the form: who is asking, why, how long it takes, "
                       "that answers are used for research only, and that they can skip it.")
    estimated_minutes: int = Field(3, ge=1, le=15)
    questions: list[Question] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question ids must be unique")
        return self


def parse_answers(survey: Survey, form: dict[str, list[str]]) -> tuple[dict, dict[str, str]]:
    """Turns raw form fields into typed answers keyed by question id. Returns (answers, errors)."""
    answers, errors = {}, {}
    for q in survey.questions:
        values = [v.strip() for v in form.get(q.id, []) if v.strip()]
        other = (form.get(f"{q.id}__other") or [""])[0].strip()
        if q.type in CHOICE_TYPES:
            picked = [v for v in values if v in q.options or (q.allow_other and v == OTHER)]
            if OTHER in picked:
                if not other:
                    errors[q.id] = "Please describe your 'Other' answer."
                    continue
                picked = [v for v in picked if v != OTHER] + [f"Other: {other}"]
            if q.type == "single_choice":
                picked = picked[:1]
            value = picked if q.type == "multi_choice" else (picked[0] if picked else None)
        elif q.type in ("scale", "number"):
            value = None
            if values:
                try:
                    value = int(values[0]) if q.type == "scale" else float(values[0])
                except ValueError:
                    errors[q.id] = "Please enter a number."
                    continue
                if q.type == "scale" and not q.scale_min <= value <= q.scale_max:
                    errors[q.id] = "Please pick a value on the scale."
                    continue
        else:
            value = values[0][:5000] if values else None
        if q.required and value in (None, []):
            errors[q.id] = "This question is required."
            continue
        answers[q.id] = value
    return answers, errors


class CampaignConfig(BaseModel):
    """Fieldwork settings for one survey. Editable in the survey workspace until the survey closes."""
    max_invites: int = Field(30, ge=1, le=500, description="Hard cap on people invited to this survey.")
    target_responses: int = Field(10, ge=1, le=500, description="Close automatically once this many people respond.")
    deadline_minutes: int = Field(240, ge=5, le=60 * 24 * 14, description="Close automatically this long after launch.")
    followup_after_minutes: int = Field(60, ge=1, le=60 * 24 * 7, description="Nudge non-responders after this long.")
    max_followups: int = Field(1, ge=0, le=3)


class Audience(BaseModel):
    """Who the survey targets and the exact Crustdata query that found them."""
    description: str = Field(description="The persona in plain words, e.g. 'Engineering leaders at Bengaluru startups, 20-200 people'.")
    plan: dict = Field(default_factory=dict, description="The ContactSearchPlan passed to crustdata_search_people.")
    effective_filters: dict | list | None = Field(None, description="effective_filters returned by that search.")
    total_count: int | None = Field(None, description="total_count returned by that search.")
    brief: str | None = Field(None, description="The confirmed research brief (markdown): objective, decision, "
                              "key questions, hypotheses. Used to write the insights.")
