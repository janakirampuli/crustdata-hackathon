"""Turns the computed statistics into a short findings report with one model call."""

import json
import os

from langchain_anthropic import ChatAnthropic

from skills.form_builder import store

from . import analytics

PROMPT = """You are the analyst on a B2B research study. Write the findings report for the client from the data below.

Rules:
- Use only the numbers in STATS. Every finding cites its numbers and its n (e.g. "7 of 12, 58%").
- With fewer than 10 responses, say the results are directional, not conclusive.
- Segment differences only count when each segment has at least 3 respondents; otherwise skip them.
- Quotes come verbatim from open-text answers, attributed by role and company type, never by name.
- Plain, direct sentences. No filler.

Write markdown with exactly these sections:
## Headline
One or two sentences: the single most important answer to the research question.
## Key findings
3-5 bullets, most important first.
## Hypotheses
For each hypothesis in the brief (if any): confirmed, refuted or unclear, with the evidence.
## Segments
Notable differences by seniority, function or company size, or "No meaningful differences at this sample size."
## In their words
2-3 short quotes, if there are open-text answers.
## Caveats
Sample size, response rate, and anything that limits the conclusions.
## Recommendation
What the client should do next, tied to the decision the study informs.

RESEARCH QUESTION: {question}
AUDIENCE: {audience}
BRIEF:
{brief}

STATS:
{stats}
"""


def generate(survey_id: str) -> dict:
    row = store.get_survey(survey_id)
    stats = analytics.compute(survey_id)
    if not stats["funnel"]["counted"]:
        return {"error": "no_responses", "detail": "There are no responses to analyse yet."}
    audience = row["audience"]
    model = os.environ.get("INSIGHTS_MODEL") or os.environ.get("AGENT_MODEL", "claude-sonnet-5-5")
    prompt = PROMPT.format(
        question=row["spec"].research_question,
        audience=audience.description if audience else row["spec"].audience,
        brief=(audience.brief if audience and audience.brief else "(no brief recorded)"),
        stats=json.dumps({k: v for k, v in stats.items() if k != "survey_id"}, ensure_ascii=False, indent=1),
    )
    message = ChatAnthropic(model=model, max_tokens=4000).invoke(prompt)
    report = message.content if isinstance(message.content, str) else "".join(
        b.get("text", "") for b in message.content if isinstance(b, dict))
    store.save_insights(survey_id, stats, report.strip(), model)
    store.log_event(survey_id, "insights", detail={"n": stats["funnel"]["counted"], "model": model})
    return {"survey_id": survey_id, "report": report.strip(), "n": stats["funnel"]["counted"], "model": model}
