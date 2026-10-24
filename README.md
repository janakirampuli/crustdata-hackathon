# Verified B2B Research Agent

See [CONTEXT.md](CONTEXT.md) for the idea, the user flow and the work split.

## Run

```bash
cp .env.example .env        # fill API keys; AGENT_MODEL picks the model
uv sync
uv run agent                # REPL
uv run agent "Find 10 engineering leaders at Bengaluru startups with 20-200 people"
uv run pytest -q            # offline tests for the Crustdata filter compiler
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
  form_builder/ on hold (enabled: false)
```

## Adding a skill

Create `skills/<name>/SKILL.md` with `name` / `description` frontmatter. Optionally add `tools.py` with `TOOLS = [...]` (LangChain `@tool`s that return dicts). It's picked up automatically. Set `enabled: false` in the frontmatter to park it.

Model: set `AGENT_MODEL` in `.env` (required; the example uses `claude-sonnet-5-5`). Don't pass `temperature`: Opus 5.5 rejects it.
