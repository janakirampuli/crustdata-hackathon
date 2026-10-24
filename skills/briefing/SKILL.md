---
name: briefing
description: Turn any request, however vague, into a confirmed research brief (objective, decision, persona sized with Crustdata, method, market context) before a survey is drafted.
---

# Briefing

Every new study starts here. Do not draft a survey, mint links or look up emails until the user has confirmed a brief. A follow-up on an existing study (status, revisions, responses) skips this stage.

**Fast path: skip the brief when the user asks for a draft directly.** If they say to skip the brief, or ask to draft a survey and name both the topic and the audience, call `form_create_survey` straight away, after at most one `crustdata_search_people` at `limit` 3 for the email preview's sample people. Don't web search, size personas or ask first. The approval card in the chat is their checkpoint, so don't ask "go?" before saving. In your reply, give the audience you assumed in one line and offer to size it with Crustdata after approval. Don't paste the questions into the chat: the card already shows them.

## Steps

1. **Pin down the ask.** If the request doesn't say what decision it informs or who should answer, ask at most two short questions in one message. Offer your best guess for each so the user can just reply "yes". Never ask for something you can look up, and skip this step when the request is already specific.
2. **Market context: `web_search`, 2–4 searches.** Look for the players and alternatives in the space, who buys and why, pricing norms and recent shifts. This is what makes the survey concrete, e.g. real vendor names as answer options instead of invented ones.
   - Don't search for survey methodology: the form-builder skill has the standard methods.
   - Don't search for people: that is Crustdata's job.
   - If the searches turn up nothing useful, say so and continue with clearly labelled assumptions.
3. **Persona, sized with Crustdata.** Draft 1–3 candidate personas (titles, seniority, function, company size, geography, industry, as the ask implies). Size each with `crustdata_search_people` at `limit` 5: only `total_count` and the share with `has_business_email` matter here. Pick the persona that fits best with enough reachable people. Widen it if too few people match, and narrow it if a broad one would dilute the answers.
   - Read the sample rows, not just the count. If they show off-target people (wrong function, or employers outside the space), tighten and size again before presenting. Industry labels are loose: for a space like fintech, find the companies with `crustdata_search_companies` and filter people by `companyIds`.
4. **Sample size.** Aim for 20–30 verified responses unless the user says otherwise. Plan on a 10% response rate, so invites needed ≈ 10 × target, and the persona needs at least that many people with a business email.
5. **Present the brief** in exactly this shape, then stop and wait:

   **Research brief**
   - **Objective:** one sentence.
   - **Decision it informs:** what the client will do differently depending on the answer.
   - **Key questions:** 3–5 things we must learn.
   - **Hypotheses:** what we expect to find, so the survey can confirm or refute it.
   - **Persona:** the definition, plus Crustdata counts (total matches, with business email). Name the alternatives you sized and why you dropped them.
   - **Sample:** target verified responses and invites needed.
   - **Method:** survey type, which standard methods apply (PMF, NPS, Van Westendorp, or none), length (5–8 questions, about 3 minutes).
   - **Market context:** 3–5 bullets, each with its source link.

   End with: "Confirm or edit this, and I'll draft the survey."
6. **After confirmation,** hand over to the form-builder skill. Build the questions from the key questions and hypotheses, take answer options from the market context, and use the persona as the Crustdata plan for targets.

## Rules

- Market facts come from search results or the user. Label anything else as an assumption.
- Search spends real time on stage (a few seconds each). Don't search for definitions you already know.
- Keep the brief scannable: bullets, no long prose.
