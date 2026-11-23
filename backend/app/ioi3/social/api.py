"""Social Commerce Intelligence REST API (/api/v3/social).

Separate from the B2B endpoints so the two pipelines stay independent, but approval, the sales
pipeline and payments reuse the shared `sales` module, so an approved seller becomes a deal in the
same tables as a B2B company.

No endpoint sends anything to a business.
"""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import DB, actor
from app.config import get_settings
from app.db import utcnow
from app.ioi3 import core as b2b_core
from app.ioi3 import engine as b2b_engine
from app.ioi3 import sales
from app.ioi3.api import fact_out
from app.ioi3.models import (
    SOCIAL,
    Activity,
    AgentEvent,
    Company,
    CompanyContact,
    Deal,
    Job,
    RawItem,
    SocialAccount,
    SocialProfile,
)
from app.ioi3.social import categories as cat
from app.ioi3.social import collect, core, engine, geo, platforms, qualify, research, search
from app.settings_store import log_activity

router = APIRouter(prefix="/v3/social", tags=["ioi3-social"])

TABS = ("ready", "high_fit", "watchlist", "verify", "approved", "excluded", "all")


# ------------------------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------------------------
def _seller(db: Session, cid: int) -> Company:
    c = db.get(Company, cid)
    if c is None or c.channel != SOCIAL:
        raise HTTPException(404, "Seller not found")
    return c


def _tabs_of(c: Company) -> set[str]:
    out = {"all"}
    ready = qualify.ready(c.gates or [])
    if c.qualification == qualify.S3 or c.review_status in ("rejected", "duplicate"):
        out.add("excluded")
        return out
    if c.review_status == "approved":
        out.add("approved")
    if c.review_status == "shortlisted":
        out.add("ready")
    if c.qualification in (qualify.S0, qualify.S1):
        out.add("high_fit")
    if c.review_status == "watchlist":
        out.add("watchlist")
    if not ready:
        out.add("verify")
    return out


def account_out(a: SocialAccount) -> dict[str, Any]:
    return {"id": a.id, "platform": a.platform, "label": platforms.PLATFORM_LABEL[a.platform], "handle": a.handle,
            "url": a.url, "profile_name": a.profile_name, "account_kind": a.account_kind,
            "catalogue_url": a.catalogue_url, "bio_excerpt": a.bio_excerpt,
            # Shown for context only; it is never part of the score.
            "followers": a.followers, "followers_note": "Recorded from the profile. Never used in scoring.",
            "last_post_at": a.last_post_at, "is_primary": a.is_primary, "reachable": a.reachable,
            "readable_by_ioi": bool(platforms.FETCHABLE.get(a.platform)), "source_url": a.source_url,
            "excerpt": a.excerpt, "detected_by": a.detected_by, "observed_at": a.observed_at}


def activity_out(a) -> dict[str, Any]:
    return {"id": a.id, "signal_type": a.signal_type,
            "label": cat.ACTIVITY_SIGNALS.get(a.signal_type, (a.signal_type,))[0],
            "indicator_class": a.indicator_class, "statement": a.statement, "excerpt": a.excerpt, "url": a.url,
            "platform": a.platform, "published_at": a.published_at, "last_checked_at": a.last_checked_at,
            "state": a.state, "reliability": a.reliability, "source_name": a.source_name,
            "detected_by": a.detected_by, "review_status": a.review_status}


def card(c: Company) -> dict[str, Any]:
    p = c.social
    acts = [a for a in c.social_activity if a.review_status != "rejected"]
    newest = max((a.published_at for a in acts if a.published_at), default=None)
    return {
        "id": c.id, "name": c.name, "description": c.description,
        "category": p.product_category if p else None,
        "category_label": cat.CATEGORY_LABEL.get((p.product_category if p else "") or ""),
        "locality": c.locality,
        "geo_confidence": p.geo_confidence if p else geo.UNCLEAR,
        "geo_label": geo.GEO_LABEL.get((p.geo_confidence if p else "") or geo.UNCLEAR),
        "geo_reason": p.geo_reason if p else None,
        "qualification": c.qualification, "qualification_label": qualify.CATEGORY_LABEL.get(c.qualification, ""),
        "qualification_reasons": c.qualification_reasons, "score": c.score, "friction": c.friction,
        "review_status": c.review_status, "buying_intent": c.buying_intent,
        "offer": (c.solution or {}).get("offer"), "next_action": c.next_action,
        "sales_setup": p.sales_setup if p else cat.SETUP_UNKNOWN,
        "sales_setup_label": cat.SETUP_LABEL.get((p.sales_setup if p else "") or cat.SETUP_UNKNOWN),
        "maturity": p.maturity if p else None,
        "maturity_label": qualify.MATURITY_LABEL.get((p.maturity if p else "") or ""),
        "complexity_level": p.complexity_level if p else "unknown",
        "complexity_count": len((p.complexity_keys if p else []) or []),
        "platforms": sorted({a.platform for a in c.social_accounts}),
        "handles": [{"platform": a.platform, "handle": a.handle, "url": a.url} for a in c.social_accounts[:3]],
        "last_activity_at": newest, "activity_count": p.activity_count if p else 0,
        "demand_indicator_count": p.demand_indicator_count if p else 0,
        "website": c.website, "has_contact": bool(c.contacts),
        "official_contact": any(x.official for x in c.contacts),
        "sales_ready": qualify.ready(c.gates or []),
        "research_level": p.research_level if p else "profile",
        "research_error": p.research_error if p else None,
        "needs_human_check": bool(research.blocked_accounts(c)) and (p.research_level if p else "profile") == "profile",
        "operational_fit": c.operational_fit, "evidence_quality": c.evidence_quality,
        "commercial_readiness": c.commercial_readiness, "ai_status": c.ai_status,
        "next_follow_up_at": c.next_follow_up_at, "is_test": c.is_test,
    }


def detail(db: Session, c: Company) -> dict[str, Any]:
    p = core.ensure_profile(c)
    d = db.scalar(select(Deal).where(Deal.company_id == c.id))
    events = list(db.scalars(select(AgentEvent).where(AgentEvent.company_id == c.id)
                             .order_by(AgentEvent.id.desc()).limit(80)))
    acts = list(db.scalars(select(Activity).where(Activity.company_id == c.id)
                           .order_by(Activity.occurred_at.desc()).limit(50)))
    from app.ioi3.api import deal_out

    return {
        **card(c),
        "geo_basis": p.geo_basis, "geo_evidence_url": p.geo_evidence_url, "geo_excerpt": p.geo_excerpt,
        "geo_bases": {k: v[1] for k, v in geo.BASES.items()},
        "weak_evidence_note": geo.WEAK_NOTE,
        "category_reasons": p.category_reasons or [], "products_excerpt": p.products_excerpt,
        "order_channels": p.order_channels or [], "known_tools": p.known_tools or [],
        "workflow_gaps": p.workflow_gaps or [], "sales_setup_reason": p.sales_setup_reason,
        "complexity": [{"key": k, "label": cat.COMPLEXITY[k][0]} for k in (p.complexity_keys or [])
                       if k in cat.COMPLEXITY],
        "maturity_reasons": p.maturity_reasons or [], "maturity_note": qualify.MATURITY_NOTE,
        "gates": c.gates or [], "score_breakdown": c.score_breakdown or [],
        "friction_reasons": c.friction_reasons or [], "solution": c.solution or {},
        "accounts": [account_out(a) for a in c.social_accounts],
        "blocked_accounts": research.blocked_accounts(c),
        "readable_pages": research.readable_targets(c), "pages_checked": p.pages_checked or [],
        "activity": [activity_out(a) for a in sorted(c.social_activity,
                                                     key=lambda x: (x.published_at or x.created_at), reverse=True)],
        "facts": [fact_out(f) for f in c.facts],
        "contacts": [{"id": x.id, "kind": x.kind, "value": x.value, "label": x.label, "source_url": x.source_url,
                      "official": x.official} for x in c.contacts],
        "activities": [{"id": a.id, "kind": a.kind, "summary": a.summary, "channel": a.channel, "actor": a.actor,
                        "occurred_at": a.occurred_at} for a in acts],
        "deal": deal_out(d) if d else None,
        "outreach": sales.draft(c, *_sender(db)),
        "dossier": c.dossier or {},
        "agent_events": [{"id": e.id, "session": e.session, "step": e.step, "kind": e.kind, "tool": e.tool,
                          "args": e.args, "status": e.status, "message": e.message, "model": e.model,
                          "duration_ms": e.duration_ms, "tokens_in": e.tokens_in, "tokens_out": e.tokens_out,
                          "cost_usd": e.cost_usd, "at": e.created_at} for e in events],
        "researched_at": p.researched_at, "research_error_kind": p.research_error_kind,
        "research_retry_after": p.research_retry_after, "ai_researched_at": c.ai_researched_at,
        "source_url": c.source_url, "source_key": c.source_key, "created_at": c.created_at,
        "outreach_approved_by": c.outreach_approved_by, "outreach_approved_at": c.outreach_approved_at,
        "disqualifier": c.disqualifier,
    }


def _sender(db: Session) -> tuple[str, str]:
    from app.settings_store import get_setting

    return (get_setting(db, "sender_name") or "", get_setting(db, "sender_link") or "")


# ------------------------------------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------------------------------------
@router.get("/overview")
def overview(db: Session = DB):
    """Real counts for the Social Commerce dashboard. Nothing is invented; zeros stay zeros."""
    camp = core.active_campaign(db)
    rows = list(db.scalars(select(Company)
                           .where(Company.campaign_id == camp.id, Company.archived.is_(False),
                                  Company.is_test.is_(False))
                           .options(selectinload(Company.social_accounts), selectinload(Company.contacts))))
    profiles = {c.id: c.social for c in rows}
    cutoff = utcnow() - timedelta(days=qualify.TRIGGER_DAYS)
    recently_active = sum(1 for c in rows if (profiles[c.id] and profiles[c.id].last_activity_at
                                              and profiles[c.id].last_activity_at >= cutoff))
    job = engine.active_job(db, camp.id)
    last = db.scalar(select(Job).where(Job.campaign_id == camp.id).order_by(Job.id.desc()))
    revenue = sales.revenue(db, camp.id)
    # A "qualified conversation" is a seller who actually replied — counted from the outreach log.
    replied = set(db.scalars(select(Activity.company_id).join(Company, Company.id == Activity.company_id)
                             .where(Company.campaign_id == camp.id, Activity.kind == "reply").distinct()))
    from app.ioi3.api import job_out

    return {
        "campaign": {"id": camp.id, "name": camp.name, "city": camp.city,
                     "categories": core.campaign_settings(camp).get("categories") or []},
        "stats": {
            "discovered": len(rows),
            "verified_sellers": sum(1 for c in rows if profiles[c.id] and profiles[c.id].geo_confidence == geo.VERIFIED),
            "high_fit": sum(1 for c in rows if c.qualification in (qualify.S0, qualify.S1)),
            "recently_active": recently_active,
            "needs_verification": sum(1 for c in rows if c.qualification != qualify.S3
                                      and not qualify.ready(c.gates or [])),
            "approved": sum(1 for c in rows if c.review_status == "approved"),
            "qualified_conversations": sum(1 for c in rows if c.id in replied),
            "ready_to_review": sum(1 for c in rows if c.review_status == "shortlisted"),
            "needs_human_check": sum(1 for c in rows if research.blocked_accounts(c)
                                     and (profiles[c.id].research_level if profiles[c.id] else "profile") == "profile"),
        },
        "revenue": revenue,
        "by_platform": {pl: sum(1 for c in rows if any(a.platform == pl for a in c.social_accounts))
                        for pl in platforms.PLATFORMS},
        "by_category": {k: sum(1 for c in rows if profiles[c.id] and profiles[c.id].product_category == k)
                        for k in cat.CATEGORIES},
        "by_qualification": {k: sum(1 for c in rows if c.qualification == k)
                             for k in (qualify.S0, qualify.S1, qualify.S2, qualify.S3)},
        "active_job": job_out(job) if job else None,
        "last_job": job_out(last) if last and (not job or last.id != job.id) else None,
        "preflight": engine.preflight(db, camp),
    }


@router.get("/counts")
def counts(db: Session = DB):
    camp = core.active_campaign(db)
    out = {t: 0 for t in TABS}
    for c in db.scalars(select(Company).where(Company.campaign_id == camp.id, Company.archived.is_(False),
                                              Company.is_test.is_(False))):
        for t in _tabs_of(c):
            out[t] += 1
    return out


# ------------------------------------------------------------------------------------------------
# Sellers
# ------------------------------------------------------------------------------------------------
@router.get("/sellers")
def sellers(
    tab: str = Query("ready", pattern="^(ready|high_fit|watchlist|verify|approved|excluded|all)$"),
    platform: str | None = Query(None, pattern="^(instagram|facebook|whatsapp|other|multi)$"),
    category: str | None = Query(None),
    qualification: str | None = Query(None, pattern="^S[0-3]$"),
    geo_confidence: str | None = Query(None, pattern="^(verified_chennai|probable_chennai|unclear|outside_chennai)$"),
    maturity: str | None = Query(None),
    research_state: str | None = Query(None, pattern="^(not_researched|researched|needs_human_check|failed)$"),
    active_days: int | None = Query(None, ge=1, le=730),
    contact: bool | None = None,
    q: str | None = None,
    include_test: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    db: Session = DB,
):
    camp = core.active_campaign(db)
    stmt = (select(Company).where(Company.campaign_id == camp.id, Company.archived.is_(False))
            .options(selectinload(Company.social_accounts), selectinload(Company.social_activity),
                     selectinload(Company.contacts)))
    if not include_test:
        stmt = stmt.where(Company.is_test.is_(False))
    if qualification:
        stmt = stmt.where(Company.qualification == qualification)
    if q:
        stmt = stmt.where(or_(Company.name.ilike(f"%{q}%"), Company.locality.ilike(f"%{q}%"),
                              Company.description.ilike(f"%{q}%")))
    if category:
        stmt = stmt.where(Company.social.has(SocialProfile.product_category == category))
    if geo_confidence:
        stmt = stmt.where(Company.social.has(SocialProfile.geo_confidence == geo_confidence))
    if maturity:
        stmt = stmt.where(Company.social.has(SocialProfile.maturity == maturity))
    if contact is not None:
        has = exists().where(CompanyContact.company_id == Company.id)
        stmt = stmt.where(has if contact else ~has)
    rows = [c for c in db.scalars(stmt) if tab in _tabs_of(c)]
    if platform == "multi":
        rows = [c for c in rows if len({a.platform for a in c.social_accounts}) > 1]
    elif platform:
        rows = [c for c in rows if any(a.platform == platform for a in c.social_accounts)]
    if active_days:
        cutoff = utcnow() - timedelta(days=active_days)
        rows = [c for c in rows if c.social and c.social.last_activity_at and c.social.last_activity_at >= cutoff]
    if research_state:
        def matches(c: Company) -> bool:
            p = c.social
            if research_state == "not_researched":
                return (p.research_level if p else "profile") == "profile"
            if research_state == "researched":
                return (p.research_level if p else "profile") != "profile"
            if research_state == "failed":
                return bool(p and p.research_error)
            return bool(research.blocked_accounts(c)) and (p.research_level if p else "profile") == "profile"
        rows = [c for c in rows if matches(c)]
    order = {qualify.S0: 0, qualify.S1: 1, qualify.S2: 2, qualify.S3: 3}
    rows.sort(key=lambda c: (order.get(c.qualification, 9), not qualify.ready(c.gates or []), -c.score, c.id))
    return {"items": [card(c) for c in rows[offset: offset + limit]], "total": len(rows),
            "offset": offset, "limit": limit}


@router.get("/sellers/{cid}")
def seller(cid: int, db: Session = DB):
    return detail(db, _seller(db, cid))


class AddProfileIn(BaseModel):
    link: str = Field(min_length=3, max_length=2048)
    name: str | None = Field(None, max_length=300)
    other_links: str | None = Field(None, max_length=4000)
    description: str | None = Field(None, max_length=4000)
    category: str | None = None
    address: str | None = Field(None, max_length=500)
    locality: str | None = Field(None, max_length=120)
    delivery_area: str | None = Field(None, max_length=500)
    pickup_point: str | None = Field(None, max_length=500)
    event_listing: str | None = Field(None, max_length=500)
    website: str | None = Field(None, max_length=2048)
    phone: str | None = Field(None, max_length=40)
    email: str | None = Field(None, max_length=200)
    source_url: str | None = Field(None, max_length=2048)
    note: str | None = Field(None, max_length=2000)


@router.post("/sellers", status_code=201)
def add_seller(body: AddProfileIn, db: Session = DB, who: str = Depends(actor)):
    """Add one seller from a public profile, catalogue or website link."""
    camp = core.active_campaign(db)
    if body.category and body.category not in cat.CATEGORIES:
        raise HTTPException(422, f"Unknown category. Use one of: {', '.join(cat.CATEGORIES)}")
    try:
        r = collect.add_profile(db, camp, body.model_dump(exclude_none=True))
    except platforms.NotAProfile as exc:
        raise HTTPException(422, str(exc)) from exc
    if r.outcome == "accepted":
        log_activity(db, "social_seller", r.company.id, "seller_added", {"name": r.company.name}, who)
        db.commit()
        return {"outcome": r.outcome, "seller": detail(db, r.company)}
    if r.outcome == "duplicate":
        return {"outcome": r.outcome, "reason": r.reason, "seller": detail(db, r.company)}
    raise HTTPException(422, r.reason or f"Not added: {r.outcome}")


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), source_url: str | None = Form(None), db: Session = DB,
                     who: str = Depends(actor)):
    raw = await file.read(get_settings().upload_max_bytes + 1)
    if len(raw) > get_settings().upload_max_bytes:
        raise HTTPException(413, "That file is too large.")
    camp = core.active_campaign(db)
    try:
        stats = collect.import_csv(db, camp, raw.decode("utf-8", errors="replace"), default_source_url=source_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_activity(db, "social_import", None, "csv_imported", {"rows": stats["rows"]}, who)
    db.commit()
    return stats


@router.get("/import/template.csv")
def csv_template():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(collect.CSV_COLUMNS)
    w.writerow(["Asha Cakes", "https://www.instagram.com/asha_cakes/", "", "home_bakery",
                "Custom cakes, pre-order 3 days", "Adyar, Chennai 600020", "Adyar", "9876543210", "", "",
                "Delivers across Chennai", "https://example.org/where-you-found-them", ""])
    return StreamingResponse(io.BytesIO(buf.getvalue().encode()), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=social-sellers-template.csv"})


# ------------------------------------------------------------------------------------------------
# Research
# ------------------------------------------------------------------------------------------------
class ObservationIn(BaseModel):
    """What a person saw after opening a profile IOI cannot read."""

    platform: str | None = Field(None, pattern="^(instagram|facebook|whatsapp|other)$")
    url: str | None = Field(None, max_length=2048)
    notes: str | None = Field(None, max_length=4000)
    last_post_at: str | None = None
    followers: int | None = Field(None, ge=0)
    account_kind: str | None = Field(None, pattern="^(business|creator|page|personal)$")
    catalogue_url: str | None = Field(None, max_length=2048)
    profile_location: str | None = Field(None, max_length=500)
    delivery_area: str | None = Field(None, max_length=500)
    pickup_point: str | None = Field(None, max_length=500)
    event_listing: str | None = Field(None, max_length=500)
    confirmed_problem: str | None = Field(None, max_length=1000)


@router.post("/sellers/{cid}/observation")
def record_observation(cid: int, body: ObservationIn, db: Session = DB, who: str = Depends(actor)):
    """Record what you saw on their profile. The honest route for Instagram and Facebook."""
    c = _seller(db, cid)
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(422, "Nothing to record.")
    research.record_observation(db, c, data, actor=who)
    log_activity(db, "social_seller", c.id, "observation_recorded", {"platform": data.get("platform")}, who)
    db.commit()
    return detail(db, c)


@router.post("/sellers/{cid}/research")
def research_one(cid: int, deep: bool = False, db: Session = DB, who: str = Depends(actor)):
    """Read this seller's own readable pages now (their website / catalogue, never a social profile)."""
    from app.http_client import SafeHttp

    c = _seller(db, cid)
    if not research.readable_targets(c):
        blocked = research.blocked_accounts(c)
        raise HTTPException(422, ("There is nothing IOI may read for this seller. "
                                  + (blocked[0]["why"] if blocked else "Add their website or catalogue link.")))
    http = SafeHttp(rate_limit_per_minute=20)
    try:
        research.research_seller(db, c, http, deep=deep)
        db.commit()
    finally:
        http.close()
    return detail(db, c)


@router.post("/sellers/{cid}/ai-research")
def ai_research(cid: int, db: Session = DB, who: str = Depends(actor)):
    from app.ioi3.social import agent

    c = _seller(db, cid)
    if not agent.available(db):
        raise HTTPException(422, "AI is not configured. Rule-based research still works.")
    out = agent.investigate(db, c, max_model_calls=agent.LIMITS.max_model_calls)
    db.commit()
    return {"outcome": out.outcome, "model_calls": out.model_calls, "tool_calls": out.tool_calls,
            "facts": out.facts, "complexity": out.complexity, "rejected_claims": out.rejected_claims,
            "stop_reason": out.stop_reason, "seller": detail(db, c)}


class SignalReviewIn(BaseModel):
    review_status: str = Field(pattern="^(confirmed|rejected)$")


@router.post("/sellers/{cid}/activity/{aid}/review")
def review_signal(cid: int, aid: int, body: SignalReviewIn, db: Session = DB, who: str = Depends(actor)):
    """Confirm or reject a detected signal. Only a confirmed request for help can reach S0."""
    c = _seller(db, cid)
    row = next((a for a in c.social_activity if a.id == aid), None)
    if row is None:
        raise HTTPException(404, "Signal not found")
    row.review_status = body.review_status
    b2b_core.evaluate(c)
    log_activity(db, "social_seller", c.id, "signal_reviewed", {"signal": aid, "status": body.review_status}, who)
    db.commit()
    return detail(db, c)


@router.get("/activity")
def activity_feed(days: int = Query(90, ge=1, le=730), indicator_class: str | None = Query(None),
                  platform: str | None = Query(None), limit: int = Query(100, ge=1, le=500), db: Session = DB):
    """Recent public activity across all sellers, newest first."""
    from app.ioi3.models import SocialActivity

    camp = core.active_campaign(db)
    since = utcnow() - timedelta(days=days)
    stmt = (select(SocialActivity, Company)
            .join(Company, Company.id == SocialActivity.company_id)
            .where(Company.campaign_id == camp.id, Company.archived.is_(False), Company.is_test.is_(False),
                   or_(SocialActivity.published_at.is_(None), SocialActivity.published_at >= since))
            .order_by(SocialActivity.published_at.desc().nullslast(), SocialActivity.id.desc()).limit(limit))
    if indicator_class:
        stmt = stmt.where(SocialActivity.indicator_class == indicator_class)
    if platform:
        stmt = stmt.where(SocialActivity.platform == platform)
    rows = db.execute(stmt).all()
    return {"items": [{**activity_out(a), "seller": {"id": c.id, "name": c.name}} for a, c in rows],
            "note": "A post shows a seller is active. It is not proof of sales, order volume or revenue."}


# ------------------------------------------------------------------------------------------------
# Discovery jobs
# ------------------------------------------------------------------------------------------------
class JobIn(BaseModel):
    mode: str | None = Field(None, pattern="^(quick|balanced|deep)$")
    max_candidates: int | None = Field(None, ge=1, le=200)
    max_research: int | None = Field(None, ge=1, le=100)
    ai_max_calls: int | None = Field(None, ge=0, le=200)
    categories: list[str] | None = None
    search_terms: list[str] | None = None
    only_sources: list[str] | None = None


@router.get("/discover")
def discover(db: Session = DB):
    camp = core.active_campaign(db)
    st = core.campaign_settings(camp)
    from app.ioi3.api import job_out

    job = engine.active_job(db, camp.id)
    return {"settings": {k: st.get(k) for k in ("depth", "max_candidates", "max_research", "ai_max_calls",
                                                "categories", "search_terms", "market_pages", "schedule")},
            "preflight": engine.preflight(db, camp), "stages": [{"key": k, "label": v} for k, v in engine.STAGES],
            "categories": [{"key": k, "label": cat.CATEGORY_LABEL[k], "blurb": cat.CATEGORY_BLURB[k]}
                           for k in cat.CATEGORIES],
            "active_job": job_out(job) if job else None,
            "search": {"ready": search.availability().ready, "message": search.availability().message,
                       "example_queries": search.queries_for(list(st.get("categories") or []), limit=6)}}


@router.post("/jobs", status_code=202)
def start_job(body: JobIn, db: Session = DB, who: str = Depends(actor)):
    camp = core.active_campaign(db)
    overrides = {k: v for k, v in body.model_dump(exclude_none=True).items() if k != "only_sources"}
    if overrides.get("categories"):
        bad = [c for c in overrides["categories"] if c not in cat.CATEGORIES]
        if bad:
            raise HTTPException(422, f"Unknown categories: {', '.join(bad)}")
    try:
        job = engine.start_job(db, camp, mode=body.mode, overrides=overrides, only_sources=body.only_sources)
    except b2b_engine.JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except b2b_engine.ConfigError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_activity(db, "social_job", job.id, "discovery_started", {"mode": job.mode}, who)
    db.commit()
    from app.ioi3.api import job_out

    return job_out(job)


@router.get("/jobs")
def jobs(limit: int = Query(20, ge=1, le=100), db: Session = DB):
    camp = core.active_campaign(db)
    from app.ioi3.api import job_out

    rows = db.scalars(select(Job).where(Job.campaign_id == camp.id).order_by(Job.id.desc()).limit(limit))
    return {"items": [job_out(j) for j in rows]}


@router.get("/jobs/{job_id}")
def job(job_id: int, db: Session = DB):
    from app.ioi3.api import job_out

    j = db.get(Job, job_id)
    if j is None or j.channel != SOCIAL:
        raise HTTPException(404, "Run not found")
    return job_out(j)


@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: int, db: Session = DB, who: str = Depends(actor)):
    j = db.get(Job, job_id)
    if j is None or j.channel != SOCIAL:
        raise HTTPException(404, "Run not found")
    from app.ioi3.api import job_out

    b2b_engine.request_stop(db, j)
    log_activity(db, "social_job", job_id, "stop_requested", {}, who)
    db.commit()
    return job_out(j)


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: int, db: Session = DB, who: str = Depends(actor)):
    j = db.get(Job, job_id)
    if j is None or j.channel != SOCIAL:
        raise HTTPException(404, "Run not found")
    if j.status not in ("failed", "interrupted", "stopped"):
        raise HTTPException(422, "Only a failed, stopped or interrupted run can be retried.")
    camp = core.active_campaign(db)
    failed = [k for k, v in (j.sources or {}).items() if v.get("status") == "failed"] or None
    try:
        new = engine.start_job(db, camp, mode=j.mode, trigger="retry", retry_of=j, only_sources=failed)
    except b2b_engine.JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    log_activity(db, "social_job", new.id, "discovery_retried", {"retry_of": job_id}, who)
    db.commit()
    from app.ioi3.api import job_out

    return job_out(new)


# ------------------------------------------------------------------------------------------------
# Approval and the shared sales pipeline
# ------------------------------------------------------------------------------------------------
class ApproveIn(BaseModel):
    message: str | None = Field(None, max_length=8000)


@router.post("/sellers/{cid}/approve")
def approve(cid: int, body: ApproveIn, db: Session = DB, who: str = Depends(actor)):
    c = _seller(db, cid)
    try:
        sales.approve(db, c, who, body.message)
    except sales.SalesError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return detail(db, c)


class DraftIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


@router.put("/sellers/{cid}/draft")
def edit_draft(cid: int, body: DraftIn, db: Session = DB, who: str = Depends(actor)):
    c = _seller(db, cid)
    sales.edit_draft(db, c, body.message, who)
    db.commit()
    return detail(db, c)


class ReviewIn(BaseModel):
    status: str = Field(pattern="^(watchlist|rejected|new|shortlisted)$")
    reason: str | None = Field(None, max_length=500)


@router.post("/sellers/{cid}/review")
def set_review(cid: int, body: ReviewIn, db: Session = DB, who: str = Depends(actor)):
    c = _seller(db, cid)
    try:
        sales.set_review(db, c, body.status, who, body.reason)
    except sales.SalesError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return detail(db, c)


class ContactedIn(BaseModel):
    channel: str = Field(pattern="^(whatsapp|instagram_dm|facebook_dm|phone|email|in_person|other)$")
    note: str | None = Field(None, max_length=2000)
    follow_up_days: int | None = Field(3, ge=0, le=90)


@router.post("/sellers/{cid}/contacted")
def mark_contacted(cid: int, body: ContactedIn, db: Session = DB, who: str = Depends(actor)):
    c = _seller(db, cid)
    channel = {"instagram_dm": "instagram", "facebook_dm": "facebook"}.get(body.channel, body.channel)
    try:
        sales.mark_contacted(db, c, who, channel, body.note, body.follow_up_days or None)
    except sales.SalesError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return detail(db, c)


class ReplyIn(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    interested: bool | None = None
    confirmed_problem: str | None = Field(None, max_length=1000)


@router.post("/sellers/{cid}/reply")
def record_reply(cid: int, body: ReplyIn, db: Session = DB, who: str = Depends(actor)):
    """Record what the seller replied. A problem they confirm becomes a buyer-confirmed fact."""
    c = _seller(db, cid)
    try:
        sales.record_reply(db, c, who, body.summary, body.interested, body.confirmed_problem)
    except sales.SalesError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return detail(db, c)


class CorrectIn(BaseModel):
    category: str | None = None
    name: str | None = Field(None, max_length=300)
    website: str | None = Field(None, max_length=2048)
    locality: str | None = Field(None, max_length=120)
    disqualifier: str | None = Field(None, max_length=500)
    owner_confirmed_locality: str | None = Field(None, max_length=200)


@router.put("/sellers/{cid}")
def correct(cid: int, body: CorrectIn, db: Session = DB, who: str = Depends(actor)):
    """Fix what IOI got wrong. Owner-stated facts are recorded as confirmed by you."""
    c = _seller(db, cid)
    p = core.ensure_profile(c)
    data = body.model_dump(exclude_none=True)
    if "category" in data:
        if data["category"] not in cat.CATEGORIES:
            raise HTTPException(422, f"Unknown category. Use one of: {', '.join(cat.CATEGORIES)}")
        p.product_category, p.category_reasons = data["category"], ["Category chosen by you"]
    for field in ("name", "website", "locality"):
        if field in data:
            setattr(c, field, data[field])
    if "website" in data:
        from app.normalize import domain_of

        c.domain = domain_of(data["website"])
    if "disqualifier" in data:
        c.disqualifier = data["disqualifier"] or None
    if data.get("owner_confirmed_locality"):
        research.record_observation(db, c, {"profile_location": data["owner_confirmed_locality"]}, actor=who)
    b2b_core.evaluate(c)
    log_activity(db, "social_seller", c.id, "seller_corrected", {"fields": sorted(data)}, who)
    db.commit()
    return detail(db, c)


@router.get("/export.csv")
def export_csv(tab: str = Query("all", pattern="^(ready|high_fit|watchlist|verify|approved|excluded|all)$"),
               db: Session = DB):
    camp = core.active_campaign(db)
    rows = [c for c in db.scalars(select(Company).where(Company.campaign_id == camp.id,
                                                        Company.archived.is_(False), Company.is_test.is_(False)))
            if tab in _tabs_of(c)]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "name", "category", "qualification", "score", "location", "location_reason", "maturity",
                "sales_setup", "complexity", "platforms", "handles", "offer", "contact", "next_action", "source_url"])
    for c in rows:
        p = c.social
        w.writerow([c.id, c.name, cat.CATEGORY_LABEL.get((p.product_category if p else "") or "", ""),
                    c.qualification, c.score, geo.GEO_LABEL.get((p.geo_confidence if p else "") or "", ""),
                    (p.geo_reason if p else "") or "", qualify.MATURITY_LABEL.get((p.maturity if p else "") or "", ""),
                    cat.SETUP_LABEL.get((p.sales_setup if p else "") or "", ""),
                    len((p.complexity_keys if p else []) or []),
                    " ".join(sorted({a.platform for a in c.social_accounts})),
                    " ".join(f"@{a.handle}" for a in c.social_accounts),
                    (c.solution or {}).get("offer") or "",
                    "; ".join(f"{x.kind}:{x.value}" for x in c.contacts), c.next_action or "", c.source_url])
    return StreamingResponse(io.BytesIO(buf.getvalue().encode()), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=social-sellers.csv"})
