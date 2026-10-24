"""Turns the computed statistics into a short findings report with one model call."""

import json
import os

from langchain_anthropic import ChatAnthropic

from skills.form_builder import store

from . import analytics

PROMPT = """You are the analyst on a B2B research study. Write the findings report for the client from the data below.

Rules:
- Use only the numbers in STATS. Every finding cites its numbers and its n (e.g. "7 of 12, 58%").
- The client pays for verified respondents, so state the basis. Open the Headline with it, e.g. "From 21 verified
  respondents (2 excluded after failing verification): ...". Use the counts in STATS.verification: say "verified"
  only for its `verified` count, and name flagged or pending answers if there are any.
- With fewer than 10 responses, say the results are directional, not conclusive.
- Segment differences only count when each segment has at least 3 respondents; otherwise skip them.
- Quotes come verbatim from open-text answers, attributed by role and company type, never by name. Prefer answers
  with quality "high" or "ok"; never quote "spam".
- STATS.quality counts responses by quality tier. If any are "low" or "spam", say how many in Caveats and treat
  conclusions that depend on them with more caution.
- The brief was written before fieldwork, so its sample size and audience sizing are plans. FIELDWORK and STATS.funnel
  say what actually happened; report those and don't treat the difference as an error.
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
Sample size, response rate, and anything that limits the conclusions. List every excluded or flagged answer with its
reason from STATS.verification (by role, never by name), and say excluded answers are in none of the numbers.
## Recommendation
What the client should do next, tied to the decision the study informs.

RESEARCH QUESTION: {question}
AUDIENCE: {audience}
BRIEF:
{brief}

FIELDWORK: target {target} responses, at most {max_invites} invites.

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
        brief=(audience.brief if audience and audience.brief else row["brief"] or "(no brief recorded)"),
        target=row["config"].target_responses, max_invites=row["config"].max_invites,
        stats=json.dumps({k: v for k, v in stats.items() if k != "survey_id"}, ensure_ascii=False, indent=1),
    )
    # Thinking shares max_tokens with the answer, so leave room for both; streaming avoids long-request timeouts.
    message = ChatAnthropic(model=model, max_tokens=32000, streaming=True).invoke(prompt)
    blocks = [message.content] if isinstance(message.content, str) else message.content
    report = "".join(b if isinstance(b, str) else b.get("text", "") for b in blocks
                     if isinstance(b, str) or b.get("type") == "text")
    if not report.strip():
        return {"error": "empty_report", "detail": f"The model returned no text (stop: "
                f"{message.response_metadata.get('stop_reason')}). Try again."}
    store.save_insights(survey_id, stats, report.strip(), model)
    store.log_event(survey_id, "insights", detail={"n": stats["funnel"]["counted"], "model": model})
    return {"survey_id": survey_id, "report": report.strip(), "n": stats["funnel"]["counted"], "model": model}
