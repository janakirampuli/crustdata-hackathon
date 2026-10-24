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
- Business emails: `crustdata_enrich_contact` returns real emails via `/person/enrich` when `CRUSTDATA_MOCK_CONTACT_ENRICH=false`; set it to `true` to mock. Mock emails are plus-addresses of `MOCK_EMAIL_INBOX` (or `@mock.invalid`), marked `mocked: true`, so outreach can't reach strangers. **Teammate:** in mock mode the email domain won't match the employer, so the domain-vs-employer verification check has to skip or flag mocked targets.

**Still to build**
- Outreach: sending invite emails, follow-ups, a send cap, and the consent line.
- Verification check: nothing sets a response's `verified` field yet, so every response stays `pending`.
- Simulated lane: forecast answers from each target's profile.
- Analysis/report page, and the end-to-end demo run (brief → targets → emails → links → responses → report).

## Work split (proposal — adjust)

| Who | Owns |
|---|---|
| Praneeth | LangGraph agent backbone, Crustdata skill (port from Kris), PLAN + TARGET steps, simulated lane |
| Teammate | Outreach (email sending + follow-ups), unique-link/token survey form, verification check, results collection |
| Together | Analysis/report page, demo script, planted fakes |

Interface between the halves: a **target record** `{crustdata_person_id, name, title, company, company_domain, linkedin_url, business_email, why_qualified}` goes into outreach. A **response record** `{token, crustdata_person_id, answers, submitted_from_email, verified: ok|flag|fail, reason}` comes back out.

## Open questions

1. ~~Which form tool?~~ Settled: our own FastAPI form server (`skills/form_builder`).
2. Email sending: Gmail API vs Resend/SES. We need reply tracking for follow-ups.
3. Will the organizers let us survey the room and share the attendee list?
4. ~~Contact enrich access~~: Crustdata confirmed they'll enable `POST /person/contact/enrich` (our only source of business emails) on our key later, around demos. Until then it's **mocked** (`CRUSTDATA_MOCK_CONTACT_ENRICH=true`). Still to confirm: the `end_date` filter behaves as documented.
