# Demo script: Verified Research

Pointers for a 3 to 5 minute video. Talk freely around them; these are the things to hit.

## 1. The problem (about 45 s)

Crustdata asked us two questions when we pitched: why do companies pay for surveys, and what does it cost today. Open with the answers.

**Why companies run B2B surveys**
- Decisions that need numbers from real buyers: market sizing, pricing and willingness to pay, product and concept validation, unmet needs, win/loss. ([SIS](https://www.sisinternational.com/top-5-benefits-of-b2b-market-research/), [Sogolytics](https://www.sogolytics.com/learning-center/managed-research/b2b-market-research/), [NewtonX](https://www.newtonx.com/article/research-for-go-to-market-planning/))
- In B2B, one account can be worth hundreds of consumer sales, so one pricing decision carries a lot of money. ([Sogolytics](https://www.sogolytics.com/learning-center/managed-research/b2b-market-research/))
- Original research is also a marketing asset. "State of X" reports drive pipeline:
  - 75% of B2B buyers say a piece of thought leadership led them to research a product they weren't considering. ([Edelman and LinkedIn 2024](https://www.edelman.com/insights/thought-leadership-gets-b2b-buyers-back-into-game))
  - 73% trust it more than marketing material for judging a company. (same source)
  - 93% of B2B marketers use research-based content they find effective for engagement and leads. ([MediaPost on TopRank/Ascend2](https://www.mediapost.com/publications/article/410608/its-showtime-for-research-b2b-brands-use-surveys.html))
- The market is large: about $150B for insights overall in 2024 and about $54–56B for market research alone. ([ESOMAR via Research World](https://researchworld.com/articles/inside-the-153bn-insights-industry), [Ipsos](https://www.ipsos.com/en-nl/node/1081941))

**What it costs today**
- Panel price per completed survey:
  - consumer: about $5–35;
  - B2B individual contributor: about $40–80;
  - director or VP: about $150–200;
  - niche or C-suite (CISO, CTO): $150–500 or more. ([CleverX](https://cleverx.com/blog/b2b-panel-pricing-vs-consumer-panel-pricing/), [CleverX enterprise](https://cleverx.com/blog/best-b2b-research-panel-providers-for-enterprise-teams-in-2026/))
- Recruiting 200 B2B decision makers costs about $20k–60k, before any analysis. ([DoppelIQ](https://www.doppeliq.ai/blog/how-much-does-a-survey-really-cost))
- A full-service custom study costs about $15k–50k and takes 4–12 weeks. Agencies add 40–70% for management. ([Preuve](https://preuve.ai/blog/how-much-does-market-research-cost), [CleverX](https://cleverx.com/blog/market-research-cost-benchmarks-b2b-saas-funding-stage))
- An expert-network call costs about $400–1,200+ an hour at GLG and $700–1,800+ at AlphaSights, sold in prepaid bundles. ([CleverX comparison](https://cleverx.com/blog/best-expert-network-platforms-complete-comparison-guide))

**And the data is often fake (the real hook)**
- 15–45% of online panel responses get thrown out as fraud or junk. B2B is at the high end. ([Pogo roundup](https://www.joinpogo.com/articles/survey-fraud-market-research-widespread), [Rep Data: 29% flagged](https://repdata.com/blog/what-new-research-on-research-says-about-fraud-in-survey-data))
- Asked how many of 100 B2B panel completes are genuine, most researchers in an informal poll said 10–20%. ([Quirk's](https://www.quirks.com/articles/why-research-agencies-must-prioritize-high-quality-b2b-data))
- An AI agent passed standard attention checks 99.8% of the time, at about 5 cents a response. "We can no longer trust that survey responses are coming from real people." (Westwood, PNAS 2025, [404 Media coverage](https://www.404media.co/a-researcher-made-an-ai-that-completely-breaks-the-online-surveys-scientists-rely-on/))
- Panels rely on self-reported job titles. Anyone can claim to be a VP of Engineering.

**One-line framing:** companies pay tens of thousands of dollars and wait weeks for B2B answers, and a large share of those answers come from people who aren't who they say they are.

## 2. What we built (about 15 s)

- An agent that replaces the survey firm, from brief to findings report.
- The difference is that every respondent is a real, verified person:
  - Crustdata finds the exact people (title, seniority, company size, location);
  - their work email is on their current employer's domain;
  - each survey link works once, and only for that person.
- Targeting comes from Crustdata's data, not from a profile the respondent filled in.

## 3. Live run (about 2 to 2.5 min)

Start at `http://localhost:8000/chat`.

1. **Brief in chat.** Type a real research question, e.g. pricing for a data API among Indian SaaS engineering leaders.
   - Show that the agent asks clarifying questions and writes a brief with hypotheses.
   - Show the Crustdata audience count (how many people match).
   - The brief takes about 50 s, so cut or speed up that part of the video.
2. **Survey draft and approval card.**
   - Edit through chat: "make question 3 a scale", "change the deadline to 2 days", "add a Van Westendorp pricing block".
   - Point out that standard methods (PMF, NPS, Van Westendorp) are built in and the survey stays short (about 3 minutes).
   - A human approves. Nothing goes out without approval.
3. **Launch with personalized emails.**
   - Open the outbox and one or two sample emails. The personal line comes from that person's Crustdata facts, and code rejects any line with a fact not in their profile.
   - Point out the consent line, the opt-out footer and the send cap.
   - Optional: a real email to the presenter through Resend (only allowlisted addresses receive mail).
4. **Respondent view.** Open one `/s/<token>` link and show the questionnaire. Don't submit a fast answer live: under about 30 s it gets tagged spam.

## 4. Results (about 1 to 1.5 min)

Off camera, before this part: `uv run python scripts/seed_responses.py <survey_id>`. It backdates the launch by 6 hours and fills in answers for the agent's campaign.

5. **Responses tab: quality ranking.**
   - Each response has a score from 0 to 100 and a tier.
   - Point at the planted cases:
     - the person who left the company (verification fail, excluded);
     - the duplicate (fail);
     - the speeder (flagged);
     - the pasted, straight-lined answer (low score).
   - Say it plainly: this is the 15–45% junk that panels charge you for. We catch it, and failed responses never reach the analysis.
6. **Ask the agent to write it up.** "Close the survey and give me the findings."
   - Show the short reply and open the link.
7. **Analytics tab.**
   - Headline, then each hypothesis supported or not. Example from the dry run: small companies rank price first, larger ones freshness.
   - Splits by company size and seniority come from Crustdata, so the questionnaire never had to ask.
   - The funnel shows invited, opened, responded and opted out.

## 5. Close (about 20 s)

- Compare costs: a $15k–50k agency study over 4–12 weeks, against Crustdata credits plus a few dollars of model calls. The agent gets from brief to a launched campaign in minutes; after that the wait is for real people to reply.
- Personalization at scale: every invite gets its own line from that person's Crustdata facts, where a panel sends one generic invite.
  - Read our real numbers off the Crustdata credits counter before recording. Don't quote a number we haven't measured.
- Why Crustdata: verified identity is what makes the data trustworthy, and Crustdata is the identity layer. Every study is a new Crustdata search and enrichment.
- Next steps: incentives and payouts, recurring tracker studies, a panel of verified respondents.

## Things to say if asked (Q&A)

- **Is the response data real?** In the demo, the answers are generated and the respondents are renamed to fictional people and companies, so no made-up answer is tied to a real person. The targets, emails and invites are what the agent produced.
- **Spam or privacy?** Each email asks for consent first, has an opt-out link and is capped per campaign. There's no automated LinkedIn messaging. Answers are used only for the research.
- **Response rates?** We plan on about 10% from cold outreach (max invites = target ÷ 0.1). Incentives raise this: $25–75 is the usual B2B band, with 50–70% response rates in one benchmark. ([Grape Data](https://grape-data.com/blog/how-to-incentivise-knowledgeable-b2b-respondents)) An honorarium cut fieldwork from 25 to 12 days in one study. ([Quirk's](https://www.quirks.com/articles/make-your-next-b2b-study-a-success))
- **Can a bot still answer?** It would need the person's inbox, because the link is single-use and tied to one person. Even then, the quality checks look at timing, typing versus pasting, straight-lining, contradictions and duplicates.
- **Why not Typeform plus a panel?** Typeform only hosts the form. You still buy a panel and inherit its fraud. We pick the people and verify them ourselves.

## Before recording

- Restart the server after any SKILL.md change. Stop it with Ctrl-C, not a force-kill, or agent.db's WAL breaks. The fix is `sqlite3 agent.db "PRAGMA wal_checkpoint(TRUNCATE)"`.
- For a live email: set `EMAIL_MODE=resend`, `RESEND_API_KEY`, `EMAIL_FROM` and `EMAIL_ALLOWLIST=<presenter>`, and add the presenter on the Participants tab.
- Raise `max_invites` (e.g. 120 for a target of 12) so the funnel reads like a realistic response rate rather than 68%.
- Keep a seeded survey ready as a fallback in case the live brief is slow or the network drops.

Source caveat: most cost and fraud figures come from vendor blogs, so quote them as ranges ("industry estimates put…"). The Westwood PNAS paper and the Edelman–LinkedIn study are the strongest sources.
