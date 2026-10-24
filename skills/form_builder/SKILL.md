---
name: form-builder
description: Draft a short B2B survey and its invite email template from the client's brief, get both approved by a human, then mint one identity-bound link per verified target and read back the answers.
---

# Form builder

You write the questionnaire. Our own form server hosts it, so every link is tied to one Crustdata person.

## Lifecycle

1. `form_create_survey`: save a draft with its invite email template (`survey.email`) and up to 3 `sample_targets`: real people from your Crustdata search for this audience, with their profile facts. If you haven't searched yet, run one `crustdata_search_people` at `limit` 3 first. The chat shows it as an approval card, and `review_url` opens the same review as a page. Don't repeat the questions or the link in your reply: one or two lines asking them to approve or request changes on the card, then stop. Do not mint links yourself.
2. A human opens the review page and either approves it or requests changes.
3. `form_get_survey`: check the status.
   - `changes_requested`: read `feedback` and call `form_revise_survey` with the full revised survey. That sends it back to draft.
   - `approved`: go on to step 4.
4. Fieldwork belongs to the campaign skill: `campaign_launch` creates the links and sends each person the approved email template, filled in for them (see the campaign skill). Use `form_create_invite_links` only when the user wants raw links without emails. Each URL works once and only for that person. Never send one link to several people.
5. `form_get_responses`: answers, each bound to its `crustdata_person_id`, plus invited/opened/responded counts. Only analyse rows whose `verified` is not `fail`.

If a tool refuses (`not_approved`, `locked`, `invalid_survey`), read the error and fix the call. Do not work around approval.

## Writing the survey

- **Length:** 5–8 questions, about 3 minutes, and at most one open text question. Completion drops past 7–8 minutes, and senior people quit early. Put the time in `estimated_minutes`. Do not promise less than it takes.
- **`intro`** (shown to respondents): 2–4 short sentences saying who is asking and why, that answers are used only for this research and not for sales, how long it takes, and that it's fine to skip. No pitch.
- **Don't ask what Crustdata already knows:** title, seniority, company, company size, industry and location. Ask what only the respondent knows: behaviour, decisions, spend, pain, intent.
- **First question:** confirm involvement, e.g. "Which best describes your role in choosing X?". Include a "Not involved" option so the answer can be screened later.
- **Prefer closed questions:**
  - `single_choice`: mutually exclusive options.
  - `multi_choice`: "select all that apply".
  - `scale`: e.g. 1–5 or 0–10, always with `min_label` and `max_label`.
  - `number`: counts, money or percentages; put the unit in the prompt.
  - `text`: only for the one open question.
- **One idea per question.** Never ask "how fast and reliable…".
- **Neutral wording.** Don't lead ("How much do you love…") or presuppose ("Why did you switch…" before establishing that they switched).
- **Options:** cover the whole range and don't overlap: 1–10 / 11–50 / 51–200, not 1–10 / 10–50. Add `allow_other` when your list might miss real answers, and "None" or "Don't know" where honest people need it.
- **Balanced scales:** both ends labelled, same number of points on each side.
- **Ids:** short snake_case names for what each answer means (`current_vendor`, `monthly_spend_usd`). The analysis step reads these ids.

## Writing the invite email (`survey.email`)

The client approves the template once; nobody reviews the individual emails. Code fills `{first_name}`, `{name}`, `{title}`, `{company}`, `{survey_minutes}` and `{link}` from each target record. A writer model fills `{personal_line}` per person at launch, following `personal_line_rule`, and code rejects any line with a number or name that isn't in that person's Crustdata facts. A rejected line becomes `fallback_line`.

- **`subject`:** short and plain, e.g. "Quick research question on {company}'s eng tooling". No clickbait.
- **`body`:** under 120 words. Greet with `{first_name}`, then ask for consent in the first sentence ("Would you be open to a {survey_minutes}-minute research survey on X?"). Then `{personal_line}`, why their answer matters, that answers are used only for this research, then `{link}`. Sign off as the research team. Code appends the opt-out footer, so don't write one.
- **`personal_line_rule`:** what the line should connect, e.g. "One sentence linking their role and company size to why their view on X matters." Professional facts only.
- **`fallback_line`:** a generic sentence that is true for everyone in the audience, e.g. "We're hearing from engineering leaders at Indian SaaS companies like {company}."

## Standard methods (use these exactly; don't invent new ones)

- **Product–market fit (Sean Ellis):**
  - `single_choice` "How would you feel if you could no longer use X?", with options Very disappointed / Somewhat disappointed / Not disappointed / I no longer use X.
  - The benchmark is 40% "Very disappointed".
- **NPS:** `scale` 0–10 "How likely are you to recommend X to a colleague?", with labels Not at all likely / Extremely likely.
- **Pricing (Van Westendorp):**
  - Four `number` questions in this order:
    - too cheap to trust the quality,
    - a bargain,
    - getting expensive but still worth considering,
    - too expensive to consider.
  - Give the same unit and period in each prompt, e.g. "USD per user per month".
- **Problem severity:** `scale` 1–5 "How big a problem is X for your team today?", with labels Not a problem / Critical problem. Follow it with "How do you handle it today?" as `single_choice` with `allow_other`.

## Example

```json
{
  "title": "How AI builders choose agent data infrastructure",
  "research_question": "How are Bengaluru AI builders choosing agent data infrastructure?",
  "audience": "Founders and engineering leads at Bengaluru AI startups building agents",
  "intro": "We're a small team at ContextCon Build researching how builders pick data infrastructure for AI agents. It takes about 2 minutes. Answers are used only for this research and shared back in aggregate. Feel free to skip.",
  "estimated_minutes": 2,
  "questions": [
    {"id": "decision_role", "type": "single_choice", "prompt": "What is your role in choosing data sources for your agents?",
     "options": ["I make the decision", "I recommend or evaluate", "I use what's chosen", "Not involved"]},
    {"id": "data_sources", "type": "multi_choice", "prompt": "Which external data sources do your agents use today?",
     "options": ["Web search APIs", "B2B people/company data", "Scraped websites", "Internal docs only", "None yet"], "allow_other": true},
    {"id": "top_criterion", "type": "single_choice", "prompt": "When choosing a data provider, what matters most?",
     "options": ["Accuracy / freshness", "Coverage", "Price", "Latency", "Ease of integration"]},
    {"id": "pain_severity", "type": "scale", "prompt": "How big a problem is getting reliable data into your agents today?",
     "scale_min": 1, "scale_max": 5, "min_label": "Not a problem", "max_label": "Critical problem"},
    {"id": "monthly_spend_usd", "type": "number", "prompt": "Roughly how much does your team spend on external data per month, in USD?", "required": false},
    {"id": "biggest_gap", "type": "text", "prompt": "What's the one thing you wish your agent data stack did better?", "required": false}
  ],
  "email": {
    "subject": "A 2-minute question on agent data at {company}",
    "body": "Hi {first_name},\n\nWould you be open to a {survey_minutes}-minute research survey on how teams choose data infrastructure for AI agents?\n\n{personal_line} Your answers go only into this research, shared back in aggregate.\n\n{link}\n\nThanks,\nThe Verified Research team",
    "personal_line_rule": "One sentence linking their role and company stage to why their view on agent data infrastructure matters.",
    "fallback_line": "We're hearing from founders and engineering leads at Bengaluru AI startups like {company}."
  }
}
```
