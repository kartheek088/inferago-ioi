"""Campaign, source registry, evidence helpers, identity resolution and evaluation."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import lead_rules
from app.db import utcnow
from app.ioi3 import qualify
from app.ioi3.models import Campaign, Company, CompanyContact, DiscoverySource, Fact, Location
from app.normalize import normalize_org_name

DEFAULT_SETTINGS: dict[str, Any] = {
    "depth": "balanced",  # quick | balanced | deep
    "max_candidates": 50,  # new businesses per run
    "max_deep": 10,  # websites researched per run
    "daily_shortlist": 5,
    "ai_max_calls": 10,  # per run; deep mode only; 0 disables AI
    "approved_localities": [],  # metro-area localities the owner accepts as in scope
    "sources": {"overture_places": True, "official_websites": True, "news_rss": True},
    "schedule": "off",  # off | daily | weekly
}
DEFAULT_MIX = {lead_rules.EQUIPMENT: 70, lead_rules.WHOLESALE: 30}


def active_campaign(db: Session) -> Campaign:
    c = db.scalar(select(Campaign).where(Campaign.status == "active").order_by(Campaign.id.desc()))
    if c is None:
        c = Campaign(name="Chennai — Equipment service & Wholesale distribution", city="Chennai",
                     industries=[lead_rules.EQUIPMENT, lead_rules.WHOLESALE], industry_mix=dict(DEFAULT_MIX),
                     settings=dict(DEFAULT_SETTINGS), status="active")
        db.add(c)
        db.commit()
    return c


def campaign_settings(c: Campaign) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(c.settings or {})}


# ------------------------------------------------------------------------------------------------
# Source registry (only advertised as working after a real successful retrieval)
# ------------------------------------------------------------------------------------------------
SOURCES = [
    dict(key="overture_places", name="Overture Maps business places (open data)", category="directory", access_method="local_file",
         url="https://docs.overturemaps.org/guides/places/", geo_coverage="Chennai box from the India file", industry_coverage="Both",
         terms="CDLA-Permissive-2.0 open data. Read from a local Parquet file; no scraping.", rate_limit_per_minute=None,
         description="Finds businesses: names, categories, addresses, phones, websites from Meta/Microsoft/Foursquare data."),
    dict(key="official_websites", name="Official company websites", category="website", access_method="http",
         url=None, geo_coverage="Per company", industry_coverage="Both", rate_limit_per_minute=20,
         terms="Up to a few public pages per company; robots.txt respected; no logins or CAPTCHAs.",
         description="Verifies address, operations, public contacts and dated announcements."),
    dict(key="news_rss", name="Business news RSS (The Hindu, BusinessLine, ET)", category="news", access_method="rss",
         url="https://www.thehindu.com/news/cities/chennai/feeder/default.rss", geo_coverage="Chennai items only",
         industry_coverage="Both", rate_limit_per_minute=20, terms="Public RSS feeds; robots.txt respected; headlines and summaries only.",
         description="Finds dated expansion / new facility / technology news and matches it to known companies."),
    dict(key="csv_import", name="Authorised CSV import", category="import", access_method="csv", url=None,
         geo_coverage="Whatever you upload (filtered to Chennai)", industry_coverage="Both", rate_limit_per_minute=None,
         terms="Only lists you are allowed to use (e.g. exhibitor or association lists you received).",
         description="Upload a CSV of businesses; each row is checked like any other candidate."),
    dict(key="manual", name="Add a business by hand", category="manual", access_method="form", url=None,
         geo_coverage="Chennai", industry_coverage="Both", rate_limit_per_minute=None,
         terms="Anything you found yourself — a post, a trade-fair list — with the link where you found it.",
         description="For LinkedIn posts, IndiaMART pages and other sites IOI does not read automatically."),
]


def seed_sources(db: Session) -> None:
    have = {s.key for s in db.scalars(select(DiscoverySource))}
    for s in SOURCES:
        if s["key"] not in have:
            db.add(DiscoverySource(**s, health="working" if s["key"] in ("manual",) else "untested"))
    db.commit()


def source(db: Session, key: str) -> DiscoverySource | None:
    return db.scalar(select(DiscoverySource).where(DiscoverySource.key == key))


def mark_source(db: Session, key: str, *, ok: bool, records: int | None = None, error: str | None = None, freshness: str | None = None) -> None:
    s = source(db, key)
    if s is None:
        return
    now = utcnow()
    if ok:
        s.health, s.last_success_at, s.failure_count = "working", now, 0
        if records is not None:
            s.last_records = records
        if freshness:
            s.data_freshness = freshness
    else:
        s.health = "needs_setup" if error and error.startswith("needs_setup:") else "failing"
        s.last_error, s.last_error_at = (error or "unknown error")[:500], now
        s.failure_count = (s.failure_count or 0) + 1


# ------------------------------------------------------------------------------------------------
# Evidence helpers (deduplicated)
# ------------------------------------------------------------------------------------------------
def add_fact(c: Company, *, kind: str, statement: str, state: str, key: str | None = None, excerpt: str | None = None,
             source_url: str | None = None, source_name: str | None = None, reliability: str = "medium",
             published_at: datetime | None = None, detected_by: str = "rule", review_status: str | None = None) -> Fact | None:
    assert state in ("source_verified", "inferred", "buyer_confirmed", "unknown")
    for f in c.facts:
        if f.kind == kind and f.key == key and f.source_url == source_url and (key or f.statement == statement):
            return None
    f = Fact(kind=kind, statement=statement[:2000], state=state, key=key, excerpt=(excerpt or None) and excerpt[:1500],
             source_url=source_url, source_name=source_name, reliability=reliability, published_at=published_at,
             detected_by=detected_by, review_status=review_status)
    c.facts.append(f)
    return f


def add_contact(c: Company, *, kind: str, value: str, source_url: str, official: bool, label: str | None = None) -> CompanyContact | None:
    value = value.strip()
    if not value or not source_url:
        return None
    norm = re.sub(r"\D", "", value)[-10:] if kind == "phone" else value.lower()
    for x in c.contacts:
        if x.kind == kind and (re.sub(r"\D", "", x.value)[-10:] if kind == "phone" else x.value.lower()) == norm:
            if official and not x.official:  # upgrade provenance to the official site
                x.official, x.source_url = True, source_url
            return None
    ct = CompanyContact(kind=kind, value=value[:500], source_url=source_url, official=official, label=label)
    c.contacts.append(ct)
    return ct


def add_location(c: Company, *, address: str | None, verdict, basis: str, evidence_url: str | None, excerpt: str | None = None,
                 lat: float | None = None, lon: float | None = None) -> Location:
    loc = Location(address=address, locality=verdict.locality, pincode=verdict.pincode, lat=lat, lon=lon, status=verdict.status,
                   reason=verdict.reason, basis=basis, evidence_url=evidence_url, excerpt=excerpt)
    c.locations.append(loc)
    return loc


def location_confidence(status: str, basis: str) -> str:
    if status in ("outside", "gcma_outside"):
        return "outside"
    if status == "chennai_city":
        return "verified" if basis in ("official_site", "owner") else "partial"
    return "unknown"


# ------------------------------------------------------------------------------------------------
# Identity resolution — never merge on name alone
# ------------------------------------------------------------------------------------------------
def _phones(c: Company) -> set[str]:
    return {re.sub(r"\D", "", x.value)[-10:] for x in c.contacts if x.kind == "phone"}


def same_business(a_name: str, a_domain: str | None, a_phones: set[str], a_lat, a_lon, b: Company) -> bool:
    if normalize_org_name(a_name) != b.normalized_name or not b.normalized_name:
        return False
    if a_domain and b.domain and a_domain == b.domain:
        return True
    if a_phones & _phones(b):
        return True
    if None not in (a_lat, a_lon, b.lat, b.lon) and abs(a_lat - b.lat) < 0.3 / 111 and abs(a_lon - b.lon) < 0.3 / 108:
        return True
    return False


def find_existing(db: Session, campaign_id: int, name: str, domain: str | None, phones: set[str], lat, lon) -> Company | None:
    if domain:
        hit = db.scalar(select(Company).where(Company.campaign_id == campaign_id, Company.domain == domain,
                                              Company.review_status != "duplicate"))
        if hit is not None and hit.normalized_name == normalize_org_name(name):
            return hit
    for b in db.scalars(select(Company).where(Company.campaign_id == campaign_id, Company.normalized_name == normalize_org_name(name),
                                              Company.review_status != "duplicate")):
        if same_business(name, domain, phones, lat, lon, b):
            return b
    return None


# ------------------------------------------------------------------------------------------------
# Evaluation
# ------------------------------------------------------------------------------------------------
TOOL_RX = re.compile(r"\b(tally|zoho|sap|oracle|salesforce|microsoft dynamics|busy accounting|marg erp|google sheets|excel)\b", re.I)


def snapshot(c: Company) -> qualify.Snapshot:
    sigs = [qualify.SignalView(f.key or "", f.review_status or "hypothesis", f.published_at, f.source_url, f.statement)
            for f in c.facts if f.kind == "signal"]
    return qualify.Snapshot(
        name=c.name, industry=c.industry, industry_strength=c.industry_strength, location_confidence=c.location_confidence,
        activity=c.activity,
        official_contacts=sum(1 for x in c.contacts if x.official),
        directory_contacts=sum(1 for x in c.contacts if not x.official),
        workflow_keys={f.key for f in c.facts if f.kind == "workflow" and f.state in ("source_verified", "buyer_confirmed") and f.key},
        signals=sigs,
        buyer_confirmed_problems=[f.statement for f in c.facts if f.kind == "problem" and f.state == "buyer_confirmed"],
        tools={f.key for f in c.facts if f.kind == "tools" and f.state in ("source_verified", "buyer_confirmed") and f.key},
        disqualifier=c.disqualifier, review_status=c.review_status, research_level=c.research_level,
        legal_form=lead_rules.legal_form(c.name),
    )


def evaluate(c: Company, now: datetime | None = None) -> Company:
    now = now or utcnow()
    s = snapshot(c)
    gs = qualify.gates(s)
    c.gates = gs
    c.qualification, c.qualification_reasons = qualify.categorise(s, gs, now)
    sol = qualify.recommend(s)
    c.solution = sol
    c.score, c.score_breakdown = qualify.score(s, sol.get("level"), now)
    c.friction, c.friction_reasons = qualify.friction(s)
    c.buying_intent = qualify.buying_intent(s, now)
    c.next_action = qualify.next_action(c.qualification, gs, s)
    return c


def prescore(c: Company) -> float:
    s = {"strong": 3, "candidate": 2}.get(c.industry_strength, 0)
    s += 2 if c.website else 0
    s += 2 if c.location_confidence in ("partial", "verified") else 0
    s += 1 if any(x.kind == "email" for x in c.contacts) else 0
    s += 1 if re.search(r"\b(distributors?|wholesale|equipments?|instruments?|biomedical|surgical|systems|engineers?)\b", c.name, re.I) else 0
    return float(s)


def new_company(campaign_id: int, *, name: str, source_key: str, source_ref: str, source_url: str, is_test: bool = False) -> Company:
    c = Company(campaign_id=campaign_id, name=name[:300], normalized_name=normalize_org_name(name)[:300], source_key=source_key,
                source_ref=source_ref[:200], source_url=source_url, is_test=is_test, review_status="new",
                industry_strength="candidate", location_confidence="unknown", activity="unknown", research_level="directory",
                qualification="P2", friction="unknown", buying_intent="unknown", score=0, prescore=0.0, archived=False)
    c.facts, c.contacts, c.locations = [], [], []
    return c
