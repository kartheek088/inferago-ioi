"""Social-commerce campaign, source registry, evidence helpers and evaluation.

`evaluate` is the single choke point: it rebuilds a seller's qualification from stored evidence and
writes it to the shared `ioi_companies` columns (so outreach, approval and the sales pipeline work
unchanged) plus the social-only columns on `ioi_social_profiles`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.ioi3.models import SOCIAL, Campaign, Company, CompanyContact, DiscoverySource, SocialAccount, SocialActivity, SocialProfile
from app.ioi3.social import categories as cat
from app.ioi3.social import geo as geomod
from app.ioi3.social import platforms as plat
from app.ioi3.social import qualify, solutions
from app.normalize import normalize_org_name

CAMPAIGN_NAME = "Chennai — Social commerce (Instagram, Facebook, WhatsApp)"

DEFAULT_SETTINGS: dict[str, Any] = {
    "depth": "balanced",  # quick | balanced | deep
    "max_candidates": 40,  # new sellers per run
    "max_research": 12,  # sellers whose public pages are read per run
    "daily_shortlist": 5,
    "ai_max_calls": 10,  # per run; deep mode only; 0 disables AI
    "approved_localities": [],
    "categories": list(cat.CATEGORIES),
    "sources": {"manual_profile": True, "csv_import": True, "public_search": True,
                "market_listings": True, "business_features": True, "meta_api": False},
    "search_terms": [],  # extra owner-supplied search phrases
    "market_pages": [],  # public market / exhibitor pages the owner authorises
    "schedule": "off",
}


def active_campaign(db: Session) -> Campaign:
    """The social-commerce campaign (separate from the B2B one, so the pipelines stay isolated)."""
    c = db.scalar(select(Campaign).where(Campaign.channel == SOCIAL, Campaign.status == "active").order_by(Campaign.id.desc()))
    if c is None:
        c = Campaign(name=CAMPAIGN_NAME, channel=SOCIAL, city="Chennai", industries=list(cat.CATEGORIES),
                     industry_mix={}, settings=dict(DEFAULT_SETTINGS), status="active")
        db.add(c)
        db.commit()
    return c


def campaign_settings(c: Campaign) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(c.settings or {})}


# ------------------------------------------------------------------------------------------------
# Source registry — honest about what IOI can actually reach (§8, §9)
# ------------------------------------------------------------------------------------------------
SOURCES = [
    dict(key="manual_profile", name="Add a profile or catalogue link by hand", category="manual", access_method="form",
         url=None, geo_coverage="Chennai", industry_coverage="All social categories", rate_limit_per_minute=None,
         terms="Any public link you found yourself: a business profile, a catalogue, a market listing or their website.",
         description="The reliable way in. Paste a public Instagram/Facebook profile, a WhatsApp business number, "
                     "a catalogue link or a website and IOI investigates whatever is publicly readable."),
    dict(key="csv_import", name="Authorised list import (CSV)", category="import", access_method="csv", url=None,
         geo_coverage="Whatever you upload (filtered to Chennai)", industry_coverage="All social categories",
         rate_limit_per_minute=None,
         terms="Only lists you are allowed to use — e.g. an exhibitor or market list you were given.",
         description="Upload a CSV of sellers; each row goes through the same checks as any other candidate."),
    dict(key="public_search", name="Public web search for indexed business profiles", category="search",
         access_method="api", url=None, geo_coverage="Chennai search phrases", industry_coverage="Per category",
         rate_limit_per_minute=30,
         terms="Needs an authorised search API key (Brave Search or Google Programmable Search). Without one this "
               "source reports itself unavailable rather than scraping a search engine.",
         description="Finds publicly indexed Instagram/Facebook business profiles and seller pages by search phrase."),
    dict(key="market_listings", name="Public Chennai market & exhibitor pages", category="directory",
         access_method="http", url=None, geo_coverage="Chennai events", industry_coverage="All social categories",
         rate_limit_per_minute=20,
         terms="Public event/exhibitor pages you add. robots.txt respected; no logins or CAPTCHAs.",
         description="Reads public pop-up market, craft fair and exhibition pages you authorise and picks out the "
                     "seller names and profile links they publish."),
    dict(key="business_features", name="Public business features & small-business news", category="news",
         access_method="rss", url="https://www.thehindu.com/news/cities/chennai/feeder/default.rss",
         geo_coverage="Chennai items only", industry_coverage="All social categories", rate_limit_per_minute=20,
         terms="Public RSS feeds; robots.txt respected; headlines and summaries only.",
         description="Finds published seller spotlights and entrepreneur features that name a Chennai social seller."),
    dict(key="meta_api", name="Meta Graph API (Instagram / Facebook Pages)", category="platform",
         access_method="api", url="https://developers.facebook.com/docs/graph-api/", geo_coverage="n/a",
         industry_coverage="n/a", rate_limit_per_minute=None,
         terms="Requires a Meta app, a connected business account and approved permissions. IOI has none of these, "
               "so this source stays unavailable. It is never used to read a profile IOI does not own.",
         description="Not available. Documented so it is clear what has and has not been set up."),
]


def seed_sources(db: Session) -> None:
    have = {s.key for s in db.scalars(select(DiscoverySource))}
    for s in SOURCES:
        if s["key"] in have:
            continue
        if s["key"] == "manual_profile":
            health, err = "working", None
        elif s["key"] == "meta_api":
            health, err = "needs_setup", ("No Meta app, business account or approved permissions are configured. "
                                          "IOI will not read Instagram or Facebook profiles automatically.")
        else:
            health, err = "untested", None
        db.add(DiscoverySource(**s, health=health, last_error=err))
    db.commit()


def source(db: Session, key: str) -> DiscoverySource | None:
    return db.scalar(select(DiscoverySource).where(DiscoverySource.key == key))


def mark_source_ok(db: Session, key: str, *, records: int | None = None, freshness: str | None = None) -> None:
    """A source is only ever marked working after a real successful retrieval."""
    from app.ioi3 import core as b2b_core

    b2b_core.mark_source(db, key, ok=True, records=records, freshness=freshness)


def mark_source_failed(db: Session, key: str, error: str) -> None:
    """Record a source failure in its own short transaction (never holds the caller's lock)."""
    from app.ioi3 import core as b2b_core
    from app.ioi3.fetch import short_write

    short_write(lambda s: b2b_core.mark_source(s, key, ok=False, error=error))


def add_fact(c: Company, **kw):
    """Shared evidence helper (same labelling and de-duplication as the B2B channel)."""
    from app.ioi3 import core as b2b_core

    return b2b_core.add_fact(c, **kw)


# ------------------------------------------------------------------------------------------------
# Profile, account and activity helpers
# ------------------------------------------------------------------------------------------------
def ensure_profile(c: Company) -> SocialProfile:
    if c.social is None:
        c.social = SocialProfile(company_id=c.id)
    return c.social


def add_account(c: Company, ref: plat.ProfileRef, *, source_url: str, excerpt: str | None = None,
                profile_name: str | None = None, followers: int | None = None, bio: str | None = None,
                catalogue_url: str | None = None, detected_by: str = "rule", primary: bool = False) -> SocialAccount | None:
    """Record a public account. Returns None if this exact account is already known."""
    for a in c.social_accounts:
        if a.platform == ref.platform and a.handle == ref.handle:
            if primary and not a.is_primary:
                a.is_primary = True
            if bio and not a.bio_excerpt:
                a.bio_excerpt = bio[:2000]
            if catalogue_url and not a.catalogue_url:
                a.catalogue_url = catalogue_url[:2048]
            return None
    acc = SocialAccount(
        platform=ref.platform, handle=ref.handle[:200], url=ref.url[:2048], profile_name=(profile_name or None),
        account_kind=ref.kind, catalogue_url=(catalogue_url or None), bio_excerpt=(bio or None) and bio[:2000],
        followers=followers, is_primary=primary or not c.social_accounts, source_url=source_url[:2048],
        excerpt=(excerpt or None) and excerpt[:1500],
        reachable="public" if plat.FETCHABLE.get(ref.platform) else "restricted", detected_by=detected_by)
    c.social_accounts.append(acc)
    return acc


def add_activity(c: Company, *, signal_type: str, statement: str, url: str, indicator_class: str = "activity",
                 platform: str | None = None, published_at: datetime | None = None, excerpt: str | None = None,
                 state: str = "source_verified", reliability: str = "medium", source_name: str | None = None,
                 detected_by: str = "rule", review_status: str | None = "hypothesis") -> SocialActivity | None:
    for a in c.social_activity:
        if a.url == url and a.signal_type == signal_type:
            a.last_checked_at = utcnow()
            return None
    row = SocialActivity(
        signal_type=signal_type[:40], statement=statement[:2000], url=url[:2048], indicator_class=indicator_class,
        platform=platform, published_at=published_at, excerpt=(excerpt or None) and excerpt[:1500], state=state,
        reliability=reliability, source_name=source_name, detected_by=detected_by, review_status=review_status,
        last_checked_at=utcnow())
    c.social_activity.append(row)
    return row


def add_contact(c: Company, *, kind: str, value: str, source_url: str, official: bool,
                label: str | None = None) -> CompanyContact | None:
    """Public business contact routes only. Never a guessed address, never a private number."""
    value = (value or "").strip()
    if not value or not source_url:
        return None
    norm = re.sub(r"\D", "", value)[-10:] if kind == "phone" else value.lower()
    for x in c.contacts:
        if x.kind == kind and (re.sub(r"\D", "", x.value)[-10:] if kind == "phone" else x.value.lower()) == norm:
            if official and not x.official:
                x.official, x.source_url = True, source_url
            return None
    ct = CompanyContact(kind=kind, value=value[:500], source_url=source_url[:2048], official=official, label=label)
    c.contacts.append(ct)
    return ct


def set_geo(c: Company, verdict: geomod.GeoVerdict) -> None:
    p = ensure_profile(c)
    p.geo_confidence = verdict.confidence
    p.geo_reason = verdict.reason
    p.geo_basis = verdict.basis
    p.geo_evidence_url = verdict.evidence_url
    p.geo_excerpt = verdict.excerpt
    if verdict.locality:
        c.locality = verdict.locality
    if verdict.pincode:
        c.pincode = verdict.pincode
    # Mirror into the shared column so lists and the pipeline can filter on one field.
    c.location_confidence = {geomod.VERIFIED: "verified", geomod.PROBABLE: "partial",
                             geomod.OUTSIDE: "outside", geomod.UNCLEAR: "unknown"}[verdict.confidence]
    c.location_reason = verdict.reason


# ------------------------------------------------------------------------------------------------
# Snapshot and evaluation
# ------------------------------------------------------------------------------------------------
def snapshot(c: Company) -> qualify.Snapshot:
    p = c.social or SocialProfile(company_id=c.id)
    acts = [qualify.ActivityView(a.signal_type, a.indicator_class, a.published_at, a.url,
                                 a.review_status or "hypothesis", a.statement) for a in c.social_activity]
    return qualify.Snapshot(
        name=c.name, category=p.product_category, geo_confidence=p.geo_confidence or geomod.UNCLEAR,
        platforms={a.platform for a in c.social_accounts},
        activity=acts, complexity_keys=set(p.complexity_keys or []),
        confirmed_problems=[f.statement for f in c.facts if f.kind == "problem" and f.state == "buyer_confirmed"],
        official_contacts=sum(1 for x in c.contacts if x.official),
        other_contacts=sum(1 for x in c.contacts if not x.official),
        sales_setup=p.sales_setup or cat.SETUP_UNKNOWN, order_channels=list(p.order_channels or []),
        tools=list(p.known_tools or []), workflow_gaps=list(p.workflow_gaps or []),
        research_level=p.research_level or "profile", review_status=c.review_status, disqualifier=c.disqualifier,
        accounts=len(c.social_accounts),
        business_account=any(a.account_kind in ("business", "page", "creator") for a in c.social_accounts),
        weak_geo_only=_weak_only(c),
    )


def _weak_only(c: Company) -> list[str]:
    """Weak location evidence recorded for this seller (shown so it is clear it was seen and ignored)."""
    out = []
    for f in c.facts:
        if f.kind == "note" and f.key == "weak_location_evidence" and f.statement:
            out.append(f.statement)
    return out[:4]


def evaluate(c: Company, now: datetime | None = None) -> Company:
    """Recompute everything from stored evidence. Called after any change to a seller's evidence."""
    now = now or utcnow()
    p = ensure_profile(c)
    s = snapshot(c)

    gs = qualify.gates(s, now)
    c.gates = gs
    c.qualification, c.qualification_reasons = qualify.categorise(s, gs, now)

    sol = solutions.recommend(category=s.category, complexity_keys=s.complexity_keys, tools=s.tools,
                              sales_setup=s.sales_setup, confirmed_problems=s.confirmed_problems,
                              order_channels=s.order_channels, workflow_gaps=s.workflow_gaps)
    c.solution = sol
    c.score, c.score_breakdown = qualify.score(s, now, sol.get("level"))
    c.friction, c.friction_reasons = qualify.friction(s)
    c.buying_intent = qualify.buying_intent(s)
    c.operational_fit = qualify.operational_fit(s)
    c.commercial_readiness = qualify.commercial_readiness(s, now)
    c.evidence_quality = qualify.evidence_quality(s)
    c.next_action = qualify.next_action(c.qualification, gs, s)

    p.maturity, p.maturity_reasons = qualify.maturity(s, now)
    p.complexity_level = cat.complexity_level(s.complexity_keys)
    dates = [a.published_at for a in c.social_activity if a.published_at and (a.review_status or "") != "rejected"]
    p.last_activity_at = max(dates) if dates else None
    p.activity_count = sum(1 for a in c.social_activity if a.indicator_class == "activity" and a.review_status != "rejected")
    p.demand_indicator_count = sum(1 for a in c.social_activity
                                   if a.indicator_class == "demand_indicator" and a.review_status != "rejected")
    c.dossier = {**(c.dossier or {}), "answers": explain(c, s, gs, sol)}
    if c.review_status == "shortlisted" and not qualify.ready(gs):
        c.review_status = "new"  # a check stopped passing, so it leaves the ready queue
    return c


SOURCE_LABEL = {"manual_profile": "you (added by hand)", "csv_import": "a list you imported",
                "public_search": "a public web search", "market_listings": "a public Chennai market listing",
                "business_features": "a published business feature"}


def explain(c: Company, s: qualify.Snapshot, gs: list[dict], sol: dict) -> list[dict]:
    """Plain answers to the questions every social lead must answer (§15). Stored evidence only."""
    p = c.social
    agent = (c.dossier or {}).get("agent") or {}
    verified = [a for a in c.social_activity if a.state == "source_verified" and a.review_status != "rejected"]
    confirmed = s.confirmed_problems
    open_gates = [g["label"] for g in gs if g["passed"] is not True]
    hypotheses = [f.statement for f in c.facts if f.kind == "problem" and f.state == "inferred"]
    who = [f"{x.kind}: {x.value} ({'their own profile/site' if x.official else 'public listing'})" for x in c.contacts[:4]]
    accounts = ", ".join(f"{plat.PLATFORM_LABEL[a.platform]} @{a.handle}" for a in c.social_accounts[:3])
    return [
        {"q": "Why was this seller found?", "a": f"Found via {SOURCE_LABEL.get(c.source_key, c.source_key)}."
            + (f" Accounts: {accounts}." if accounts else "")},
        {"q": "What exactly do they sell?", "a": c.description or (cat.CATEGORY_LABEL.get(s.category or "")
            if s.category else "Not established yet.")},
        {"q": "What evidence exists?", "a": f"{len(verified)} dated/source-verified public signals, "
            f"{p.activity_count if p else 0} activity and {p.demand_indicator_count if p else 0} demand indicators. "
            f"Evidence quality: {c.evidence_quality}. Location: {geomod.GEO_LABEL.get(p.geo_confidence if p else '', 'unclear')}."},
        {"q": "How do they take orders today?", "a": (cat.SETUP_LABEL.get(p.sales_setup, "Not known yet") if p else "Not known yet")
            + (f" — {p.sales_setup_reason}" if p and p.sales_setup_reason else "")
            + (f" Channels: {', '.join(s.order_channels)}." if s.order_channels else "")},
        {"q": "What is the likely operational problem?",
         "a": (confirmed[0] if confirmed else hypotheses[0] if hypotheses else "Not identified yet.")},
        {"q": "Is that problem verified or a hypothesis?",
         "a": "Confirmed by the seller." if confirmed else
              ("Hypothesis from their own public posts — not confirmed by them." if hypotheses or s.complexity_keys
               else "Nothing identified yet.")},
        {"q": "Why might Inferago be useful to them?", "a": sol.get("why") or "Not established."},
        {"q": "What is the recommended low-cost step?", "a": (f"{sol['offer']} — {sol.get('level_label')}. "
            f"{sol.get('improvement') or ''}" if sol.get("offer") else "Nothing to offer yet.")},
        {"q": "What must still be confirmed?",
         "a": "; ".join((agent.get("open_questions") or []) + (sol.get("confirm_with_buyer") or [])[:3])
              + (f" Also unverified: {', '.join(open_gates)}." if open_gates else "") or "—"},
        {"q": "Who can be contacted legitimately?", "a": "; ".join(who) or "No public business contact found yet."},
        {"q": "What should the founder ask first?",
         "a": agent.get("first_question") or (sol.get("confirm_with_buyer") or ["How do you handle orders today?"])[0]},
    ]


def new_company(campaign_id: int, *, name: str, source_key: str, source_ref: str, source_url: str,
                is_test: bool = False) -> Company:
    c = Company(campaign_id=campaign_id, channel=SOCIAL, name=name[:300],
                normalized_name=normalize_org_name(name)[:300], source_key=source_key, source_ref=source_ref[:200],
                source_url=source_url, is_test=is_test, review_status="new", industry=None,
                industry_strength="candidate", location_confidence="unknown", activity="unknown",
                research_level="directory", qualification=qualify.S2, friction="unknown", buying_intent="unknown",
                score=0, prescore=0.0, archived=False)
    c.facts, c.contacts, c.locations, c.social_accounts, c.social_activity = [], [], [], [], []
    c.social = SocialProfile()
    return c


def prescore(c: Company) -> float:
    """Research order only — which sellers to read first."""
    p = c.social
    s = 0.0
    s += 3 if p and p.product_category else 0
    s += 2 if p and p.geo_confidence == geomod.VERIFIED else 1 if p and p.geo_confidence == geomod.PROBABLE else 0
    s += 2 if any(a.catalogue_url for a in c.social_accounts) else 0
    s += 2 if c.website else 0
    s += 1 if any(x.official for x in c.contacts) else 0
    s += 1 if any(a.account_kind in ("business", "page") for a in c.social_accounts) else 0
    return s
