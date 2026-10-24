# Verified B2B Research Agent

See [CONTEXT.md](CONTEXT.md) for the idea, the user flow and the work split.

## Run

```bash
cp .env.example .env        # fill API keys; AGENT_MODEL picks the model
uv sync
uv run web                  # chat UI: http://localhost:8000/chat (also serves /surveys and /s/<token>)
uv run agent                # terminal REPL
uv run agent "Find 10 engineering leaders at Bengaluru startups with 20-200 people"
uv run forms                # form pages only: http://localhost:8000/surveys (review + approve), /s/<token> (respondents)
uv run pytest -q            # offline tests
```

## Layout

```
agent/
  graph.py      LangGraph backbone: model node ⇄ tool node; system prompt = base + every SKILL.md
  skills.py     discovers skills/<name>/SKILL.md (+ tools.py exposing TOOLS)
  cli.py        terminal driver
  web.py        chat UI server: streams turns over SSE, mounts the form server on the same port
  templates/chat.html  chat page (extends the shared console layout in skills/form_builder/templates)
  templates/_survey_canvas.html  in-chat survey approval canvas (approve / request changes)
  static/chat.js       streaming + run-log rendering (tool results as people tables, survey and invite cards)
skills/
  briefing/     vague ask → confirmed research brief: clarify, web search for market context, size personas with Crustdata
  crustdata/    Crustdata knowledge + tools (ported from Kris@Work)
    SKILL.md            query-authoring rules, vocabularies, examples, person filter catalog
    contact_plan.py     typed people plan → Crustdata filter DSL (+ catalog validation, country fixes)
    tools.py            search_people, enrich_person, enrich_contact (mock via CRUSTDATA_MOCK_CONTACT_ENRICH), identify_company,
                        search_companies, search_jobs, get_credits
    reference/person_filter_catalog.json
  campaign/     fieldwork for an approved survey (1 survey = 1 campaign)
    SKILL.md            lifecycle: configure → launch → monitor/nudge → close → report
    service.py          launch (respects max_invites), follow-ups, auto-close at target/deadline, 30s scheduler
    mailer.py           invite + follow-up emails; EMAIL_MODE=log records them in the outbox, EMAIL_MODE=resend sends via Resend
    analytics.py        funnel, per-question stats, segment splits by seniority / function / company size
    insights.py         findings report from the stats (one model call; INSIGHTS_MODEL overrides AGENT_MODEL)
    tools.py            campaign_configure, campaign_launch, campaign_status, campaign_nudge, campaign_close, campaign_report
  form_builder/ survey drafting, human approval, one identity-bound link per target
    SKILL.md            lifecycle + questionnaire design rules + standard methods (PMF, NPS, Van Westendorp)
    schema.py           Survey / Question spec the LLM writes, server-side answer validation
    store.py            SQLite (data/forms.db): surveys, invites (token ↔ crustdata_person_id), responses
    personalize.py      invite emails from the approved template: per-person line, grounding check, fallback
    tools.py            form_create_survey, form_revise_survey, form_get_survey, form_list_surveys,
                        form_create_invite_links, form_get_responses
    server.py           FastAPI pages: /surveys list, /surveys/<id> review/approve, /s/<token> respondent form
scripts/
  seed_demo.py          seeds a finished demo campaign (fictional people, planted fakes, findings report)
```

## Adding a skill

Create `skills/<name>/SKILL.md` with `name` / `description` frontmatter. Optionally add `tools.py` with `TOOLS = [...]` (LangChain `@tool`s that return dicts). It's picked up automatically. Set `enabled: false` in the frontmatter to park it.

Model: set `AGENT_MODEL` in `.env` (required; the example uses `claude-sonnet-5-5`). Don't pass `temperature`: Opus 5.5 rejects it.
