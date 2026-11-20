"""Global source registry seed.

connector_status is honest:
- live              → a working connector exists and runs without credentials
- credential_gated  → connector exists but needs API credentials/approval
- manual            → owner-driven import (URL or document upload)
- planned           → listed for coverage; NO connector exists yet (never presented as live)
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source

S = dict[str, Any]


def _src(key, name, category, access, status, *, base_url=None, connector=None, country=None, region=None,
         auth=None, terms=None, freq=None, rate=30, max_items=50, enabled=False, coverage=None, config=None) -> S:
    return dict(
        key=key, name=name, category=category, access_method=access, connector_status=status, base_url=base_url,
        connector=connector, country=country, region=region, api_auth_requirements=auth, terms_notes=terms,
        collection_frequency_minutes=freq, rate_limit_per_minute=rate, max_items_per_run=max_items, enabled=enabled,
        coverage=coverage, config=config or {},
    )


SEED_SOURCES: list[S] = [
    # --- Live ---------------------------------------------------------------------------------
    _src("hackernews", "Hacker News (Seeking Freelancer thread + keyword search)", "public_project_community", "api", "live",
         base_url="https://news.ycombinator.com", connector="hackernews", region="Global",
         auth="None. Official Firebase API + HN Search (Algolia) API.",
         terms="Public read-only APIs. Collects buyer posts only: SEEKING FREELANCER requests, contract/freelance roles, keyword matches. SEEKING WORK / job-seeker posts are skipped.",
         freq=720, rate=120, max_items=60, enabled=True,
         coverage="Monthly Seeking-freelancer thread (buyers only), contract/freelance roles in Who-is-hiring, and keyword matches (last 30 days, incremental).",
         config={"freelancer_thread": True, "hiring_contracts": True, "keyword_search": True, "hits_per_term": 10, "lookback_days": 30}),
    _src("rss_custom", "Custom RSS/Atom feed (configure feed_url)", "public_project_community", "rss", "live",
         connector="rss", auth="None", terms="Only add feeds you are permitted to consume; robots.txt is respected.",
         freq=360, rate=20, max_items=50, enabled=False,
         coverage="Any permitted RSS/Atom feed. Set config.feed_url and enable.",
         config={"feed_url": None, "require_term_match": True}),
    _src("n8n_jobs", "n8n community — Jobs category (RSS)", "online_community", "rss", "live",
         base_url="https://community.n8n.io/c/jobs/13", connector="rss", region="Global",
         auth="None", terms="Public Discourse RSS; robots.txt allows. Read-only, low rate.",
         freq=720, rate=10, max_items=30, enabled=True,
         coverage="[HIRING] posts for n8n / workflow-automation freelancers.",
         config={"feed_url": "https://community.n8n.io/c/jobs/13.rss", "require_term_match": False}),
    _src("make_hire_a_pro", "Make community — Hire a Pro (RSS)", "online_community", "rss", "live",
         base_url="https://community.make.com/c/hire-a-pro/50", connector="rss", region="Global",
         auth="None", terms="Public Discourse RSS; robots.txt allows. '[For hire]' seller posts are rejected by the classifier.",
         freq=720, rate=10, max_items=30, enabled=True,
         coverage="Requests for Make.com / automation builders (mixed with seller posts).",
         config={"feed_url": "https://community.make.com/c/hire-a-pro/50.rss", "require_term_match": False,
                 "title_must_match": r"\b(need|needed|looking for|hiring|wanted|seeking|require[sd]?|help (with|needed))\b"}),
    # --- Manual --------------------------------------------------------------------------------
    _src("manual_url", "Manual URL import", "manual", "manual", "manual", connector=None, enabled=True,
         terms="Owner-submitted public URLs; robots.txt respected, SSRF-protected.", coverage="Any public page the owner submits."),
    _src("partner_programmes", "Researched vendor / partner programmes", "vendor_partner", "manual", "manual", enabled=True,
         terms="Official programme pages researched by hand; facts dated, re-check before applying.",
         coverage="ERP/CRM/automation/cloud/payments partner programmes (scripts/seed_partner_programmes.py)."),
    _src("procurement_documents", "Procurement document import (PDF/DOCX)", "government_procurement", "document", "manual",
         enabled=True, terms="Owner-uploaded tender/RFP documents downloaded manually from portals.",
         coverage="Tender documents from TN e-Procurement, CPPP, GeM, PSUs or private RFPs, uploaded manually."),
    # --- Credential-gated ----------------------------------------------------------------------
    _src("reddit", "Reddit (official API)", "online_community", "api", "credential_gated", base_url="https://oauth.reddit.com",
         connector="reddit", region="Global",
         auth="Reddit app client id/secret + user agent (IOI_REDDIT_*). Review Reddit Data API terms; commercial use may need approval.",
         terms="Official OAuth API only. No HTML scraping, no private data.", freq=720, rate=60, max_items=50,
         coverage="Public subreddit listings, e.g. r/forhire posts tagged [Hiring].",
         config={"subreddits": ["forhire"], "title_must_match": r"\[hiring\]"}),
    _src("discord", "Authorised public Discord channels", "online_community", "api", "planned",
         auth="Discord bot token with explicit server-owner authorisation.",
         terms="Only approved bot access to channels the bot is authorised for. Never scrape private channels, messages or member lists.",
         coverage="Not implemented."),
    # --- Planned: project communities -------------------------------------------------------
    _src("indie_hackers", "Indie Hackers", "public_project_community", "web", "planned", base_url="https://www.indiehackers.com",
         terms="Check terms/robots before implementing; no official public API known.", coverage="Not implemented. Use Manual URL import."),
    _src("product_hunt", "Product Hunt", "online_community", "api", "planned", base_url="https://www.producthunt.com",
         auth="Product Hunt API token", terms="API terms restrict commercial use; review before enabling.", coverage="Not implemented."),
            # --- Planned: government procurement -------------------------------------------------------
    _src("tn_eprocurement", "Tamil Nadu e-Procurement", "government_procurement", "web", "planned", base_url="https://tntenders.gov.in",
         country="India", region="Tamil Nadu", terms="Portal uses CAPTCHA; no automated bypass. Download documents manually and import.",
         coverage="Manual: use Procurement document import."),
    _src("cppp", "Central Public Procurement Portal (CPPP)", "government_procurement", "web", "planned", base_url="https://eprocure.gov.in",
         country="India", terms="CAPTCHA-protected search; no bypass. Manual document import.", coverage="Manual: use Procurement document import."),
    _src("gem", "Government e-Marketplace (GeM) — public bid listing", "government_procurement", "web", "live",
         base_url="https://bidplus.gem.gov.in/all-bids", connector="gem", country="India",
         auth="None to read the public listing. Seller registration on GeM is required to BID (owner does this; IOI never bids or registers).",
         terms="Public all-bids listing (no login, no CAPTCHA; robots.txt allows). Read-only, low rate, bounded pages and document downloads. "
               "Only service bids matching approved services are kept; goods/licences/hardware and reverse auctions are skipped.",
         freq=720, rate=12, max_items=40, enabled=False,
         coverage="Ongoing GeM bids for software development, web/portal, API, automation, ERP/MIS and IT-project services; bid PDF parsed for deadline, buyer, turnover/experience, MSE/startup relaxation, EMD.",
         config={"search_terms": None, "pages_per_term": 2, "fetch_documents": True, "max_documents": 25, "skip_reverse_auctions": True}),
    _src("gepnic", "Government ePublishing (GePNIC)", "government_procurement", "web", "planned", country="India",
         terms="Manual import only.", coverage="Manual."),
    _src("psu_procurement", "PSU procurement pages", "government_procurement", "web", "planned", country="India",
         terms="Per-PSU terms; manual import.", coverage="Manual."),
    _src("intl_procurement", "International public procurement portals", "government_procurement", "api", "planned",
         terms="Only where access is permitted (e.g. official open-data APIs).", coverage="Not implemented."),
    # --- Planned: vendor & partner sources ----------------------------------------------------
    _src("vendor_portals", "Official vendor registration portals", "vendor_partner", "manual", "planned",
         terms="Owner reviews; V1 never registers automatically.", coverage="Use Manual URL import for specific portals."),
    _src("si_partner_programmes", "System integrator / ERP / CRM partner programmes", "vendor_partner", "manual", "planned",
         terms="Official partner directories; respect terms.", coverage="Use Manual URL import."),
    _src("corporate_procurement", "Corporate procurement pages", "vendor_partner", "manual", "planned", coverage="Use Manual URL import."),
    # --- Planned: business sources ------------------------------------------------------------
    _src("company_websites", "Official company websites", "business_directory", "web", "manual",
         terms="Visited only during selective research, robots.txt respected.", enabled=True, coverage="Used by the research workflow."),
    _src("industry_directories", "Industry / manufacturer / exhibitor directories, chambers of commerce, industrial estates",
         "business_directory", "web", "planned", country="India",
         terms="Only permitted listings/APIs. Directory presence alone is not demand.", coverage="Not implemented."),
    _src("linkedin", "LinkedIn", "online_community", "none", "planned",
         terms="Not automated — platform restrictions are not bypassed. Owner may paste public URLs manually.", coverage="Not implemented by design."),
    _src("freelance_marketplaces", "Freelance marketplaces (Upwork etc.)", "online_community", "none", "planned",
         terms="Not automated — platform restrictions are not bypassed.", coverage="Not implemented by design."),
]


# Sources that gained a connector after first release: rows still in their original "no connector"
# state are upgraded once. Rows the owner has already wired to a connector are left alone.
UPGRADE_WHEN_NO_CONNECTOR = {"gem"}


def seed_sources(db: Session) -> int:
    """Insert missing seed sources. Existing rows (and owner edits) are left untouched,
    except one-time upgrades of planned sources that now have a connector."""
    existing = {src.key: src for src in db.scalars(select(Source)).all()}
    n = 0
    for s in SEED_SOURCES:
        row = existing.get(s["key"])
        if row is None:
            db.add(Source(**s))
            n += 1
        elif s["key"] in UPGRADE_WHEN_NO_CONNECTOR and not row.connector and s.get("connector"):
            for k, v in s.items():
                if k not in ("key", "enabled"):
                    setattr(row, k, v)
    db.commit()
    return n
