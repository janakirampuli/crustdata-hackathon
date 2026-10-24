---
name: campaign
description: Run fieldwork for an approved survey (invite verified targets, track progress, nudge, close) and turn the responses into analytics and a findings report.
---

# Campaign

One approved survey is one campaign. Every person invited, every email and every response is tracked in the survey workspace (`workspace_url`), which has these tabs: Progress, Participants, Survey, Audience, Analytics and Activity.

## Lifecycle

1. **Settings.** Before launch, set fieldwork settings with `campaign_configure`:
   - `target_responses`: the brief's sample size.
   - `max_invites`: about target ÷ 0.1. Plan on a 10% response rate.
   - `deadline_minutes`
   - `followup_after_minutes`

   The user may already have set these in the UI. Read them back with `campaign_status` and don't overwrite them unless asked.
2. **Targets.** Pick people from `crustdata_search_people` and get each one's business email with `crustdata_enrich_contact`:
   - Use the email on the current employer's domain.
   - Prefer `deliverable` emails over `catch_all`.
   - Never guess an email.
3. **Launch.** `campaign_launch` only works on an approved survey. Pass:
   - **`targets`:** full target records. Include `why_qualified` (one clause the invite email uses, such as "you lead platform engineering at a 120-person fintech") and copy `seniority`, `function`, `company_headcount` and `location` from the search rows, so the analysis can split by them.
   - **`audience`:** the persona description; the exact `plan`, `effective_filters` and `total_count` of the search the targets came from; and the confirmed brief as markdown in `brief`. This is what the Audience tab shows, and the report checks the hypotheses against it.
4. **Monitor.** `campaign_status` reports the funnel, pace and a recommendation.
   - If you're behind pace with invites left, find the next batch (exclude people already invited) and call `campaign_launch` again.
   - `campaign_nudge` sends the follow-up now. The scheduler also sends it automatically after `followup_after_minutes`.
5. **Close.** The survey closes on its own when `target_responses` is reached or the deadline passes. `campaign_close` ends it early.
6. **Report.** `campaign_report` computes the stats and writes the findings. Give the user the headline and the `analytics_url`. Don't restate every number: the page shows them.

## Rules

- Emails are written to the outbox (`email_mode: log`). Say so if the user asks whether people were emailed.
- Never invite more people than `max_invites`. If the user wants more, raise it with `campaign_configure` first.
- Report results only from `campaign_report` or `campaign_status`. Never estimate them.
