# Sources

The registry (`backend/app/source_registry.py`, table `sources`) records for every source: name,
base URL, country/region, category, access method, API/auth requirements, permission/terms notes,
collection frequency, rate limit, last checked, last success, failure status, enabled state,
schedule state, coverage and **connector status**. Seeding never overwrites owner edits.

## Status meanings

| Status | Meaning |
|---|---|
| `live` | Working, tested connector; runs without credentials. |
| `credential_gated` | Connector exists but needs credentials/approval; disabled until configured. |
| `manual` | Owner-driven (URL import, document upload, research site visits). |
| `planned` | Listed for coverage only. **No connector.** Cannot be enabled. |

## Live

### Hacker News (`hackernews`)
- APIs: official Firebase API (`/user/whoishiring`, `/item/{id}`) to find the monthly threads;
  HN Search (Algolia) `/items/{id}` for a whole thread in one request and `/search_by_date` for keywords.
- Modes (source config):
  - `freelancer_thread` — "Ask HN: Freelancer? Seeking freelancer?" top-level comments beginning
    **SEEKING FREELANCER** (buyers). *SEEKING WORK* comments (competitors) are skipped.
  - `hiring_contracts` — "Ask HN: Who is hiring?" posts whose header says contract / contractor /
    freelance / fractional.
  - `keyword_search` — search terms from Settings, last `lookback_days` (30), incremental cursor.
    Comments in "Who wants to be hired?" / "Who is hiring?" threads are skipped here.
- Org name parsed from `Company | Role | Location` headers; website = first non-platform URL (unverified).
- Observed reality (Nov 2026): recent Seeking-Freelancer threads contained **zero** SEEKING
  FREELANCER posts; Who-is-hiring had ~14 contract/freelance roles. Volume is modest by nature.

### n8n community Jobs (`n8n_jobs`) and Make community Hire a Pro (`make_hire_a_pro`)
- Public Discourse category RSS (`/c/jobs/13.rss`, `/c/hire-a-pro/50.rss`); robots.txt allows; 10 req/min.
- Strong fit for workflow automation / integration work. Make's category mixes sellers and buyers,
  so it uses `title_must_match` (need / looking for / hiring …) and the classifier rejects
  "[For hire]", "I can help you…", unpaid and commission-only posts.
- Checked Nov 2026: n8n 23 posts → 12 opportunities; Make 25 posts → 2 buyer posts.

### Custom RSS/Atom (`rss_custom`, plus any feed added in UI)
- Set `config.feed_url` (Sources page) and enable. `require_term_match` keeps only entries that
  contain a search term; `title_must_match` (regex) keeps only matching titles. Incremental by entry timestamp. robots.txt respected.
- Good candidates (check each site's terms first): Discourse forums such as community.n8n.io
  (`/latest.rss`), company procurement news feeds, government tender RSS feeds where offered.

## Manual

- **Manual URL import** (`/api/imports/url`, Discover page): fetches one public page through the
  SSRF guard, extracts main text, runs the full pipeline.
- **Procurement document import** (`/api/imports/document`): PDF via pypdf, DOCX via python-docx.
  Extracts title, buyer, publication date, deadline, scope, budget, EMD, turnover, experience,
  GST, legal-entity, consortium, subcontracting and contact clauses with page references.
  Scanned PDFs (little text) are flagged `needs_manual_review`. Missing clauses stay empty.
  Use this for **TN e-Procurement, CPPP, GeM, GePNIC, PSU** tenders downloaded by hand.
  (Checked Nov 2026: the CPPP and tntenders.gov.in "Latest Active Tenders" listings themselves
  require a CAPTCHA, so they cannot be collected automatically without bypassing it.)
- **Official company websites**: visited only by the research workflow (homepage, one contact
  page, one vendor/partner page) within the request budget.

## Credential-gated

### Reddit (`reddit`)
1. Create an app at https://www.reddit.com/prefs/apps and review Reddit's Data API / Developer
   terms (commercial use may require Reddit's approval).
2. Set `IOI_REDDIT_CLIENT_ID`, `IOI_REDDIT_CLIENT_SECRET`, `IOI_REDDIT_USER_AGENT`
   (`platform:app-id:version (by /u/name)`), restart the backend.
3. Enable the source. Default config reads `r/forhire` posts whose title matches `[Hiring]`.
Uses app-only OAuth and public listings; no HTML scraping. The OAuth path is implemented but was
**not tested against live Reddit** (no credentials in this environment).

## Planned (no connector)

Discord (authorised bot only — never private channels/messages/member lists), Indie Hackers,
Product Hunt, TN e-Procurement / CPPP / GeM / GePNIC / PSU portals
(CAPTCHA-protected — manual document import instead), international procurement portals,
vendor portals, SI/ERP/CRM partner directories, corporate procurement pages, industry/
manufacturer/exhibitor directories, chambers of commerce. LinkedIn and freelance marketplaces are
deliberately not automated.

## Adding a connector

See `.claude/skills/add-connector/SKILL.md`. In short: implement `collect(ctx) -> Iterator[CollectedItem]`
using only `ctx.http` (SafeHttp), register in `pipeline.CONNECTORS`, add a registry entry with an
honest status, add mocked tests, update this file.
