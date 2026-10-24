---
name: crustdata
description: Find and verify B2B people and companies with Crustdata (person search/enrich, company identify/search, job search).
---

# Crustdata

Crustdata indexes LinkedIn-derived people and company data. Use it to turn an audience description into a concrete, verifiable list of people.

## Picking a tool

| Need | Tool |
|---|---|
| People by title, seniority, function, geography, employer attributes, skills, past employers, education | `crustdata_search_people` (typed plan) |
| Canonical name / primary domain / id for a named company | `crustdata_identify_company` (**free**). Call this before filtering people by employer. |
| Verify one specific person's current employer and title | `crustdata_enrich_person` (no emails) |
| Business email for a **selected** target | `crustdata_enrich_contact` (2 credits per matched person; only for final targets, never a whole search page). Prefer `deliverable`; treat `catch_all` as unconfirmed. People often have several business emails (old employers, personal domains): pick the one on the current employer's domain. Search results only carry `has_business_email`. |
| Companies by revenue, funding, technologies, or other firmographics | `crustdata_search_companies`, then people via `companyIds` |
| Companies that are hiring for a role | `crustdata_search_jobs` |
| Credit balance | `crustdata_get_credits` (zero-credit) |

Person search is billed at about 0.03 credits per returned profile. Start with a small `limit` (10–25), check `total_count`, then page with `next_cursor` using the **same** plan.

## Rules that matter

1. **Ground every filter in the brief.** Emit only constraints the brief states or clearly implies. Never invent an industry, size, or geography just to have something to send: a made-up filter silently narrows the list to the wrong people. Fewer, high-signal filters beat a long noisy list.
2. **Countries come in two vocabularies.** The person's own country (`personCountries`) uses full names (`United States`, `India`). Company-side countries use ISO-3 (`USA`, `IND`). The compiler normalizes friendly fields, but raw company-search filters must already use ISO-3.
3. **Exact-match fields need Crustdata's exact strings.** Wrong strings silently match **zero**:
   - `seniorityLevels`: `CXO`, `Vice President` (not "VP"), `Director`, `Senior`, `Entry Level` (not "Entry"), `Entry Level Manager`, `Experienced Manager`, `In Training`, `Owner / Partner`, `Strategic`.
   - `functionCategories`: `Sales`, `Engineering`, `Marketing`, `Finance`, `Operations`, `Consulting`, `Research`, `Customer Success and Support`, `Arts and Design`, `Human Resources`, `Legal`, `Product Management`.
   - `basic_profile.normalized_title.department` uses "&" forms: `Sales & Revenue`, `Engineering & Technology`, `Marketing`, `People & HR`, `Finance & Accounting`, `Operations & Logistics`, `Product & Design`, `Customer Service & Support`, `Legal & Compliance`, `Data & Analytics`, `Executive Leadership`.
   - `openToCards`: `CAREER_INTEREST`, `HIRING_MANAGER`, `VOLUNTEERING`. Labels like "Open to Work" match zero.
4. **Titles are the main lever.** `currentJobTitles` is an OR of all-words contains matches on the current title, so keep phrases short ("VP Sales" also matches "Co-Founder and VP of Sales"). Title matching is approximate. Don't use it to claim exact seniority or buying authority.
5. **Named employers.** `companyNames` is exact and case-sensitive on the canonical name ("Kris@Work" is stored as "KrisAtWork"). `companyDomains` matches only the employer's **primary** domain, and an alias domain returns zero. Resolve the company with `crustdata_identify_company` first, then filter by the returned `companyIds`, primary domain, or name. Never AND a guessed name with a guessed domain, and never guess sibling TLDs.
6. **The person index has no employer revenue, funding, valuation, or technologies.** For those, run `crustdata_search_companies` first and feed the resulting ids into `companyIds`.
7. **Headcount** uses numeric `minHeadcount` / `maxHeadcount`, not range buckets.
8. **Recency.** For new-in-role intent, use `currentRoleStartDateFrom` (YYYY-MM-DD, computed from today's date). `recentlyChangedJobs` only means a past role ended within about 90 days. It is not proof that a new role started, and it never narrows a search on its own.
9. **Exclusions never narrow on their own.** Pair them with at least one positive filter, or the search won't run. On person search, free-text columns such as `current.title` support `(!)`. Industry columns use `not_in`, and only with exact taxonomy labels you're certain of. A guessed label excludes nothing.
10. **Always set `sorts` explicitly** (`[{field, type}]`) on a sortable field that matches the ranking you want. Without a stated ranking, prefer `experience.employment_details.company_headcount_latest` desc.
11. **Read `warnings` and `effective_filters`** in every search result. A dropped filter means the search was broader than intended, so fix it and rerun instead of trusting the rows.
12. **Zero results.** Before broadening, separate a provider error, wrong vocabulary, and a true zero. Validate field names and canonical values first. Broaden only optional criteria, and say what you changed.

## Raw `filters` (in the people plan)

Top-level entries are ANDed with the friendly fields. A condition is `{field, type, value}`; a group is `{op: and|or|all_of, conditions: [...]}`.

- Use only fields from the catalog below, with operators from the field's operator set. "Contains" means `(.)` (all words, typo-tolerant); `[.]` is an exact phrase.
- `has_all` and `all_of` work only on fields that have a nested array path (`experience.employment_details.*`, `education.schools.*`). Inside `all_of`, every child must target the same nested array: different elements can satisfy different children, whereas `and` requires one element to satisfy all of them.
- Null operators need `value: null`.
- Geo radius works only on `professional_network.location.raw` with `{location: "Bengaluru, India", distance: 25, unit: "km"}` (or `lat_lng: [lat, lng]`).
- "filterOnly" fields can narrow a search, but their values are not returned. Never claim them as observed evidence.
- Past employer: `experience.employment_details.past.company_name`. All roles (current and past): `experience.employment_details.company_name` / `.title` / `.start_date` / `.end_date`. Use `all_of` over these to say "a role at X that ended after date D".
- Education lives only under `education.schools.*` (`school`, `degree`, `field_of_study`). There is no `education.degrees`.

## Examples

**"VP or Director of Sales in the US, skilled in Salesforce, who used to work at Oracle"**
```json
{"currentJobTitles": ["VP Sales", "Director of Sales"],
 "personCountries": ["United States"],
 "filters": [
   {"field": "skills.professional_network_skills", "type": "in", "value": ["Salesforce"]},
   {"field": "experience.employment_details.past.company_name", "type": "in", "value": ["Oracle"]}],
 "sorts": [{"field": "professional_network.connections", "type": "desc"}]}
```

**"Heads of demand generation at software companies, excluding agencies"**
```json
{"currentJobTitles": ["Demand Generation"],
 "companyIndustries": ["Software"],
 "filters": [{"field": "experience.employment_details.current.company_industries", "type": "not_in",
              "value": ["Advertising Services", "Marketing Services"]}]}
```

**"Engineering leaders at Bengaluru startups with 20–200 people"**
```json
{"currentJobTitles": ["Head of Engineering", "VP Engineering", "CTO", "Engineering Manager"],
 "minHeadcount": 20, "maxHeadcount": 200,
 "filters": [{"field": "professional_network.location.raw", "type": "geo_distance",
              "value": {"location": "Bengaluru, India", "distance": 30, "unit": "km"}}],
 "sorts": [{"field": "experience.employment_details.company_headcount_latest", "type": "desc"}]}
```

**"Owners at employers headquartered in Texas"**: `{"currentJobTitles": ["Owner"], "companyHeadquartersStates": ["Texas"]}`. This matches employer HQ text, not where the person lives.

**"People currently at Stripe"**: call `crustdata_identify_company(domains=["stripe.com"])` first, then `{"companyIds": [<crustdata_company_id>]}`.

## Company search (`crustdata_search_companies`)

Fields include `basic_info.name`, `basic_info.primary_domain`, `basic_info.industries`, `basic_info.company_type`, `basic_info.year_founded`, `headcount.total`, `locations.country` (ISO-3), `revenue.estimated.lower_bound_usd`, `revenue.estimated.upper_bound_usd`, `funding.total_investment_usd`, `funding.last_round_type` (lowercase with underscores, e.g. `series_a`), `funding.last_fundraise_date`, `funding.investors`, `technographics.technologies.name`, `headcount.growth_percent.{1m,3m,6m,12m}`, `taxonomy.categories`, and `taxonomy.professional_network_industry`.

Operators: `= != < =< > => in not_in (.) [.]`. There is **no** fuzzy negation; use `!=` / `not_in` with exact values. `basic_info.markets` lists stock exchanges (NASDAQ, NSE, ...), not B2B/B2C. Canonical strings are case-sensitive (`FinTech`, `SaaS`, `Salesforce`, `Software Development`).

## Person filter catalog

Operator sets: `numeric`: = != < =< > => in not_in is_null is_not_null; `numericNested`: = != < =< > => in not_in is_null is_not_null has_all; `temporal`: = != < =< > => in not_in is_null is_not_null; `temporalNested`: = != < =< > => in not_in is_null is_not_null has_all; `text`: = != in not_in is_null is_not_null (.) (!) [.]; `textNested`: = != in not_in is_null is_not_null has_all (.) (!) [.]; `textArray`: = != in not_in is_null is_not_null (.) (!) [.]; `textArrayNested`: = != in not_in is_null is_not_null has_all (.) (!) [.]; `boolean`: = != in not_in is_null is_not_null; `booleanNested`: = != in not_in is_null is_not_null has_all; `personLocation`: = != in not_in is_null is_not_null (.) (!) [.] geo_distance geo_exclude

| field | type | ops | notes |
|---|---|---|---|
| `crustdata_person_id` | integer | numeric | Crustdata person ID; sortable |
| `metadata.updated_at` | datetime | temporal | Last profile update timestamp; sortable |
| `metadata.last_scraped_source` | string | text | Last profile refresh source |
| `basic_profile.name` | string | text | Full name; sortable |
| `basic_profile.first_name` | string | text | First name |
| `basic_profile.last_name` | string | text | Last name |
| `basic_profile.headline` | string | text | Profile headline |
| `basic_profile.summary` | string | text | Profile summary / about; filterOnly |
| `basic_profile.languages` | string[] | textArray | Spoken languages |
| `basic_profile.last_updated` | datetime | temporal | Last update timestamp on the basic profile |
| `basic_profile.location` | string | text | Location summary; sortable |
| `basic_profile.location.full_location` | string | text | Full location string; sortable |
| `basic_profile.location.city` | string | text | City; sortable; prefer plan field personCities |
| `basic_profile.location.state` | string | text | State / region as a full name; sortable; prefer plan field personStates |
| `basic_profile.location.country` | string | text | Country as a full name; sortable; full country name; prefer plan field personCountries |
| `basic_profile.location.continent` | string | text | Continent as a full name |
| `basic_profile.normalized_title.department` | string | text | Job Title Normalization (beta) — high-level department. |
| `basic_profile.normalized_title.sub_department` | string | text | Job Title Normalization (beta) — sub-department / category. |
| `basic_profile.normalized_title.matched_title` | string | text | Job Title Normalization (beta) — standardized canonical title. |
| `basic_profile.professional_network_name` | string | text | Display name on the professional-network profile |
| `professional_network.location.raw` | string | personLocation | Raw location string from profile; geo |
| `professional_network.location` | string | text | Network location summary |
| `professional_network.location.city` | string | text | Network location city |
| `professional_network.location.state` | string | text | Network location state / region |
| `professional_network.location.country` | string | text | Network location country |
| `professional_network.location.continent` | string | text | Network location continent |
| `professional_network.connections` | integer | numeric | Connection count; sortable; prefer plan field minConnections |
| `professional_network.followers` | integer | numeric | Follower count (requires API key access); sortable; prefer plan field minFollowers |
| `professional_network.open_to_cards` | string[] | textArray | Open-to signal codes. See Open-to signal values Use only the documented uppercase enum values.; values: CAREER_INTEREST, HIRING_MANAGER, VOLUNTEERING; prefer plan field openToCards/activelyHiring |
| `professional_network.metadata.last_scraped_source` | string | text | Last profile refresh source |
| `skills.professional_network_skills` | string[] | textArray | Listed skills; filterOnly |
| `experience.employment_details.company_name` | string | textNested | Company name across all roles |
| `experience.employment_details.title` | string | textNested | Job title across all roles |
| `experience.employment_details.description` | string | textNested | Role description across all roles |
| `experience.employment_details.seniority_level` | string | textNested | Seniority level across all roles |
| `experience.employment_details.function_category` | string | textNested | Function category across all roles |
| `experience.employment_details.start_date` | date | temporalNested | Role start date across all roles; sortable |
| `experience.employment_details.end_date` | date | temporalNested | Role end date across all roles |
| `experience.employment_details.location` | string | textNested | Role location across all roles |
| `experience.employment_details.company_id` | integer | numericNested | Company ID across all roles; sortable |
| `experience.employment_details.professional_network_id` | string | textNested | Employer profile ID across all roles |
| `experience.employment_details.company_website_domain` | string | textNested | Employer website domain; bare domain without scheme |
| `experience.employment_details.company_headcount_latest` | integer | numericNested | Employer latest headcount; sortable |
| `experience.employment_details.company_industries` | string[] | textArrayNested | Employer industries |
| `experience.employment_details.company_professional_network_industry` | string | textNested | Employer primary industry label |
| `experience.employment_details.company_type` | string | textNested | Employer company type |
| `experience.employment_details.company_headquarters_country` | string | textNested | Employer HQ country as ISO-3 code; ISO 3166-1 alpha-3 country code |
| `experience.employment_details.company_hq_location` | string | textNested | Employer HQ location string |
| `experience.employment_details.company_website` | string | textNested | Employer website across all roles — exact match against the stored full URL (scheme and any query string included); prefer company_website_domain |
| `experience.employment_details.employment_type` | string | textNested | Employment type across all roles |
| `experience.employment_details.years_at_company_raw` | number | numericNested | Whole years in the role, floored. Counts from the role's start date, so a promotion starts it over. For precise tenure, filter start_date instead; sortable |
| `experience.employment_details.business_email_verified` | boolean | booleanNested | Verified business email across all roles |
| `experience.employment_details.current.company_name` | string | textNested | Current company name (filter alias of current.name); prefer plan field companyNames |
| `experience.employment_details.current.title` | string | textNested | Current job title; prefer plan field currentJobTitles |
| `experience.employment_details.current.description` | string | textNested | Current role description |
| `experience.employment_details.current.seniority_level` | string | textNested | Current seniority level; prefer plan field seniorityLevels |
| `experience.employment_details.current.function_category` | string | textNested | Current function category; prefer plan field functionCategories |
| `experience.employment_details.current.start_date` | date | temporalNested | Current role start date; prefer plan field currentRoleStartDateFrom/currentRoleStartDateTo |
| `experience.employment_details.current.name` | string | textNested | Current company name (returned response field) |
| `experience.employment_details.current.years_at_company_raw` | number | numericNested | Years at current company; prefer plan field minYearsAtCurrentCompany/maxYearsAtCurrentCompany |
| `experience.employment_details.current.company_headquarters_country` | string | textNested | Current employer HQ country. Java expands in/not_in and =/!= to ISO-3 plus full-name aliases for new searches; existing cursors retain their original filters.; ISO-3 country code or full country name; prefer plan field companyHeadquartersCountries |
| `experience.employment_details.current.company_id` | integer | numericNested | Current employer company ID (filter alias of current.crustdata_company_id) — the response returns the id under current.crustdata_company_id, not company_id |
| `experience.employment_details.current.professional_network_id` | string | textNested | Current employer profile ID. Returned under the same name on each role, so this one is not an alias. |
| `experience.employment_details.current.position_id` | string | textNested | Per-role identifier for the current position (one per role, distinct from company ID) |
| `experience.employment_details.current.company_industries` | string[] | textArrayNested | Current employer industries; prefer plan field companyIndustryCodes |
| `experience.employment_details.current.company_type` | string | textNested | Current employer company type |
| `experience.employment_details.current.company_headcount_latest` | integer | numericNested | Current employer latest headcount |
| `experience.employment_details.current.company_hq_location` | string | textNested | Current employer HQ location string; use companyHeadquartersStates for approximate state/region matching. |
| `experience.employment_details.current.company_website_domain` | string | textNested | Current employer website domain (filter alias of current.company_website) — filter with a bare domain like "stripe.com"; the response returns the full URL under current.company_website; bare domain without scheme; prefer plan field companyDomains |
| `experience.employment_details.current.company_professional_network_industry` | string | textNested | Current employer primary industry label |
| `experience.employment_details.current.company_professional_network_profile_url` | string | textNested | Current employer profile URL. Exact full URL — see Find people at a company |
| `experience.employment_details.current.company_linkedin_profile_url` | string | textNested | Current employer profile URL (accepted alias) |
| `experience.employment_details.current.employment_type` | string | textNested | Current employment type |
| `experience.employment_details.current.business_email_verified` | boolean | booleanNested | Verified business email on current role |
| `experience.employment_details.past.company_name` | string | textNested | Past company name (filter alias of past.name) |
| `experience.employment_details.past.title` | string | textNested | Past job title |
| `experience.employment_details.past.description` | string | textNested | Past role description |
| `experience.employment_details.past.seniority_level` | string | textNested | Past seniority level |
| `experience.employment_details.past.function_category` | string | textNested | Past function category |
| `experience.employment_details.past.start_date` | date | temporalNested | Past role start date |
| `experience.employment_details.past.name` | string | textNested | Past company name (returned response field) |
| `experience.employment_details.past.years_at_company_raw` | number | numericNested | Years at past company |
| `experience.employment_details.past.company_headquarters_country` | string | textNested | Past employer HQ country as ISO-3 code; ISO 3166-1 alpha-3 country code |
| `experience.employment_details.past.company_id` | integer | numericNested | Past employer company ID (filter alias of past.crustdata_company_id) — the response returns the id under past.crustdata_company_id, not company_id |
| `experience.employment_details.past.professional_network_id` | string | textNested | Past employer profile ID. Returned under the same name on each role, so this one is not an alias. |
| `experience.employment_details.past.position_id` | string | textNested | Per-role identifier for the past position (one per role, distinct from company ID) |
| `experience.employment_details.past.company_industries` | string[] | textArrayNested | Past employer industries |
| `experience.employment_details.past.company_type` | string | textNested | Past employer company type |
| `experience.employment_details.past.company_headcount_latest` | integer | numericNested | Past employer latest headcount |
| `experience.employment_details.past.company_hq_location` | string | textNested | Past employer HQ location string |
| `experience.employment_details.past.company_website_domain` | string | textNested | Past employer website domain (filter alias of past.company_website) — filter with a bare domain like "stripe.com"; the response returns the full URL under past.company_website; bare domain without scheme |
| `experience.employment_details.past.company_professional_network_industry` | string | textNested | Past employer primary industry label |
| `experience.employment_details.past.company_professional_network_profile_url` | string | textNested | Past employer profile URL. Exact full URL — see Find people at a company |
| `experience.employment_details.past.company_linkedin_profile_url` | string | textNested | Past employer profile URL (accepted alias) |
| `experience.employment_details.past.employment_type` | string | textNested | Past employment type |
| `experience.employment_details.past.business_email_verified` | boolean | booleanNested | Verified business email on past role |
| `education.schools.school` | string | textNested | School name |
| `education.schools.degree` | string | textNested | Degree |
| `education.schools.field_of_study` | string | textNested | Field of study |
| `education.schools.location` | string | textNested | School location summary |
| `education.schools.location.city` | string | textNested | School location city |
| `education.schools.location.state` | string | textNested | School location state / region |
| `education.schools.location.country` | string | textNested | School location country |
| `education.schools.location.continent` | string | textNested | School location continent |
| `education.schools.location.full_location` | string | textNested | School full location string |
| `certifications.name` | string | textNested | Certification name; filterOnly |
| `certifications.issuing_organization` | string | textNested | Certification issuer; filterOnly |
| `certifications.issue_date` | date | temporalNested | Certification issue date; filterOnly |
| `certifications.expiration_date` | date | temporalNested | Certification expiration date; filterOnly |
| `certifications.credential_id` | string | textNested | Certification credential ID; filterOnly |
| `certifications.credential_url` | string | textNested | Certification credential URL; filterOnly |
| `honors.title` | string | textNested | Honor or award title; filterOnly |
| `social_handles.twitter_handle` | string | text | Twitter/X handle |
| `dev_platform_profiles.name` | string | text | Name on the GitHub profile; filterOnly |
| `dev_platform_profiles.bio` | string | text | Profile bio; filterOnly |
| `dev_platform_profiles.location` | string | text | Self-reported location; filterOnly |
| `dev_platform_profiles.website_url` | string | text | Blog / website URL; filterOnly |
| `dev_platform_profiles.company_text` | string | text | Company text on the profile; filterOnly |
| `dev_platform_profiles.is_hireable` | boolean | boolean | GitHub "available for hire" flag; filterOnly |
| `dev_platform_profiles.followers` | number | numeric | Follower count; sortable; filterOnly |
| `dev_platform_profiles.following` | number | numeric | Following count; sortable; filterOnly |
| `dev_platform_profiles.public_repo_count` | number | numeric | Public repositories owned; sortable; filterOnly |
| `dev_platform_profiles.metadata.created_at` | date | temporal | Account creation date; sortable; filterOnly |
| `dev_platform_profiles.total_repos` | number | numeric | Owned repositories tracked; sortable; filterOnly |
| `dev_platform_profiles.total_stars` | number | numeric | Stars across all owned repositories; sortable; filterOnly |
| `dev_platform_profiles.max_stars` | number | numeric | Stars on the most-starred repository; sortable; filterOnly |
| `dev_platform_profiles.median_stars` | number | numeric | Median stars across owned repositories; sortable; filterOnly |
| `dev_platform_profiles.all_languages` | string[] | textArray | Primary languages across all owned repositories; filterOnly |
| `dev_platform_profiles.all_topics` | string[] | textArray | Topic tags across all owned repositories; filterOnly |
| `dev_platform_profiles.repos.full_name` | string | text | owner/repo slug; filterOnly |
| `dev_platform_profiles.repos.owner` | string | text | Owning account login; filterOnly |
| `dev_platform_profiles.repos.description` | string | text | Repository description; filterOnly |
| `dev_platform_profiles.repos.primary_language` | string | text | Primary language of the repository; filterOnly |
| `dev_platform_profiles.repos.topics` | string[] | textArray | Topic tags; filterOnly |
| `dev_platform_profiles.repos.license_key` | string | text | License key (for example mit); filterOnly |
| `dev_platform_profiles.repos.is_fork` | boolean | boolean | Whether the repository is a fork; filterOnly |
| `dev_platform_profiles.repos.parent` | string | text | Parent repository slug (if a fork); filterOnly |
| `dev_platform_profiles.repos.archived` | boolean | boolean | Archived flag; filterOnly |
| `dev_platform_profiles.repos.disabled` | boolean | boolean | Disabled flag; filterOnly |
| `dev_platform_profiles.repos.is_template` | boolean | boolean | Template repository flag; filterOnly |
| `dev_platform_profiles.repos.has_issues` | boolean | boolean | Issues enabled; filterOnly |
| `dev_platform_profiles.repos.has_projects` | boolean | boolean | Projects enabled; filterOnly |
| `dev_platform_profiles.repos.has_wiki` | boolean | boolean | Wiki enabled; filterOnly |
| `dev_platform_profiles.repos.stars` | number | numeric | Star count; filterOnly |
| `dev_platform_profiles.repos.forks_count` | number | numeric | Fork count; filterOnly |
| `dev_platform_profiles.repos.open_issues_count` | number | numeric | Open issue count; filterOnly |
| `dev_platform_profiles.repos.size` | number | numeric | Repository size (KB); filterOnly |
| `dev_platform_profiles.repos.github_created_at` | date | temporal | Repository creation date; filterOnly |
| `dev_platform_profiles.repos.github_updated_at` | date | temporal | Last metadata update; filterOnly |
| `dev_platform_profiles.repos.github_pushed_at` | date | temporal | Last code push; filterOnly |
| `recently_changed_jobs` | boolean | boolean | Past role ended within 90 days of the last index rebuild; this does not mean a new role started. Use current.start_date for recent hires.; sortable; filterOnly; prefer plan field recentlyChangedJobs |
| `years_of_experience_raw` | number | numeric | Total years of experience (precise); sortable; prefer plan field minYearsOfExperience/maxYearsOfExperience |
| `years_of_experience` | number | numeric | Total years of experience (rounded) |
