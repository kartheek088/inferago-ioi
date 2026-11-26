"""IOI 3.0 REST API (/api/v3). Everything the UI needs; no endpoint sends anything to a business."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import DB, actor
from app.config import get_settings
from app.db import utcnow
from app.ioi3 import collect, core, engine, qualify, sales
from app.ioi3.models import Activity, Campaign, Company, CompanyContact, Deal, Job, DiscoverySource, Fact, RawItem
from app.lead_rules import EQUIPMENT, SIGNAL_LABEL, WHOLESALE
from app.models import ActivityLog
from app.settings_store import get_setting, log_activity, set_setting

router = APIRouter(prefix="/v3", tags=["ioi3"])

BUSINESS_DEFAULT = {
    "company_name": "Inferago Tech Services",
    "positioning": "Simple business automation and integration for companies that do not want complicated software.",
    "services": ["Backend / software development", "API development and integrations", "Workflow automation",
                 "Small custom internal business applications"],
    "facts": ["Founder-operated", "Udyam registered", "Not GST registered", "Not an incorporated company"],
    "revenue_goal_monthly": 30000,
    "sender_name": "",
    "sender_link": "",
    "language_note": "",
}


def _business(db: Session) -> dict[str, Any]:
    return {**BUSINESS_DEFAULT, **(get_setting(db, "ioi3_business") or {})}


def _company(db: Session, cid: int) -> Company:
    c = db.scalar(select(Company).where(Company.id == cid).options(
        selectinload(Company.facts), selectinload(Company.contacts), selectinload(Company.locations)))
    if c is None or c.archived:
        raise HTTPException(404, "Business not found")
    return c


def _err(exc: Exception, code: int = 422):
    raise HTTPException(code, str(exc)) from exc


# ------------------------------------------------------------------------------------------------
# Serialisers
# ------------------------------------------------------------------------------------------------
def _latest_signal(c: Company) -> dict | None:
    sigs = [f for f in c.facts if f.kind == "signal" and f.review_status != "rejected"]
    if not sigs:
        return None
    s = sorted(sigs, key=lambda f: f.published_at or datetime.min, reverse=True)[0]
    return {"label": SIGNAL_LABEL.get(s.key or "", s.statement), "date": s.published_at, "url": s.source_url,
            "confirmed": s.review_status == "confirmed"}


def card(c: Company) -> dict[str, Any]:
    return {
        "id": c.id, "name": c.name, "industry": c.industry, "industry_subtype": c.industry_subtype, "locality": c.locality,
        "location_confidence": c.location_confidence, "description": c.description, "qualification": c.qualification,
        "qualification_reasons": c.qualification_reasons, "score": c.score, "friction": c.friction, "review_status": c.review_status,
        "buying_intent": c.buying_intent, "offer": (c.solution or {}).get("offer"), "next_action": c.next_action,
        "latest_signal": _latest_signal(c), "website": c.website, "research_level": c.research_level,
        "has_contact": bool(c.contacts), "official_contact": any(x.official for x in c.contacts),
        "sources": len({f.source_url for f in c.facts if f.source_url}), "sales_ready": qualify.sales_ready(c.gates or []),
        "next_follow_up_at": c.next_follow_up_at, "is_test": c.is_test,
        "operational_fit": c.operational_fit, "evidence_quality": c.evidence_quality, "commercial_readiness": c.commercial_readiness,
        "ai_status": c.ai_status, "researched_at": c.researched_at,
    }


def fact_out(f: Fact) -> dict[str, Any]:
    return {"id": f.id, "kind": f.kind, "key": f.key, "statement": f.statement, "state": f.state, "excerpt": f.excerpt,
            "source_url": f.source_url, "source_name": f.source_name, "reliability": f.reliability, "published_at": f.published_at,
            "observed_at": f.observed_at, "detected_by": f.detected_by, "review_status": f.review_status, "reviewed_by": f.reviewed_by,
            "label": SIGNAL_LABEL.get(f.key or "") if f.kind == "signal" else None}


def deal_out(d: Deal) -> dict[str, Any]:
    return {"id": d.id, "company_id": d.company_id, "company": d.company.name,
            # Which pipeline the lead came from, so the shared board can label and filter it.
            "channel": d.company.channel, "lead_source": d.company.lead_source, "stage": d.stage, "outcome": d.outcome,
            "outcome_reason": d.outcome_reason,
            "contact_name": d.contact_name, "confirmed_requirement": d.confirmed_requirement, "offer": d.offer,
            "potential_amount": d.potential_amount, "quoted_amount": d.quoted_amount, "expected_payment_date": d.expected_payment_date,
            "delivery_status": d.delivery_status, "next_follow_up_at": d.next_follow_up_at, "notes": d.notes,
            "collected": sales.collected(d), "outstanding": sales.balance(d),
            "payments": [{"id": p.id, "amount": p.amount, "kind": p.kind, "received_on": p.received_on, "reference": p.reference,
                          "note": p.note} for p in d.payments],
            "updated_at": d.updated_at}


def detail(db: Session, c: Company) -> dict[str, Any]:
    acts = db.scalars(select(Activity).where(Activity.company_id == c.id).order_by(Activity.occurred_at.desc()).limit(100)).all()
    deal = db.scalar(select(Deal).where(Deal.company_id == c.id))
    biz = _business(db)
    return {
        **card(c), "address": c.address, "pincode": c.pincode, "location_reason": c.location_reason, "activity": c.activity,
        "industry_strength": c.industry_strength, "industry_reasons": c.industry_reasons, "directory_category": c.directory_category,
        "gates": c.gates, "score_breakdown": c.score_breakdown, "friction_reasons": c.friction_reasons, "solution": c.solution,
        "disqualifier": c.disqualifier, "source_url": c.source_url, "source_key": c.source_key, "researched_at": c.researched_at,
        "research_error": c.research_error, "last_verified_at": c.last_verified_at, "created_at": c.created_at,
        "outreach_approved_by": c.outreach_approved_by, "outreach_approved_at": c.outreach_approved_at,
        "facts": [fact_out(f) for f in c.facts],
        "contacts": [{"id": x.id, "kind": x.kind, "value": x.value, "label": x.label, "source_url": x.source_url, "official": x.official,
                      "observed_at": x.observed_at} for x in c.contacts],
        "locations": [{"address": x.address, "locality": x.locality, "pincode": x.pincode, "status": x.status, "reason": x.reason,
                       "basis": x.basis, "evidence_url": x.evidence_url, "excerpt": x.excerpt, "observed_at": x.observed_at}
                      for x in c.locations],
        "activities": [{"id": a.id, "kind": a.kind, "summary": a.summary, "channel": a.channel, "actor": a.actor,
                        "occurred_at": a.occurred_at} for a in acts],
        "deal": deal_out(deal) if deal else None,
        "people": [{"id": p.id, "name": p.name, "role": p.role, "role_group": p.role_group, "excerpt": p.excerpt, "source_url": p.source_url,
                    "published_contact": p.published_contact, "detected_by": p.detected_by, "verified_at": p.verified_at} for p in c.people],
        "dossier": c.dossier or {}, "scope_confirmed": c.scope_confirmed, "research_error_kind": c.research_error_kind,
        "research_retry_after": c.research_retry_after, "ai_researched_at": c.ai_researched_at,
        "agent_events": agent_events(db, company_id=c.id, latest_session=True),
        "outreach": sales.draft(c, biz.get("sender_name", ""), biz.get("sender_link", "")),
    }


def job_out(j: Job) -> dict[str, Any]:
    return {"id": j.id, "mode": j.mode, "status": j.status, "stage": j.stage, "stage_index": j.stage_index,
            "stages": [{"key": k, "label": v} for k, v in engine.STAGES], "counters": j.counters, "sources": j.sources,
            "params": j.params, "summary": j.summary, "log": (j.log or [])[-60:], "error": j.error, "trigger": j.trigger,
            "retry_of_id": j.retry_of_id, "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
            "heartbeat_at": j.heartbeat_at,
            "elapsed_s": int(((j.finished_at or utcnow()) - j.started_at).total_seconds()) if j.started_at else None,
            "last_success": (j.summary or {}).get("last_success")}


# ------------------------------------------------------------------------------------------------
# Status, onboarding, settings
# ------------------------------------------------------------------------------------------------
@router.get("/status")
def status(db: Session = DB):
    camp = core.active_campaign(db)
    s = get_settings()
    return {"ok": True, "onboarding_done": bool(get_setting(db, "ioi3_onboarding_done")), "campaign": {"id": camp.id, "name": camp.name},
            "preflight": engine.preflight(db, camp), "ai_configured": s.ai_enabled, "worker_alive": engine._thread is not None and engine._thread.is_alive(),
            "time": utcnow()}


class SettingsIn(BaseModel):
    business: dict[str, Any] | None = None
    discovery: dict[str, Any] | None = None


@router.get("/settings")
def read_settings(db: Session = DB):
    camp = core.active_campaign(db)
    s = get_settings()
    provider = "Claude (Anthropic)" if s.claude_enabled else "OpenRouter" if s.ai_enabled else None
    return {
        "business": _business(db),
        "discovery": {**core.campaign_settings(camp), "city": camp.city, "industries": camp.industries, "industry_mix": camp.industry_mix},
        "ai": {"configured": s.ai_enabled, "provider": provider, "model": s.ai_model_name,
               "how_to_configure": "Set IOI_OPENROUTER_API_KEY and IOI_OPENROUTER_MODEL (or IOI_ANTHROPIC_API_KEY) in the .env file, then restart."},
    }


_DISCOVERY_KEYS = {"depth", "max_candidates", "max_deep", "daily_shortlist", "ai_max_calls", "approved_localities", "sources", "schedule"}


@router.put("/settings")
def write_settings(body: SettingsIn, db: Session = DB, who: str = Depends(actor)):
    camp = core.active_campaign(db)
    if body.business is not None:
        b = {**_business(db), **{k: v for k, v in body.business.items() if k in BUSINESS_DEFAULT}}
        if not isinstance(b.get("revenue_goal_monthly"), int) or b["revenue_goal_monthly"] < 0:
            raise HTTPException(422, "Revenue goal must be a whole number of rupees")
        set_setting(db, "ioi3_business", b)
    if body.discovery is not None:
        d = {k: v for k, v in body.discovery.items() if k in _DISCOVERY_KEYS}
        if "depth" in d and d["depth"] not in engine.MODES:
            raise HTTPException(422, "Depth must be quick, balanced or deep")
        for k, lo, hi in (("max_candidates", 1, 500), ("max_deep", 0, 100), ("daily_shortlist", 1, 50), ("ai_max_calls", 0, 200)):
            if k in d and not (isinstance(d[k], int) and lo <= d[k] <= hi):
                raise HTTPException(422, f"{k.replace('_', ' ')} must be between {lo} and {hi}")
        if "schedule" in d and d["schedule"] not in ("off", "daily", "weekly"):
            raise HTTPException(422, "Schedule must be off, daily or weekly")
        if "approved_localities" in d:
            d["approved_localities"] = [str(x).strip().lower() for x in d["approved_localities"] if str(x).strip()][:50]
        camp.settings = {**core.campaign_settings(camp), **d}
        mix = body.discovery.get("industry_mix")
        if isinstance(mix, dict) and set(mix) <= {EQUIPMENT, WHOLESALE} and all(isinstance(v, int) and 0 <= v <= 100 for v in mix.values()):
            camp.industry_mix = mix
    log_activity(db, "ioi3_settings", camp.id, "settings_updated", {"sections": [k for k in ("business", "discovery") if getattr(body, k)]}, who)
    db.commit()
    from app import jobs

    jobs.sync_ioi3_schedule()
    return read_settings(db)


@router.post("/onboarding/complete")
def onboarding_done(db: Session = DB, who: str = Depends(actor)):
    set_setting(db, "ioi3_onboarding_done", True)
    log_activity(db, "ioi3", None, "onboarding_completed", {}, who)
    db.commit()
    return {"ok": True}


@router.post("/ai/test")
def ai_test(db: Session = DB):
    from app.ai.openrouter import get_ai

    ai = get_ai(db)
    if ai is None:
        return {"ok": False, "message": "AI is not configured. Discovery and research work without it."}

    class Pong(BaseModel):
        ok: bool

    try:
        r = ai.complete_json("ioi3_ai_test", "Reply with {\"ok\": true}.", "ping", Pong, max_tokens=20)
        db.commit()
        return {"ok": bool(r.ok), "message": f"Connected to {ai.model_name}"}
    except Exception as exc:  # noqa: BLE001 — never echo secrets: message only
        db.commit()
        return {"ok": False, "message": f"AI test failed: {type(exc).__name__}: {str(exc)[:160]}"}


# ------------------------------------------------------------------------------------------------
# Home
# ------------------------------------------------------------------------------------------------
@router.get("/home")
def home(db: Session = DB):
    camp = core.active_campaign(db)
    base = select(Company).where(Company.campaign_id == camp.id, Company.archived.is_(False), Company.is_test.is_(False))
    live = [c for c in db.scalars(base.where(Company.review_status.in_(("new", "shortlisted", "approved", "watchlist"))))]
    qualified = [c for c in live if c.qualification in ("P0", "P1", "P2") and qualify.sales_ready(c.gates or [])]
    week = utcnow() - timedelta(days=7)
    new_signals = db.scalar(select(func.count()).select_from(Fact).join(Company).where(
        Company.campaign_id == camp.id, Company.archived.is_(False), Fact.kind == "signal", Fact.review_status != "rejected",
        Fact.observed_at >= week)) or 0
    t = sales.tasks(db, camp.id)
    rev = sales.revenue(db, camp.id)
    order = {"approved": 0, "shortlisted": 1}
    best = sorted([c for c in live if c.review_status in ("approved", "shortlisted")],
                  key=lambda c: (order[c.review_status], {"P0": 0, "P1": 1, "P2": 2}.get(c.qualification, 3), -c.score))[:5]
    last = db.scalar(select(Job).where(Job.campaign_id == camp.id).order_by(Job.id.desc()))
    recent = utcnow() - timedelta(days=30)
    strong = db.execute(select(Fact, Company.name).join(Company).where(
        Company.campaign_id == camp.id, Company.archived.is_(False), Fact.kind == "signal", Fact.review_status != "rejected",
        or_(Fact.review_status == "confirmed", Fact.published_at >= recent)).order_by(Fact.published_at.desc().nulls_last()).limit(5)).all()
    return {
        "engine": {"running": bool(last and last.status in engine.ACTIVE), "job": job_out(last) if last else None},
        "awaiting_approval": sum(1 for c in live if c.review_status == "shortlisted"),
        "strong_signals": [{"company_id": f.company_id, "company": name, "label": SIGNAL_LABEL.get(f.key or "", f.statement),
                            "date": f.published_at, "url": f.source_url, "confirmed": f.review_status == "confirmed"} for f, name in strong],
        "ai": {"configured": get_settings().ai_enabled},
        "stats": {"qualified": len(qualified), "new_signals": new_signals, "follow_ups_due": len(t["follow_ups_due"]),
                  "collected_this_month": rev["collected_this_month"]},
        "goal": _business(db)["revenue_goal_monthly"],
        "best": [card(c) for c in best], "tasks": t, "revenue": rev,
        "last_job": job_out(last) if last else None, "campaign": {"city": camp.city, "industries": camp.industries},
        "totals": {"companies": len(live)},
    }


# ------------------------------------------------------------------------------------------------
# Discover / jobs
# ------------------------------------------------------------------------------------------------
class JobIn(BaseModel):
    mode: str | None = Field(None, pattern="^(quick|balanced|deep)$")
    max_candidates: int | None = Field(None, ge=1, le=500)
    max_deep: int | None = Field(None, ge=0, le=100)


@router.get("/discover")
def discover(db: Session = DB):
    camp = core.active_campaign(db)
    jobs = db.scalars(select(Job).where(Job.campaign_id == camp.id).order_by(Job.id.desc()).limit(10)).all()
    news = db.scalars(select(RawItem).where(RawItem.campaign_id == camp.id, RawItem.outcome == "unmatched_news")
                      .order_by(RawItem.published_at.desc().nulls_last()).limit(15)).all()
    act = engine.active_job(db, camp.id)
    return {"settings": core.campaign_settings(camp), "preflight": engine.preflight(db, camp),
            "active": job_out(act) if act else None, "history": [job_out(j) for j in jobs],
            "market_news": [{"title": n.title, "url": n.source_url, "published_at": n.published_at,
                             "signals": [SIGNAL_LABEL.get(s, s) for s in (n.payload or {}).get("signals", [])]} for n in news]}


@router.post("/jobs", status_code=202)
def start(body: JobIn, db: Session = DB, who: str = Depends(actor)):
    camp = core.active_campaign(db)
    overrides = {k: v for k, v in body.model_dump().items() if k != "mode" and v is not None}
    try:
        job = engine.start_job(db, camp, mode=body.mode, overrides=overrides)
    except engine.JobConflict as exc:
        _err(exc, 409)
    except engine.ConfigError as exc:
        _err(exc, 422)
    log_activity(db, "ioi3_job", job.id, "discovery_started", {"mode": job.mode}, who)
    db.commit()
    return job_out(job)


@router.get("/jobs")
def job_history(limit: int = Query(20, ge=1, le=100), db: Session = DB):
    camp = core.active_campaign(db)
    return [job_out(j) for j in db.scalars(select(Job).where(Job.campaign_id == camp.id)
                                           .order_by(Job.id.desc()).limit(limit))]


@router.get("/jobs/{job_id}")
def job(job_id: int, db: Session = DB):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Run not found")
    return job_out(j)


@router.post("/jobs/{job_id}/stop")
def stop(job_id: int, db: Session = DB, who: str = Depends(actor)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Run not found")
    engine.request_stop(db, j)
    log_activity(db, "ioi3_job", j.id, "stop_requested", {}, who)
    db.commit()
    return job_out(j)


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(job_id: int, db: Session = DB, who: str = Depends(actor)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Run not found")
    if j.status in engine.ACTIVE:
        raise HTTPException(409, "This run is still in progress")
    failed = [k for k, v in (j.sources or {}).items() if v.get("status") == "failed"]
    camp = db.get(Campaign, j.campaign_id)
    try:
        new = engine.start_job(db, camp, mode=j.mode, trigger="retry", retry_of=j,
                               only_sources=failed if failed and j.status not in ("interrupted", "failed", "stopped") else None)
    except (engine.JobConflict, engine.ConfigError) as exc:
        _err(exc, 409)
    log_activity(db, "ioi3_job", new.id, "discovery_retry", {"retry_of": j.id, "sources": failed}, who)
    db.commit()
    return job_out(new)


# ------------------------------------------------------------------------------------------------
# Prospects
# ------------------------------------------------------------------------------------------------
TABS = ("ready", "strong", "watchlist", "verify", "approved", "excluded", "all")


def _tab_of(c: Company) -> set[str]:
    ready = qualify.sales_ready(c.gates or [])
    t = {"all"}
    if c.review_status == "shortlisted":
        t.add("ready")
    if c.review_status == "approved":
        t.add("approved")
    if c.qualification == "P3" or c.review_status in ("rejected", "duplicate"):
        t.add("excluded")
        return t
    if c.qualification in ("P0", "P1") or ready:
        t.add("strong")
    if c.review_status == "watchlist":
        t.add("watchlist")
    if not ready and c.review_status in ("new", "watchlist"):
        t.add("verify")
    return t


def _latest_signal_age(c: Company) -> float:
    dates = [f.published_at for f in c.facts if f.kind == "signal" and f.review_status != "rejected" and f.published_at]
    return -max(dates).timestamp() if dates else 0.0


@router.get("/companies")
def companies(
    tab: str = Query("ready", pattern="^(ready|strong|watchlist|verify|approved|excluded|all|high_fit|rejected)$"),
    industry: str | None = Query(None, pattern=f"^({EQUIPMENT}|{WHOLESALE})$"),
    qualification: str | None = Query(None, pattern="^P[0-3]$"),
    confidence: str | None = Query(None, pattern="^(verified|partial|unknown)$"),
    friction: str | None = Query(None, pattern="^(low|moderate|high|unknown)$"),
    signal_days: int | None = Query(None, ge=1, le=730),
    contact: bool | None = None,
    q: str | None = None,
    include_test: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    db: Session = DB,
):
    tab = {"high_fit": "strong", "rejected": "excluded"}.get(tab, tab)
    camp = core.active_campaign(db)
    stmt = select(Company).where(Company.campaign_id == camp.id, Company.archived.is_(False))
    if not include_test:
        stmt = stmt.where(Company.is_test.is_(False))
    if industry:
        stmt = stmt.where(Company.industry == industry)
    if qualification:
        stmt = stmt.where(Company.qualification == qualification)
    if confidence:
        stmt = stmt.where(Company.location_confidence == confidence)
    if friction:
        stmt = stmt.where(Company.friction == friction)
    if contact is not None:
        has = exists().where(CompanyContact.company_id == Company.id)
        stmt = stmt.where(has if contact else ~has)
    if signal_days:
        since = utcnow() - timedelta(days=signal_days)
        stmt = stmt.where(exists().where(and_(Fact.company_id == Company.id, Fact.kind == "signal", Fact.review_status != "rejected",
                                              Fact.published_at >= since)))
    if q:
        stmt = stmt.where(or_(Company.name.ilike(f"%{q}%"), Company.locality.ilike(f"%{q}%")))
    rows = [c for c in db.scalars(stmt.options(selectinload(Company.facts), selectinload(Company.contacts))) if tab in _tab_of(c)]
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    rows.sort(key=lambda c: (order.get(c.qualification, 9), not qualify.sales_ready(c.gates or []), _latest_signal_age(c), -c.score, c.id))
    return {"items": [card(c) for c in rows[offset: offset + limit]], "total": len(rows), "offset": offset, "limit": limit}


@router.get("/companies/counts")
def counts(db: Session = DB):
    camp = core.active_campaign(db)
    out = {t: 0 for t in TABS}
    for c in db.scalars(select(Company).where(Company.campaign_id == camp.id, Company.archived.is_(False), Company.is_test.is_(False))):
        for t in _tab_of(c):
            out[t] += 1
    return out


@router.get("/companies/{cid}")
def company(cid: int, db: Session = DB):
    return detail(db, _company(db, cid))


class ManualIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    industry: str | None = Field(None, pattern=f"^({EQUIPMENT}|{WHOLESALE})$")
    address: str | None = Field(None, max_length=1000)
    website: str | None = Field(None, max_length=2048)
    phone: str | None = Field(None, max_length=60)
    email: str | None = Field(None, max_length=300)
    source_url: str = Field(max_length=2048)
    location_evidence_url: str | None = Field(None, max_length=2048)
    note: str | None = Field(None, max_length=2000)


@router.post("/companies", status_code=201)
def add_company(body: ManualIn, db: Session = DB, who: str = Depends(actor)):
    camp = core.active_campaign(db)
    try:
        r = collect.add_manual(db, camp, body.model_dump())
    except ValueError as exc:
        _err(exc)
    if r.outcome != "accepted":
        msg = {"outside_chennai": f"Not added: {r.reason}", "wrong_industry": "Not added: not an equipment service or wholesale distribution business. "
               "Choose the industry if you know it is one.", "duplicate": f"Already in your list ({r.reason})."}.get(r.outcome, r.reason or r.outcome)
        raise HTTPException(422, msg)
    log_activity(db, "ioi3_company", r.company.id, "added_manually", {"name": r.company.name}, who)
    db.commit()
    return detail(db, _company(db, r.company.id))


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), source_url: str | None = Form(None), db: Session = DB, who: str = Depends(actor)):
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(413, "CSV is larger than 2 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        _err(ValueError("Save the CSV as UTF-8 and try again"))
    camp = core.active_campaign(db)
    try:
        stats = collect.import_csv(db, camp, text, default_source_url=source_url)
    except ValueError as exc:
        _err(exc)
    log_activity(db, "ioi3_import", None, "csv_imported", {k: v for k, v in stats.items() if k != "errors"}, who)
    db.commit()
    return stats


class ReviewIn(BaseModel):
    reason: str | None = Field(None, max_length=500)
    message: str | None = Field(None, max_length=6000)


@router.post("/companies/{cid}/approve")
def approve(cid: int, body: ReviewIn | None = None, db: Session = DB, who: str = Depends(actor)):
    c = _company(db, cid)
    try:
        sales.approve(db, c, who, (body.message if body else None))
    except sales.SalesError as exc:
        _err(exc)
    db.commit()
    return detail(db, c)


@router.post("/companies/{cid}/research")
def research_more(cid: int, db: Session = DB, who: str = Depends(actor)):
    """Research one business now (a few website pages; takes up to ~30 seconds)."""
    from app.http_client import SafeHttp
    from app.ioi3 import research

    c = _company(db, cid)
    http = SafeHttp(rate_limit_per_minute=20)
    try:
        research.research_company(db, c, http, deep=c.research_level != "directory")
    finally:
        http.close()
    sales.log(db, c, "note", "Researched further" + (f" — {c.research_error}" if c.research_error else ""), actor=who)
    db.commit()
    return detail(db, c)


@router.post("/companies/{cid}/review/{action}")
def review(cid: int, action: str, body: ReviewIn | None = None, db: Session = DB, who: str = Depends(actor)):
    status_for = {"watchlist": "watchlist", "reject": "rejected", "restore": "new", "shortlist": "shortlisted"}
    c = _company(db, cid)
    if action not in status_for:
        raise HTTPException(404, "Unknown action")
    try:
        sales.set_review(db, c, status_for[action], who, body.reason if body else None)
    except sales.SalesError as exc:
        _err(exc)
    db.commit()
    return detail(db, c)


class CompanyPatch(BaseModel):
    scope_confirmed: bool | None = None
    activity_evidence: str | None = Field(None, max_length=500)  # how the owner confirmed they're operating
    website: str | None = Field(None, max_length=2048)
    disqualifier: str | None = Field(None, max_length=1000)
    location_evidence_url: str | None = Field(None, max_length=2048)


@router.patch("/companies/{cid}")
def patch_company(cid: int, body: CompanyPatch, db: Session = DB, who: str = Depends(actor)):
    from app.normalize import domain_of

    c = _company(db, cid)
    data = body.model_dump(exclude_unset=True)
    if "website" in data:
        c.website = data["website"] or None
        c.domain = domain_of(c.website) if c.website else None
    if "disqualifier" in data:
        c.disqualifier = data["disqualifier"] or None
    if data.get("scope_confirmed") is not None:
        c.scope_confirmed = bool(data["scope_confirmed"])
    if data.get("activity_evidence"):
        c.activity = "active"
        core.add_fact(c, kind="activity", key="owner_confirmed", state="source_verified", detected_by="owner", reliability="high",
                      statement=f"Confirmed operating by {who}: {data['activity_evidence']}", source_name="Checked by you",
                      source_url=data["activity_evidence"] if data["activity_evidence"].startswith("http") else None)
    if data.get("location_evidence_url"):
        from app import chennai as _ch

        city = next((x for x in reversed(c.locations) if x.status == _ch.CHENNAI_CITY), None)
        if city is None:
            raise HTTPException(422, "The recorded address isn't a Chennai-city address — add the correct address first")
        v = _ch.classify_location(city.address, city.locality, city.pincode)
        core.add_location(c, address=city.address, verdict=v, basis="owner", evidence_url=data["location_evidence_url"])
        c.location_confidence = "verified"
        c.location_reason = f"{v.reason} (checked by {who} at {data['location_evidence_url']})"
    core.evaluate(c)
    sales.log(db, c, "note", "Details updated: " + ", ".join(data), actor=who)
    db.commit()
    return detail(db, c)


class FactIn(BaseModel):
    kind: str = Field(pattern="^(signal|problem|workflow|tools|note)$")
    statement: str = Field(min_length=5, max_length=1000)
    signal_type: str | None = None
    source_url: str | None = Field(None, max_length=2048)
    published_at: date | None = None
    buyer_confirmed: bool = False
    excerpt: str | None = Field(None, max_length=1500)


@router.post("/companies/{cid}/facts", status_code=201)
def add_fact(cid: int, body: FactIn, db: Session = DB, who: str = Depends(actor)):
    c = _company(db, cid)
    if body.kind == "signal":
        if body.signal_type not in SIGNAL_LABEL:
            raise HTTPException(422, "Choose what kind of signal this is")
        if not (body.source_url or "").startswith(("http://", "https://")):
            raise HTTPException(422, "A signal needs the link where you saw it")
        f = core.add_fact(c, kind="signal", key=body.signal_type, state="source_verified", review_status="confirmed",
                          statement=SIGNAL_LABEL[body.signal_type], excerpt=body.excerpt or body.statement, source_url=body.source_url,
                          source_name="Added by you", detected_by="owner", reliability="high",
                          published_at=datetime.combine(body.published_at, datetime.min.time()) if body.published_at else None)
    else:
        state = "buyer_confirmed" if body.buyer_confirmed else ("source_verified" if body.source_url else "inferred")
        f = core.add_fact(c, kind=body.kind, key=None if body.kind != "tools" else body.statement.lower()[:60], state=state,
                          statement=body.statement, excerpt=body.excerpt, source_url=body.source_url,
                          source_name="Buyer (recorded by you)" if body.buyer_confirmed else "Added by you",
                          detected_by="buyer" if body.buyer_confirmed else "owner", reliability="high" if body.buyer_confirmed else "medium")
    if f is None:
        raise HTTPException(409, "Already recorded")
    if f.review_status:
        f.reviewed_by = who
    core.evaluate(c)
    sales.log(db, c, "note", f"Added {body.kind}: {body.statement[:120]}", actor=who)
    db.commit()
    return detail(db, c)


class FactReview(BaseModel):
    decision: str = Field(pattern="^(confirmed|rejected|hypothesis)$")


@router.post("/facts/{fid}/review")
def review_fact(fid: int, body: FactReview, db: Session = DB, who: str = Depends(actor)):
    f = db.get(Fact, fid)
    if not f or f.kind != "signal":
        raise HTTPException(404, "Signal not found")
    f.review_status, f.reviewed_by = body.decision, who
    c = _company(db, f.company_id)
    core.evaluate(c)
    sales.log(db, c, "note", f"Signal '{f.statement}' {body.decision}", actor=who)
    db.commit()
    return detail(db, c)


# ------------------------------------------------------------------------------------------------
# Outreach
# ------------------------------------------------------------------------------------------------
@router.get("/outreach")
def outreach(channel: str | None = Query(None, pattern="^(b2b|social_commerce)$"), db: Session = DB):
    """Everything approved and waiting to be contacted, from every acquisition channel.

    Outreach is shared, so an approved social seller appears here beside an approved B2B company; each
    card carries its channel and its channel's own draft wording.
    """
    stmt = (select(Company).where(Company.archived.is_(False), Company.outreach_approved_at.is_not(None),
                                  Company.review_status != "rejected")
            .options(selectinload(Company.facts), selectinload(Company.contacts))
            .order_by(Company.next_follow_up_at.is_(None), Company.next_follow_up_at, Company.id))
    if channel:
        stmt = stmt.where(Company.channel == channel)
    rows = db.scalars(stmt).all()
    biz = _business(db)
    from app.ioi3 import recovery_intel

    reviews = recovery_intel.reviews_for(db, [x.id for c in rows for x in c.contacts])
    out = []
    for c in rows:
        last = db.scalar(select(Activity).where(Activity.company_id == c.id).order_by(Activity.occurred_at.desc()))
        deal = db.scalar(select(Deal).where(Deal.company_id == c.id))
        contacts = []
        for x in c.contacts:
            v = recovery_intel.contact_view(x, reviews.get(x.id))
            # A contact the owner rejected is never offered. Recovery leads show only usable business routes.
            if v["review"] == "rejected" or (c.lead_source == recovery_intel.LEAD_SOURCE and not v["usable"]):
                continue
            contacts.append({"kind": x.kind, "value": x.value, "official": x.official, "source_url": x.source_url,
                             "needs_review": v["needs_review"]})
        out.append({**card(c), "channel": c.channel, "lead_source": c.lead_source, "contacts": contacts,
                    "outreach": sales.draft(c, biz.get("sender_name", ""), biz.get("sender_link", "")),
                    "last_activity": {"kind": last.kind, "summary": last.summary, "at": last.occurred_at} if last else None,
                    "deal_stage": deal.stage if deal else None})
    return out


class DraftIn(BaseModel):
    message: str = Field(min_length=10, max_length=6000)


@router.put("/companies/{cid}/draft")
def save_draft(cid: int, body: DraftIn, db: Session = DB, who: str = Depends(actor)):
    c = _company(db, cid)
    sales.edit_draft(db, c, body.message, who)
    db.commit()
    return detail(db, c)


class ContactedIn(BaseModel):
    channel: str = Field(pattern="^(phone|email|whatsapp|in_person|other)$")
    note: str | None = Field(None, max_length=1000)
    follow_up_days: int | None = Field(3, ge=0, le=90)


@router.post("/companies/{cid}/contacted")
def contacted(cid: int, body: ContactedIn, db: Session = DB, who: str = Depends(actor)):
    c = _company(db, cid)
    try:
        sales.mark_contacted(db, c, who, body.channel, body.note, body.follow_up_days or None)
    except sales.SalesError as exc:
        _err(exc)
    db.commit()
    return detail(db, c)


class ReplyIn(BaseModel):
    summary: str = Field(min_length=2, max_length=2000)
    interested: bool | None = None
    buyer_problem: str | None = Field(None, max_length=500)


@router.post("/companies/{cid}/reply")
def reply(cid: int, body: ReplyIn, db: Session = DB, who: str = Depends(actor)):
    c = _company(db, cid)
    try:
        sales.record_reply(db, c, who, body.summary, body.interested, body.buyer_problem)
    except sales.SalesError as exc:
        _err(exc)
    db.commit()
    return detail(db, c)


class FollowUpIn(BaseModel):
    at: datetime
    note: str | None = Field(None, max_length=500)


@router.post("/companies/{cid}/follow-up")
def follow_up(cid: int, body: FollowUpIn, db: Session = DB, who: str = Depends(actor)):
    c = _company(db, cid)
    sales.schedule_follow_up(db, c, body.at.replace(tzinfo=None), who, body.note)
    db.commit()
    return detail(db, c)


@router.post("/companies/{cid}/to-pipeline")
def to_pipeline(cid: int, db: Session = DB, who: str = Depends(actor)):
    c = _company(db, cid)
    if c.outreach_approved_at is None:
        raise HTTPException(422, "Approve this business for outreach first")
    d = sales.ensure_deal(db, c)
    db.commit()
    return deal_out(d)


# ------------------------------------------------------------------------------------------------
# Sales pipeline
# ------------------------------------------------------------------------------------------------
@router.get("/pipeline")
def pipeline(channel: str | None = Query(None, pattern="^(b2b|social_commerce)$"), db: Session = DB):
    """The shared sales pipeline: deals from every acquisition channel, each tagged with its own.

    Approved leads from B2B discovery and from Social Commerce land in the same tables, so there is one
    place to see money. `channel` narrows it when you want only one pipeline.
    """
    stmt = (select(Deal).join(Company, Company.id == Deal.company_id)
            .options(selectinload(Deal.payments)).order_by(Deal.updated_at.desc()))
    if channel:
        stmt = stmt.where(Company.channel == channel)
    deals = db.scalars(stmt).all()
    camp_id = None
    if channel:
        camp_id = db.scalar(select(Campaign.id).where(Campaign.channel == channel, Campaign.status == "active")
                            .order_by(Campaign.id.desc()))
    return {"stages": [{"key": k, "label": v} for k, v in sales.STAGES],
            "outcomes": [{"key": k, "label": v} for k, v in sales.OUTCOMES.items()],
            "deals": [deal_out(d) for d in deals],
            "revenue": sales.revenue(db, camp_id), "goal": _business(db)["revenue_goal_monthly"]}


class DealPatch(BaseModel):
    contact_name: str | None = Field(None, max_length=200)
    confirmed_requirement: str | None = Field(None, max_length=4000)
    offer: str | None = Field(None, max_length=200)
    potential_amount: int | None = Field(None, ge=0)
    expected_payment_date: date | None = None
    delivery_status: str | None = Field(None, max_length=60)
    next_follow_up_at: datetime | None = None
    notes: str | None = Field(None, max_length=4000)


def _deal(db: Session, did: int) -> Deal:
    d = db.get(Deal, did)
    if not d:
        raise HTTPException(404, "Deal not found")
    return d


@router.patch("/deals/{did}")
def patch_deal(did: int, body: DealPatch, db: Session = DB, who: str = Depends(actor)):
    d = _deal(db, did)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v.replace(tzinfo=None) if isinstance(v, datetime) else v)
    if body.confirmed_requirement:
        core.add_fact(d.company, kind="problem", key="deal_requirement", state="buyer_confirmed", statement=body.confirmed_requirement[:500],
                      source_name="Buyer (recorded by you)", detected_by="buyer", reliability="high")
        core.evaluate(d.company)
    sales.log(db, d.company, "note", "Deal updated: " + ", ".join(body.model_dump(exclude_unset=True)), actor=who, deal=d)
    db.commit()
    return deal_out(d)


class StageIn(BaseModel):
    stage: str | None = None
    outcome: str | None = None
    outcome_reason: str | None = Field(None, max_length=300)  # why it was lost / declined, in the owner's words


@router.post("/deals/{did}/stage")
def stage(did: int, body: StageIn, db: Session = DB, who: str = Depends(actor)):
    d = _deal(db, did)
    try:
        if body.stage:
            sales.move(db, d, body.stage, who)
        if body.outcome is not None or (body.stage is None):
            sales.set_outcome(db, d, body.outcome or None, who, body.outcome_reason)
    except sales.SalesError as exc:
        _err(exc)
    db.commit()
    return deal_out(d)


class ProposalIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    scope: str | None = Field(None, max_length=6000)
    amount: int | None = Field(None, gt=0)
    sent: bool = True


@router.post("/deals/{did}/proposals", status_code=201)
def proposal(did: int, body: ProposalIn, db: Session = DB, who: str = Depends(actor)):
    d = _deal(db, did)
    try:
        sales.add_proposal(db, d, title=body.title, scope=body.scope, amount=body.amount, sent=body.sent, actor=who)
    except sales.SalesError as exc:
        _err(exc)
    db.commit()
    return deal_out(d)


class PaymentIn(BaseModel):
    amount: int = Field(gt=0)
    kind: str = Field(pattern="^(advance|milestone|final)$")
    received_on: date
    reference: str | None = Field(None, max_length=200)
    note: str | None = Field(None, max_length=1000)


@router.post("/deals/{did}/payments", status_code=201)
def payment(did: int, body: PaymentIn, db: Session = DB, who: str = Depends(actor)):
    d = _deal(db, did)
    try:
        sales.add_payment(db, d, amount=body.amount, kind=body.kind, received_on=body.received_on, reference=body.reference,
                          note=body.note, actor=who)
    except sales.SalesError as exc:
        _err(exc)
    db.commit()
    return deal_out(d)


# ------------------------------------------------------------------------------------------------
# Data management + advanced
# ------------------------------------------------------------------------------------------------
@router.get("/export/companies.csv")
def export_companies(db: Session = DB):
    camp = core.active_campaign(db)
    rows = db.scalars(select(Company).where(Company.campaign_id == camp.id, Company.archived.is_(False))
                      .options(selectinload(Company.contacts), selectinload(Company.facts))).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "name", "industry", "locality", "location_confidence", "qualification", "score", "friction", "review_status",
                "website", "phones", "emails", "offer", "next_action", "source_url"])
    for c in rows:
        w.writerow([c.id, c.name, c.industry, c.locality, c.location_confidence, c.qualification, c.score, c.friction, c.review_status,
                    c.website, "; ".join(x.value for x in c.contacts if x.kind == "phone"),
                    "; ".join(x.value for x in c.contacts if x.kind == "email"), (c.solution or {}).get("offer"), c.next_action, c.source_url])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="ioi-prospects-{date.today()}.csv"'})


LEGACY_TABLES = ("prospects", "business_chains", "project_leads", "opportunities", "organisations", "chennai_leads")


@router.get("/legacy")
def legacy(db: Session = DB):
    from sqlalchemy import text

    from app.reset import BACKUP_DIR

    counts = {t: db.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in LEGACY_TABLES}
    backups = sorted(BACKUP_DIR.glob("ioi-*.db"), reverse=True)
    return {"tables": counts, "note": "Archived data from earlier versions. Read-only; never loaded into the active campaign.",
            "backups": [{"name": b.name, "size_mb": round(b.stat().st_size / 1e6), "created": datetime.fromtimestamp(b.stat().st_mtime)}
                        for b in backups[:10]]}


@router.get("/legacy/{table}.csv")
def legacy_csv(table: str, db: Session = DB):
    from sqlalchemy import text

    if table not in LEGACY_TABLES:
        raise HTTPException(404, "Unknown archive table")

    def gen():
        res = db.execute(text(f'SELECT * FROM "{table}"'))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(res.keys())
        for i, row in enumerate(res):
            w.writerow(row)
            if i % 2000 == 0:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="legacy-{table}.csv"'})


@router.post("/backup")
def make_backup(db: Session = DB, who: str = Depends(actor)):
    from app.reset import backup

    try:
        m = backup(export_csv=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Backup failed: {exc}") from exc
    log_activity(db, "ioi3", None, "backup_created", {"file": m["backup"]}, who)
    db.commit()
    return {"ok": True, "file": m["backup"].rsplit("/", 1)[-1], "integrity": m["integrity"]}


@router.get("/campaign/reset-preview")
def reset_preview(db: Session = DB):
    camp = core.active_campaign(db)
    n = lambda stmt: db.scalar(select(func.count()).select_from(stmt.subquery())) or 0  # noqa: E731
    return {"campaign": camp.name, "companies": n(select(Company).where(Company.campaign_id == camp.id, Company.archived.is_(False))),
            "deals": n(select(Deal).where(Deal.campaign_id == camp.id)),
            "payments": n(select(Deal).join(Deal.payments).where(Deal.campaign_id == camp.id)),
            "what_happens": "The current campaign is archived (kept, read-only, still exportable) and a new empty campaign starts. Nothing is deleted.",
            "confirm_phrase": "START NEW CAMPAIGN"}


class ResetIn(BaseModel):
    confirm: str


@router.post("/campaign/reset")
def reset_campaign(body: ResetIn, db: Session = DB, who: str = Depends(actor)):
    if body.confirm.strip() != "START NEW CAMPAIGN":
        raise HTTPException(422, "Type START NEW CAMPAIGN to confirm")
    camp = core.active_campaign(db)
    if engine.active_job(db, camp.id):
        raise HTTPException(409, "Stop the running discovery first")
    camp.status, camp.archived_at = "archived", utcnow()
    db.query(Company).filter(Company.campaign_id == camp.id).update({Company.archived: True})
    db.commit()
    new = core.active_campaign(db)
    new.settings, new.industry_mix = dict(camp.settings or {}), dict(camp.industry_mix or {})
    log_activity(db, "ioi3_campaign", new.id, "campaign_reset", {"archived_campaign": camp.id}, who)
    db.commit()
    return {"ok": True, "archived_campaign": camp.id, "new_campaign": new.id}


@router.get("/sources")
def sources(db: Session = DB):
    camp = core.active_campaign(db)
    enabled = core.campaign_settings(camp).get("sources") or {}
    f = collect.overture_file()
    out = []
    for s in db.scalars(select(DiscoverySource).order_by(DiscoverySource.id)):
        out.append({"key": s.key, "name": s.name, "url": s.url, "category": s.category, "access_method": s.access_method,
                    "geo_coverage": s.geo_coverage, "industry_coverage": s.industry_coverage, "rate_limit_per_minute": s.rate_limit_per_minute,
                    "terms": s.terms, "description": s.description, "health": s.health, "last_success_at": s.last_success_at,
                    "last_error": s.last_error, "last_error_at": s.last_error_at, "failure_count": s.failure_count,
                    "last_records": s.last_records, "data_freshness": s.data_freshness,
                    "enabled": enabled.get(s.key, True) if s.key in enabled else True, "togglable": s.key in enabled})
    return {"sources": out, "overture_file": f.name if f else None}


@router.get("/diagnostics")
def diagnostics(db: Session = DB):
    from app import jobs
    from app.config import BACKEND_DIR

    s = get_settings()
    db_path = BACKEND_DIR / "data" / "ioi.db"
    return {"worker_alive": engine._thread is not None and engine._thread.is_alive(), "scheduler": jobs.scheduler_state(),
            "database_mb": round(db_path.stat().st_size / 1e6) if db_path.exists() else None, "discovery_scope": s.discovery_scope,
            "ai_configured": s.ai_enabled, "auth": "token" if s.api_token else "this computer only",
            "recent_events": [{"at": a.created_at, "actor": a.actor, "action": a.action, "entity": a.entity_type}
                              for a in db.scalars(select(ActivityLog).order_by(ActivityLog.id.desc()).limit(30))]}


@router.get("/sources/directory")
def directory_status(db: Session = DB):
    from app.models import ProspectRun

    files = sorted(collect.MAPS_DIR.glob("overture-india-*.parquet")) if collect.MAPS_DIR.is_dir() else []
    last = db.scalar(select(ProspectRun).where(ProspectRun.areas.cast(String).like("%Overture: download%")).order_by(ProspectRun.id.desc()))
    return {"files": [{"name": f.name, "size_mb": round(f.stat().st_size / 1e6), "modified": datetime.fromtimestamp(f.stat().st_mtime)} for f in files],
            "downloading": bool(last and last.status == "running"),
            "last_download": {"status": last.status, "log": last.log[-3:], "started_at": last.started_at} if last else None,
            "about": "Overture Maps places — open data (CDLA-Permissive-2.0). Downloading the India file takes 10–40 minutes and ~350 MB."}


@router.post("/sources/directory/download", status_code=202)
def directory_download(db: Session = DB, who: str = Depends(actor)):
    from app import jobs
    from app.models import ProspectRun

    running = db.scalar(select(ProspectRun).where(ProspectRun.status == "running", ProspectRun.areas.cast(String).like("%Overture: download%")))
    if running:
        raise HTTPException(409, "A download is already running")
    collect.MAPS_DIR.mkdir(parents=True, exist_ok=True)
    run = ProspectRun(areas=["Overture: download India"], status="running", log=[])
    db.add(run)
    log_activity(db, "ioi3_source", None, "directory_download", {}, who)
    db.commit()
    jobs.submit_overture(run.id, "download", folder=str(collect.MAPS_DIR))
    return {"ok": True, "message": "Download started. It runs in the background (10–40 minutes)."}


# ------------------------------------------------------------------------------------------------
# AI status, agent trace, research history
# ------------------------------------------------------------------------------------------------
def agent_events(db: Session, *, company_id: int | None = None, job_id: int | None = None, latest_session: bool = False,
                 limit: int = 200) -> list[dict]:
    from app.ioi3.models import AgentEvent

    stmt = select(AgentEvent)
    if company_id is not None:
        stmt = stmt.where(AgentEvent.company_id == company_id)
        if latest_session:
            last = db.scalar(select(AgentEvent.session).where(AgentEvent.company_id == company_id).order_by(AgentEvent.id.desc()))
            if last is None:
                return []
            stmt = stmt.where(AgentEvent.session == last)
    if job_id is not None:
        stmt = stmt.where(AgentEvent.job_id == job_id)
    rows = db.scalars(stmt.order_by(AgentEvent.id.desc()).limit(limit)).all()
    return [{"id": e.id, "session": e.session, "company_id": e.company_id, "job_id": e.job_id, "step": e.step, "kind": e.kind, "tool": e.tool,
             "args": e.args, "status": e.status, "message": e.message, "model": e.model, "duration_ms": e.duration_ms,
             "tokens_in": e.tokens_in, "tokens_out": e.tokens_out, "cost_usd": e.cost_usd, "at": e.created_at} for e in reversed(rows)]


@router.get("/ai/status")
def ai_status(db: Session = DB):
    from app.ioi3 import agent
    from app.models import AIUsageLog

    s = get_settings()
    base = select(AIUsageLog).where(AIUsageLog.task.like("ioi3_%"))
    last_ok = db.scalar(base.where(AIUsageLog.success.is_(True)).order_by(AIUsageLog.id.desc()))
    last_err = db.scalar(base.where(AIUsageLog.success.is_(False)).order_by(AIUsageLog.id.desc()))

    def totals(days: int) -> dict:
        since = utcnow() - timedelta(days=days)
        r = db.execute(select(func.count(), func.coalesce(func.sum(AIUsageLog.prompt_tokens), 0), func.coalesce(func.sum(AIUsageLog.completion_tokens), 0),
                              func.coalesce(func.sum(AIUsageLog.cost_usd), 0.0))
                       .where(AIUsageLog.task.like("ioi3_%"), AIUsageLog.success.is_(True), AIUsageLog.created_at >= since)).one()
        return {"calls": r[0], "tokens_in": int(r[1]), "tokens_out": int(r[2]), "cost_usd": round(float(r[3]), 4)}

    provider = "Claude (Anthropic)" if s.claude_enabled else "OpenRouter" if s.ai_enabled else None
    return {
        "configured": s.ai_enabled, "provider": provider, "model": s.ai_model_name,
        "agent_supported": s.ai_enabled and not s.claude_enabled,
        "note": None if s.ai_enabled and not s.claude_enabled else
                ("The research agent uses OpenRouter function calling; with only an Anthropic key, AI extraction works but the agent is off."
                 if s.claude_enabled else "AI unavailable — rule-based research active."),
        "last_success": {"at": last_ok.created_at, "task": last_ok.task, "model": last_ok.model} if last_ok else None,
        "last_error": {"at": last_err.created_at, "task": last_err.task, "error": (last_err.error or "")[:200]} if last_err else None,
        "fallback": "Rule-based research continues whenever AI is unavailable.",
        "usage_24h": totals(1), "usage_30d": totals(30),
        "limits": {k: v for k, v in agent.LIMITS.__dict__.items()},
    }


@router.get("/jobs/{job_id}/events")
def job_events(job_id: int, db: Session = DB):
    return agent_events(db, job_id=job_id, limit=300)


@router.get("/companies/{cid}/agent-events")
def company_events(cid: int, all_sessions: bool = False, db: Session = DB):
    return agent_events(db, company_id=cid, latest_session=not all_sessions)


@router.post("/companies/{cid}/ai-research")
def ai_research(cid: int, db: Session = DB, who: str = Depends(actor)):
    """Run the bounded AI research agent on one business now (takes up to ~2 minutes). Read-only; sends nothing."""
    from app.ioi3 import agent

    c = _company(db, cid)
    out = agent.investigate(db, c)
    sales.log(db, c, "note", f"AI research: {out.outcome} ({out.model_calls} AI calls, {out.facts} facts, {out.people} people)", actor=who)
    db.commit()
    return detail(db, _company(db, cid))


@router.get("/research")
def research_history(q: str | None = None, ai: str | None = Query(None, pattern="^(done|partial|unavailable|failed|not_run)$"),
                     offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=200), db: Session = DB):
    camp = core.active_campaign(db)
    stmt = select(Company).where(Company.campaign_id == camp.id, Company.archived.is_(False),
                                 or_(Company.research_level != "directory", Company.ai_status != "not_run", Company.researched_at.is_not(None)))
    if q:
        stmt = stmt.where(Company.name.ilike(f"%{q}%"))
    if ai:
        stmt = stmt.where(Company.ai_status == ai)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.options(selectinload(Company.facts), selectinload(Company.contacts), selectinload(Company.people))
                      .order_by(func.coalesce(Company.ai_researched_at, Company.researched_at).desc()).offset(offset).limit(limit)).all()
    jobs = db.scalars(select(Job).where(Job.campaign_id == camp.id).order_by(Job.id.desc()).limit(15)).all()
    return {"total": total, "items": [{**card(c), "people": len(c.people), "testimonials": sum(1 for f in c.facts if f.kind == "testimonial"),
                                       "research_error": c.research_error, "ai_researched_at": c.ai_researched_at,
                                       "agent_outcome": ((c.dossier or {}).get("agent") or {}).get("outcome")} for c in rows],
            "jobs": [job_out(j) for j in jobs]}
