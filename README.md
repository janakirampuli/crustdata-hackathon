# Verified B2B Research Agent

See [CONTEXT.md](CONTEXT.md) for the idea, the user flow and the work split.

## Run

```bash
cp .env.example .env        # fill API keys; AGENT_MODEL picks the model
uv sync
uv run agent                # REPL
uv run agent "Find 10 engineering leaders at Bengaluru startups with 20-200 people"
uv run forms                # form server: http://localhost:8000/surveys (review + approve), /s/<token> (respondents)
uv run pytest -q            # offline tests
```

## Layout

```
agent/
  graph.py      LangGraph backbone: model node ⇄ tool node; system prompt = base + every SKILL.md
  skills.py     discovers skills/<name>/SKILL.md (+ tools.py exposing TOOLS)
  cli.py        terminal driver
skills/
  crustdata/    Crustdata knowledge + tools (ported from Kris@Work)
    SKILL.md            query-authoring rules, vocabularies, examples, person filter catalog
    contact_plan.py     typed people plan → Crustdata filter DSL (+ catalog validation, country fixes)
    tools.py            search_people, enrich_person, identify_company, search_companies, search_jobs, get_credits
    reference/person_filter_catalog.json
  form_builder/ survey drafting, human approval, one identity-bound link per target
    SKILL.md            lifecycle + questionnaire design rules + standard methods (PMF, NPS, Van Westendorp)
    schema.py           Survey / Question spec the LLM writes, server-side answer validation
    store.py            SQLite (data/forms.db): surveys, invites (token ↔ crustdata_person_id), responses
    tools.py            form_create_survey, form_revise_survey, form_get_survey, form_list_surveys,
                        form_create_invite_links, form_get_responses
    server.py           FastAPI pages: /surveys list, /surveys/<id> review/approve, /s/<token> respondent form
```

## Adding a skill

Create `skills/<name>/SKILL.md` with `name` / `description` frontmatter. Optionally add `tools.py` with `TOOLS = [...]` (LangChain `@tool`s that return dicts). It's picked up automatically. Set `enabled: false` in the frontmatter to park it.

Model: set `AGENT_MODEL` in `.env` (required; the example uses `claude-sonnet-5-5`). Don't pass `temperature`: Opus 5.5 rejects it.
