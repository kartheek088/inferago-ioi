# Social Commerce Intelligence

_Added 2026-11-23 · branch `feature/social-commerce-intelligence` · migration `0013_social_commerce`_

A second, independent discovery pipeline for Chennai businesses that sell through Instagram, Facebook
and WhatsApp Business. It does not change the B2B equipment-service / wholesale-distribution pipeline.

---

## 1. Why it is a separate channel

A one-person boutique or home baker is not a small version of a B2B distributor:

| | B2B channel | Social commerce channel |
|---|---|---|
| Found via | Overture directory, news | A profile link, an authorised list, a public market page, web search |
| No website | Needs explaining | Completely normal |
| No registered entity | Unusual | Completely normal |
| Qualification | P0–P3 | S0–S3 |
| Address proof | Official site or owner | Profile location, delivery area, pickup point, event listing, registration |
| Decision maker | Service/ops manager | The owner, who is usually the only person |
| First offer | ServiceFlow / OrderFlow / integration | A shareable order form, or configuring what they already pay for |

So the two pipelines have their own campaign row, their own discovery jobs, their own category rules,
geography rules, qualification engine and research agent.

**What they share, deliberately:** company identity, public contacts, evidence, outreach approval, the
11-stage sales pipeline, proposals and payments. An approved social seller becomes a deal in exactly the
same tables as a B2B company, so there is one place to see money.

Every shared row carries `channel` = `b2b` | `social_commerce` (`ioi_companies`, `ioi_campaigns`,
`ioi_jobs`). `core.evaluate()` is the single choke point that routes a company to its channel's engine,
so ingestion, research, the agent and sales all stay channel-agnostic.

---

## 2. What it will and will not do

### Will
- Read the seller's **own** website and any catalogue/order-form page they published.
- Read public Chennai market / exhibitor pages the owner authorises.
- Read public business-news feeds for seller features.
- Search the public web through an **authorised search API**, if one is configured.
- Accept a pasted profile link, an `@handle`, a WhatsApp business number, a catalogue link or a CSV.
- Store what the **owner** saw after opening a profile themselves.

### Will not — by design, not by omission
- Fetch an Instagram or Facebook profile page. They are served only to signed-in clients and their
  robots.txt restricts automated access. There is **no code path** that fetches those domains: the agent
  refuses them *by name*, so a prompt injection telling it to "open their Instagram" cannot work.
- Open a DM, a WhatsApp chat, a group, a group's members or a follower list.
- Use a Meta API. No app, business account or approved permissions exist, so `meta_api` is seeded as
  `needs_setup` and says so in the UI.
- Scrape a search engine's result pages instead of using its API.
- Send anything. Nothing is messaged, posted or called automatically, ever.

A **public WhatsApp number is a contact route, not permission for bulk messaging.** The outreach notice
says so on every seller.

---

## 3. Sources and their honest status

| Key | What it is | Status without setup |
|---|---|---|
| `manual_profile` | Paste a public profile / catalogue / website link | **working** — always |
| `csv_import` | An authorised list you were given | **working** — always |
| `public_search` | Brave Search or Google Programmable Search API | **needs_setup** — says exactly which env vars are missing |
| `market_listings` | Public Chennai market / exhibitor pages you add | **needs_setup** until you add page links |
| `business_features` | Public Chennai business-news RSS | untested until a real run |
| `meta_api` | Instagram / Facebook Graph API | **needs_setup**, with the reason spelled out |

To enable web search, set in `.env`:

```
IOI_SEARCH_PROVIDER=brave          # or google_cse
IOI_SEARCH_API_KEY=...
IOI_SEARCH_CX=...                  # google_cse only
```

Both providers have a free tier. With neither set, discovery still runs — it researches and re-qualifies
the sellers you already added, and the UI says why no new ones can be found automatically.

---

## 4. Geography: how a seller with no shop is placed in Chennai

A social seller often has no storefront, so an address is not the only acceptable evidence. What counts
depends on the **basis** of the evidence, never on how often "Chennai" appears.

| Strength | Bases | Effect |
|---|---|---|
| strong | location in their own business profile, address on their own website, public business registration, owner confirmed | **verified_chennai** on its own |
| medium | published delivery/service area, listed pickup point, public market/exhibitor listing, published business feature | **probable_chennai** alone; **verified_chennai** when two *different* medium bases agree |
| weak | a Chennai hashtag, Tamil-language captions, a Chennai follower, a customer's comment | **never** raises confidence — recorded, shown, and ignored |

Outcomes: `verified_chennai` · `probable_chennai` · `unclear` · `outside_chennai`.
Only **verified** sellers can pass the location gate, so only they reach the outreach queue. An
out-of-city address stated by the business itself (including metro-area localities outside the
corporation limit, e.g. Tambaram) excludes the seller.

---

## 5. Categories, complexity and activity

**Categories** (§6 of the brief): `fashion_boutique`, `custom_gifts`, `home_bakery`,
`meal_subscription`, `other_social`. Decided from the seller's own words. A business that matches none —
an industrial supplier, say — is not collected by an automated source; the owner can still add it by hand.

**Order complexity** — nine indicators (variants, made-to-order, advance payment, deadlines, recurring
orders, delivery, stated volume, returns, multi-channel orders). Each keeps the exact words that
triggered it. These say a workflow tool **might** be relevant. They are not proof of a problem, and the
UI repeats that wherever they appear.

**Activity vs demand** are kept apart:
- `activity` — product launches, restocks, pre-orders opening, campaigns, expansion. Evidence the
  account is being used.
- `demand_indicator` — "sold out", dispatch posts, repeat customers, testimonials, enquiry volume, and
  explicit complaints about managing orders. Evidence of what the seller *says* about demand.

Neither is evidence of sales, order volume, revenue or budget. **Follower counts are recorded when a
profile states them and are never an input to anything** — there is no follower field in the snapshot
the score is computed from, and a test asserts that.

---

## 6. Qualification (S0–S3)

Six mandatory gates, each `True` / `False` / `None` (unverified — never "pass"):

1. Credible Chennai operations
2. Relevant social-commerce category
3. Current commercial activity
4. Relevant operational complexity (or a problem the seller confirmed)
5. Legitimate public contact route
6. Practical service fit

| | Meaning |
|---|---|
| **S0** | Every gate passes **and** the seller asked for help (a public request a human confirmed) or confirmed a problem to you. |
| **S1** | Every gate passes and there is dated activity in the last 180 days. They have **not** asked for help. |
| **S2** | Relevant, but a gate is still unverified, or there is no recent activity. |
| **S3** | A gate failed, or it is a duplicate or rejected. |

**A keyword match never reaches S0.** A post that looks like "I can't keep track of my orders" is stored
as a hypothesis; a person opens it and confirms or rejects it. No score can bypass a gate — a seller with
a confirmed problem but an out-of-Chennai address is still S3.

**Score, /100** — ranks within a category only, never a chance of winning the work:
confirmed need 30 · order complexity 25 · public activity 15 · contact accessibility 10 ·
implementation simplicity 10 · source quality 10.

**Maturity** is an operational description from public evidence, not a financial one:
`growing_operational`, `established_social`, `early_stage`, `activity_unclear`, `inactive_unverified`.

---

## 7. Offers — cheapest effective option first

1. Improve the process they already have (no software).
2. Configure software they already pay for.
3. A shareable order form / light tracker.
4. Connect what they already use.
5. Build a small custom module.

The four named offers are **Social OrderFlow Lite** (fashion), **Custom OrderFlow** (gifts),
**Pre-Order and Delivery Tracker** (bakery) and **Subscription OrderFlow** (meals). But:

- A seller already using Dukaan, Shopify, Zoho, Vyapar etc. gets "set up what they already have" first.
- A seller with one complexity indicator gets a **free Google Form**, because a paid build would not be
  honest yet.
- A seller with working online checkout is never told to replace it — the offer covers only the
  made-to-order work it cannot handle. Inferago never asks for a domain transfer for a workflow project.
- **No Instagram/WhatsApp integration is ever promised.** Every offer carries a note that this needs
  approved Meta API access, arranged per business.

---

## 8. The research agent

Read-only, typed tools, hard budgets, full audit trail in `ioi_agent_events`.

Tools: `retrieve_cached_evidence`, `list_readable_pages`, `fetch_seller_page`,
`find_public_business_contacts`, `record_fact`, `record_order_complexity`,
`record_location_evidence`, `finish`.

Caps per seller: **6 AI calls · 14 tool calls · 6 pages · 40k tokens · 150 s · $0.03 · 3 consecutive
failures.**

Security properties, each covered by a test:

- `fetch_seller_page` allows **only the seller's own domains**. Instagram, Facebook, WhatsApp, LinkedIn,
  JustDial, IndiaMART, X are refused by name and cannot be allow-listed.
- A page that tells the agent to fetch cloud metadata (`169.254.169.254`) is ignored; the request is
  never made.
- A fabricated quote is rejected — a fact is kept only if its quote is found verbatim on a page fetched
  in that session.
- Weak location evidence (a hashtag) is refused even when the agent asks to record it.
- No shell, exec, filesystem, write or send tool exists.
- Loops stop at the caps; without AI configured the outcome is `unavailable` and rule-based research
  still runs.

---

## 9. The UI

Sidebar (8 items; **Social Commerce is top-level**, not nested under Discover, Prospects or Settings):

Home · B2B Discovery · B2B Prospects · **Social Commerce** · Research Intelligence · Outreach ·
Sales Pipeline · Settings

Routes: `/social-commerce` (dashboard) · `/discover` · `/leads` · `/leads/:id` · `/activity`.

- **Dashboard** — real counts only; an honest empty state; unavailable sources listed rather than hidden.
- **Discover** — Quick / Balanced / Deep, live stage progress, counters grouped as **This run** and
  **Campaign totals** (never mixed), per-source status with errors, stop and retry.
- **Leads** — filters for platform, category, location confidence, maturity, qualification and research
  state.
- **Seller dossier** — the nine "why this lead" answers, the six gates, location with its basis and
  quote, how they sell today, order complexity, dated activity (confirm/reject per signal), the offer,
  existing software to consider first, all evidence, and the AI trace.
- **Record what you saw** — the route for Instagram and Facebook: the owner opens the profile and types
  what it says; IOI runs the same rules over their words.

Dark by default, light optional, persisted. Responsive; the phone bottom bar shows five sections.

---

## 10. Data model (migration `0013`, additive only)

New tables:
- `ioi_social_accounts` — one row per public platform account, with provenance and whether IOI may read it.
- `ioi_social_activity` — dated public signals, split by `indicator_class`.
- `ioi_social_profiles` — one row per seller: category, geography, sales setup, order channels, known
  tools, workflow gaps, complexity, maturity, research state.

New columns: `channel` on `ioi_companies`, `ioi_campaigns`, `ioi_jobs` (`server_default='b2b'`, so every
existing row is backfilled and the B2B pipeline is untouched).

Rollback: `alembic downgrade 0012_research_engine`. Verified backup before this work:
`backend/data/backups/ioi-20261123-142046-pre-social.db`.

---

## 11. What real validation found and fixed

Run on 2026-11-23 against three genuine Chennai sellers that publish their own website, found through a
public web search. Only their own sites were read; no social platform was touched.

| Seller | Result |
|---|---|
| **Prince Tailors Studio** (T Nagar) — custom bridal blouses | Worked end to end. Chennai **verified** from the address and PIN 600017 on their own site; order complexity found (made-to-order, delivery); WhatsApp recorded as the order channel; one contact they published; offer **Social OrderFlow Lite**. Correctly held at **S2** because the site carries no dated post — the open check is "current activity". |
| **For Extra Flavour Fresh Bakes** — Google Sites page | Exposed a real bug (below). Now reports honestly that the page is behind a sign-in. |
| **Cake Feast** — odoo.com page | Returns 404; classified as a permanent failure with a plain message. Correct. |

Two genuine defects, each now fixed with a regression test:

1. **A sign-in page was read as the seller's own content.** The Google Sites URL redirected an anonymous
   visitor to `accounts.google.com` and still returned HTTP 200. IOI stored that page as "the page I
   read" and even extracted a contact address off the login provider's markup as if the business had
   published it. `research.login_wall()` now detects auth hosts, sign-in paths and sign-in copy, drops
   the page, and records a permanent, plain-language error pointing the owner at
   *Record what you saw*. Tests: `test_a_sign_in_wall_is_not_read_as_the_sellers_own_page`,
   `test_login_wall_detection_rules`.
2. **The shared sales pipeline did not show social deals.** `/api/v3/pipeline` and `/api/v3/outreach`
   were scoped to the B2B campaign, so an approved seller's deal existed in the database but never
   appeared on the board — which defeats the point of sharing the pipeline. Both endpoints now span
   every channel, each row carries its `channel`, an optional `?channel=` narrows them, and
   `sales.revenue(db, None)` totals across channels. Tests:
   `test_the_sales_pipeline_is_shared_between_channels`, `test_outreach_is_shared_between_channels`.
   Found by the browser acceptance test, not by a unit test — step 11 of it exists for this reason.

A third, smaller fix: the activity gate said "2 activity signal(s)" when both signals were demand
indicators. It now names each kind separately.

---

## 12. Known limitations

- **No automatic Instagram/Facebook discovery.** This is the big one. Without Meta API access, new
  sellers come from the owner pasting links, an authorised list, public market pages, or a search API.
  The module is built so that path is pleasant rather than a fallback.
- **Public web search needs a key.** Unconfigured by default (see §3).
- **Activity dates often need a person.** A seller's own website rarely carries dates; the reliable date
  is the one the owner reads off the profile and records.
- **The same business can exist in both channels.** It is recorded as a note on the social record (and
  the B2B id is linked) rather than merged, so contact them once. A shared identity table would be the
  cleaner fix.
- **Market-page extraction is approximate.** It picks up linked profiles and `@handles` near seller
  names; a human still reviews what it found.
- **No Tamil-language interface.**
