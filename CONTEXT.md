# Verified B2B Research Agent — Context

ContextCon Build: Agentic Services Hackathon (Crustdata), Bengaluru, Sat 24 Oct 2026.

| Time | What |
|---|---|
| 10:00 | Doors open |
| 17:00 | **Code freeze** |
| 17:15 | Live demos: 3 min + 2 min Q&A |
| 18:30 | People's Choice vote ("the demo they'd hire") |

Theme: **"Services, Replaced."** The page's examples (recruiter → accepted offer, diligence agent → red flags) all hand back the *finished outcome* with no human in between. Prizes: $4k / $2k / $500. Every builder gets a Crustdata API key with credits.

## The idea

Replace a **B2B survey / market research firm**. A company gives a research question and the kind of professional it wants to hear from. The agent hands back an **insights report built only from verified respondents**.

### Why this service
- B2B survey responses are expensive: roughly $30–60 per completed 10-minute survey and $300+ per verified B2B interview. The cost comes from scarcity: you may screen dozens of people to find one real IT director.
- Fraud is the industry's core problem. Panel respondents overstate seniority and company size to qualify for better-paying studies. "20 real people beat 200 fraudsters."
- AI-native research startups (Conveo, Outset, Dialogue AI, Strella, Electric Twin) automate moderation, analysis or synthetic respondents. **Nobody owns verified recruitment**, which is exactly what Crustdata data is for.

### Our core difference: target first, then contact
Panels: recruit anyone → screen → catch fraud after the fact.
Us: decide who qualifies (Crustdata) → contact **only** those people → each invite is bound to a verified profile.

- No screening funnel. Fraud mostly can't get in.
- Lower cost per *trustworthy* answer. Honest caveat: it's not faster per raw answer, because cold outreach converts at roughly 2–5%.
- **Identity binding is load-bearing.** Every invite carries a unique link tied to one Crustdata profile, sent to the person's business email, so the email domain proves the employer. Without this, a forwarded link breaks the anti-fraud claim.

## User flow

```
 CLIENT (once): research question · who to hear from · # real answers · incentive · deadline
                               │
 ══════════════════ AGENT OWNS EVERYTHING BELOW ══════════════════
  1. PLAN      questionnaire (5–8 Qs) + audience spec
               (titles, seniority, company size, industry, city)
  2. TARGET    Crustdata person/search → ranked list of people who qualify
               list size = answers needed ÷ expected response rate
  3. CONTACT   Contact Enrich for business email (selected targets only)
         ┌─────────────────────┴─────────────────────┐
  4a. REAL LANE                               4b. SIMULATED LANE
  personalised email, unique link per         predict each target's answers
  verified profile, automatic follow-ups      from their profile → FORECAST
  respondent fills short form                 (never mixed into real results)
  identity + consistency check
   ✓ link + email domain match profile
   ⚠ answers contradict their role → flag
  5. YIELD CHECK: behind target? → widen audience / next batch / raise incentive
         └─────────────────────┬─────────────────────┘
  6. ANALYSE   findings from real answers only · segment splits
               · forecast vs reality ("where the simulation was wrong")
 ═════════════════════════════════════════════════════════════════
 CLIENT RECEIVES: insights report · raw answers · verification log
```

**LLM vs plain code.** The LLM handles judgement: brief → questionnaire + audience, audience → Crustdata filters, simulated answers, analysis. Plain code handles mechanics: sending email, unique links/tokens, verification checks, follow-ups and the yield loop.

## Demo plan

- **Real lane = the hackathon room.** Get the Luma attendee list from the organizers, resolve each person in Crustdata, keep only those who match the brief, and email them at lunch. On stage: "the agent found N people in this room who qualify and contacted only them."
- **Simulated lane** = a forecast for every target, generated in the morning.
- **Reveal:** forecast vs real answers side by side, with the verification log on screen.
- **Plant 2 fake respondents** (forwarded links) so the identity check visibly catches them. Say on stage that we planted them.
- Example brief: *"How are Bengaluru AI builders choosing agent data infrastructure?"*

### Guardrails
- Email only. **No automated LinkedIn messaging** (it violates LinkedIn's ToS); show LinkedIn drafts as a "next channel".
- The invite's first line asks for consent, since we look up real people.
- Keep sends small and capped: targeted, not a spam tool.

## Tech decisions

- **Python + LangGraph** agent, fresh. Only the backbone, no memory/plumbing.
- **Skills** = a folder with a `SKILL.md` (knowledge) plus tools:
  - `skills/crustdata/` — Crustdata search/enrich tools + query-authoring knowledge, ported from Kris@Work (approved).
  - `skills/form_builder/` — our own FastAPI + SQLite form server. The agent drafts the survey, a human approves it, then the agent mints one single-use link per target, bound to a `crustdata_person_id`.
- Crustdata's own MCP server: explore later.

## Crustdata API notes

- Base `https://api.crustdata.com/`, headers `Authorization: Bearer <key>` and `x-api-version: 2025-11-01`.
- `POST /person/search`: filter DSL `{field, type, value}` or `{op: and|or, conditions: [...]}`.
  - Past employer: `experience.employment_details.past.company_name`
  - Current title: `experience.employment_details.current.title`
  - Seniority: `experience.employment_details.current.seniority_level`
  - Location: `basic_profile.location.*`, or `geo_distance` on `professional_network.location.raw`
  - `recently_changed_jobs` (boolean)
  - Operators: `= != < =< > => in not_in (.) [.] (!) is_null is_not_null has_all`
  - Paginate with `next_cursor`, and add `sorts` for stable order.
  - Role end dates *are* filterable: `experience.employment_details.end_date` / `start_date` (all roles). Combine with `company_name` inside an `all_of` group to express "a role at X that ended after D". (Not yet verified live.)
  - ~0.03 credits per result; premium field groups cost more.
  - Always pass `fields` as whole sections (`basic_profile`, `experience`, `social_handles`, `contact`). The leaf paths `basic_profile.first_name` / `last_name` → HTTP 400.
- `POST /person/enrich` by LinkedIn URL or business email. **Pass `fields`**, or you get only name + id.
- Search returns **no emails**, only a `has_business_email` flag and the LinkedIn URL. Emails come from `POST /person/enrich` with `fields: ["contact.business_emails"]` (tested live: 2 credits per matched person, returns `crustdata_person_id` + every business email with its status). **Contact Enrich** (`POST /person/contact/enrich`, 1 credit, +0.5 with `verified: true`) is still disabled on our key. A person can have several "deliverable" business emails on different domains (old employer, personal domain), so pick the one matching the current employer's domain. Statuses: deliverable, catch_all, invalid, unknown.
- People often hold several *current* roles, and filters match any of them. The tool's summary view shows the role that matched.
- `POST /company/identify` is free; `POST /company/search` and `POST /job/search` are also available.
- `GET /user/credits` returns the balance (zero-credit call).

## Status

- Agent backbone + Crustdata skill: done and tested live. See [README.md](README.md) to run it.
- Form builder: done (teammate). Survey drafting with a human approval gate, one identity-bound link per target, and response collection. Run it with `uv run forms`; set `FORMS_BASE_URL` to a public tunnel URL for real invites.
- Briefing stage: done. Every new study starts with a research brief the user confirms: clarify the ask (at most two questions), 2–4 web searches for market context (Anthropic's server-side `web_search`, capped at 5 per turn), and candidate personas sized with Crustdata. The brief covers objective, decision, key questions, hypotheses, persona with counts, sample size, method, and sourced market context. Haiku 5.5 needs `web_search_20250305`; `agent/graph.py` picks the version from `AGENT_MODEL`.
- Research brief: saved with the survey (`form_create_survey(brief=...)`, kept on revise). `campaign_launch` copies it into the audience when `audience.brief` is empty, and the report falls back to it.
- Demo data: the agent drafts the survey and email and launches the campaign in chat; then `uv run python scripts/seed_responses.py <survey_id>` adds only the respondents' side to that campaign: opens, opt-outs and answers written by `AGENT_MODEL` to fit each invitee's role and company size, plus planted cases (2 fail verification, 1 flagged speeder, 1 straight-lined paste). It first gives every invitee a fictional name, company, size and email, so made-up answers never sit under a real person; the outbox keeps the agent's emails. It moves the launch back `--hours` (default 6) so answers spread over time, `--story` steers the pattern, and reaching the target closes the survey and writes the findings report (`--no-report` leaves that for the agent). Any close (target, deadline or the reviewer's button) writes the findings in the background; the agent's `campaign_close` doesn't, because `campaign_report` follows it. Older fully scripted samples: `uv run python scripts/seed_demo.py` seeds a finished campaign (80 fictional invitees on `.example` addresses, 24 responses: 21 verified, 1 flagged, 2 planted fakes excluded, opens, follow-ups, opt-outs, closed at target) and writes the findings report. Times are relative to now, so run it shortly before the demo. `--no-report` skips the model call. Nothing is sent.
- Invite emails: done. The invite email is a template (`survey.email`) approved together with the survey, so nobody reviews individual emails. Code fills `{first_name}`, `{name}`, `{title}`, `{company}`, `{survey_minutes}` and `{link}` from the target record and appends the opt-out footer. At `campaign_launch` a small model (`EMAIL_MODEL`, default `claude-haiku-5-5`) writes `{personal_line}` per person from their Crustdata facts, batched 10 per call. Code then rejects any line with a number or proper noun that isn't in that person's facts or the study description, and swaps in the template's `fallback_line`. The finished emails go to the outbox; `invited` events record `personalized`. The workspace Survey tab and the chat approval card show the template plus 3 filled-in sample emails for real people, with the personal line highlighted and the facts it used. Pass the profile facts (`headline`, `seniority`, `function`, `company_headcount`, `role_start_date`) on each target, or everyone gets the fallback line. Follow-ups keep the built-in wording.
- Chat UI: done. `uv run web` serves the chat at `/chat` and mounts the form server on the same port, so `/surveys` and `/s/<token>` keep working and `FORMS_BASE_URL` doesn't change. Turns stream over SSE, and tool results render as cards: people tables, invite links, response counts. A drafted or revised survey shows as an approval canvas in the chat: the full questionnaire preview with Approve and Request changes. Both post to the form server's own approval routes, then send the agent a message so it continues (it revises on feedback, or moves on to targets once approved). The canvas is rendered server-side (`GET /api/surveys/<id>/canvas`) and refreshes after each turn and when the tab regains focus, so an approval on the full page shows up too. Conversations persist in SQLite (`data/agent.db`, `AGENT_DB` overrides), so they survive reloads and server restarts. Every model call uses automatic prompt caching: it reads the earlier conversation from cache and writes only the new tail. **Teammate:** a new tool gets a generic card automatically; add a renderer in `agent/static/chat.js` (`RENDER`) for a nicer one.
- Business emails: `crustdata_enrich_contact` returns real emails via `/person/enrich` when `CRUSTDATA_MOCK_CONTACT_ENRICH` is `false` **or unset** (real people's emails, 2 credits each); set it to `true` to mock while testing. Mock emails are plus-addresses of `MOCK_EMAIL_INBOX` (or `@mock.invalid`), marked `mocked: true`, so outreach can't reach strangers. **Teammate:** in mock mode the email domain won't match the employer, so the domain-vs-employer verification check has to skip or flag mocked targets.

- Campaign (teammate): one approved survey = one campaign. `campaign_launch` takes target records plus the `audience` (persona, the exact Crustdata `plan` / `effective_filters` / `total_count`, and the confirmed brief) and invites up to `max_invites`. Per-survey settings (max invites, target responses, deadline, follow-up delay, max follow-ups) are editable in the survey workspace. A 30s scheduler sends follow-ups and closes at the target or deadline. Every email (template-built or built-in wording) lands in the survey's outbox with its status. `EMAIL_MODE=log` (default) only records; `EMAIL_MODE=resend` sends via Resend (`RESEND_API_KEY`, `EMAIL_FROM` on our verified domain, optional `EMAIL_REPLY_TO`) with one-click unsubscribe headers. Mock `.invalid` addresses and anyone not on `EMAIL_ALLOWLIST` are recorded but never sent, so they still show as invited. A real send that fails leaves the person "Not sent". **Demo setup:** `CRUSTDATA_MOCK_CONTACT_ENRICH=true` (targets get mock addresses), `EMAIL_MODE=resend`, `EMAIL_ALLOWLIST=<presenter's email>`, and add the presenter on the Participants tab ("Add a participant by hand") to get a real invite. The workspace at `/surveys/<id>` has tabs: Survey, Participants (audience: persona, readable Crustdata filters, reach; then everyone invited, with status filter and search), Progress, Responses (ranked by quality), Analytics (charts, segment splits, LLM findings) and Activity (event log + outbox). **Praneeth:** target records should carry `why_qualified` (used by the built-in invite wording when a survey has no template) and `seniority`, `function`, `company_headcount`, `location` from the search rows (used for segment splits).

- Response quality (teammate): every response is ranked, and nothing is excluded.
  - **Rules on submit:** speed versus the estimate, straight-lining, keyboard mash, typed versus pasted open text (the form posts keystroke and paste counts, never the text typed), optional answers, "not involved" (capped at low), number outliers, "None" plus other options, and duplicates.
  - **Background review with Jev** (TypeSafe's decision model) when `TYPESAFE_API_KEY` is set. One call per response asks narrow typed questions and combines them in code: per open answer, relevance and specificity (Score), plus gibberish and machine-written (Noul); for the whole response, whether the answers fit the person's Crustdata profile (Noul). Low-confidence Score verdicts count as neutral. Without a key, `claude-haiku-5-5` reviews instead (`QUALITY_MODEL`). `QUALITY_REVIEW=off` disables the review.
  - **Where it shows:** a 0–100 score, a tier (high / ok / low priority / likely spam) and reasons on the workspace's new Responses tab (ranked, with a Rescore button), a quality mix on Analytics, and quality-sorted quotes. The findings report avoids spam quotes and notes low-quality counts in its caveats.

**Still to build**
- Resend delivery webhooks (bounces, complaints) and reply tracking. Needs a public URL.
- Verification check: nothing sets a response's `verified` field yet, so every response stays `pending`. Analytics and the report already show verified / flagged / pending / excluded counts and reasons, and the report's Headline states the basis.
- Simulated lane: forecast answers from each target's profile.
- The end-to-end demo run (brief → targets → emails → links → responses → report). The analysis/report page is done (workspace Analytics tab).

## Work split (proposal — adjust)

| Who | Owns |
|---|---|
| Praneeth | LangGraph agent backbone, Crustdata skill (port from Kris), PLAN + TARGET steps, simulated lane |
| Teammate | Outreach (email sending + follow-ups), unique-link/token survey form, verification check, results collection |
| Together | Analysis/report page, demo script, planted fakes |

Interface between the halves: a **target record** `{crustdata_person_id, name, title, company, company_domain, linkedin_url, business_email, why_qualified}` goes into outreach. A **response record** `{token, crustdata_person_id, answers, submitted_from_email, verified: ok|flag|fail, reason}` comes back out.

## Open questions

1. ~~Which form tool?~~ Settled: our own FastAPI form server (`skills/form_builder`).
2. ~~Email sending~~: Resend (`EMAIL_MODE=resend`). Reply tracking still open.
3. Will the organizers let us survey the room and share the attendee list?
4. ~~Contact enrich access~~: Crustdata confirmed they'll enable `POST /person/contact/enrich` on our key later, around demos. Not blocking: `/person/enrich` already returns business emails, and `crustdata_enrich_contact` uses it unless `CRUSTDATA_MOCK_CONTACT_ENRICH=true`. Still to confirm: the `end_date` filter behaves as documented.
