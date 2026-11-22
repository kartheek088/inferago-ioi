"""Chennai leads: list/filter, owner review, selective research, signals, brief and outreach approval.

Nothing here sends anything. "Approve outreach" records the owner's decision; the owner contacts
the company themselves and then marks it contacted.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, cast, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import jobs, leads, lead_rules
from app.api.deps import DB, NATIONWIDE, Paging, actor, paginate
from app.config import BACKEND_DIR, get_settings
from app.db import utcnow
from app.models import ChennaiLead, LeadSignal, ProspectRun
from app.settings_store import get_setting, log_activity

router = APIRouter(tags=["chennai leads"])
MAPS_DIR = BACKEND_DIR / "data" / "maps"
OPEN = ("new", "reviewing", "approved")


# --- Schemas -------------------------------------------------------------------------------------
class SignalOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    lead_id: int | None
    signal_type: str
    strength: str
    title: str | None
    excerpt: str
    url: str
    source_name: str | None
    published_at: datetime | None
    detected_by: str
    review_status: str
    reviewed_by: str | None
    created_at: datetime


class LeadOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    name: str
    industry: str | None
    industry_strength: str
    industry_subtype: str | None
    industry_reasons: list[str]
    directory_category: str | None
    address: str | None
    locality: str | None
    pincode: str | None
    location_status: str
    location_verified: bool
    location_basis: str | None
    location_evidence_url: str | None
    website: str | None
    phones: list[dict[str, Any]]
    emails: list[dict[str, Any]]
    activity_status: str
    activity_evidence: str | None
    operations: list[dict[str, Any]]
    branch_count: int | None
    eligibility_blocker: str | None
    source: str
    source_url: str
    category: str
    category_reasons: list[str]
    sales_difficulty: str
    difficulty_reasons: list[str]
    evidence_confidence: str
    potential_problem: str | None
    suggested_solution: str | None
    suggested_services: list[str]
    next_action: str | None
    status: str
    duplicate_of_id: int | None
    outreach_approved_by: str | None
    outreach_approved_at: datetime | None
    notes: str | None
    website_checked_at: datetime | None
    website_check_error: str | None
    last_verified_at: datetime | None
    created_at: datetime
    signals: list[SignalOut] = []


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int
    limit: int
    offset: int


class LeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    industry: str | None = Field(None, pattern=f"^({lead_rules.WHOLESALE}|{lead_rules.EQUIPMENT})$")
    address: str | None = Field(None, max_length=1000)
    website: str | None = Field(None, max_length=2048)
    phone: str | None = Field(None, max_length=60)
    email: str | None = Field(None, max_length=300)
    source_url: str | None = Field(None, max_length=2048, description="Where you found this company")
    location_evidence_url: str | None = Field(None, max_length=2048, description="Official page showing the Chennai address")
    contact_source_url: str | None = Field(None, max_length=2048, description="Official page where the phone/email is published")
    notes: str | None = Field(None, max_length=4000)


class LeadUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(new|reviewing|approved|contacted|rejected|duplicate)$")
    notes: str | None = Field(None, max_length=4000)
    eligibility_blocker: str | None = Field(None, max_length=1000)
    outreach_draft: str | None = Field(None, max_length=8000)
    location_verified_url: str | None = Field(None, max_length=2048, description="Owner checked the address at this URL")


class SignalIn(BaseModel):
    signal_type: str
    url: str = Field(max_length=2048)
    excerpt: str = Field(min_length=10, max_length=2000)
    published_at: datetime | None = None
    title: str | None = Field(None, max_length=500)


class SignalReview(BaseModel):
    decision: str = Field(pattern="^(confirmed|rejected|hypothesis)$")
    lead_id: int | None = None


class RunIn(BaseModel):
    max_keep: int = Field(2000, ge=10, le=10000)
    limit: int = Field(25, ge=1, le=200)


class RunOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    areas: list[str]
    status: str
    found: int
    new: int
    updated: int
    log: list[str]
    started_at: datetime
    finished_at: datetime | None


# --- Helpers ---------------------------------------------------------------------------------------
def _get(db: Session, lid: int) -> ChennaiLead:
    lead = db.scalar(select(ChennaiLead).where(ChennaiLead.id == lid).options(selectinload(ChennaiLead.signals)))
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


def _contact_filter():
    return or_(func.json_array_length(ChennaiLead.phones) > 0, func.json_array_length(ChennaiLead.emails) > 0)


def _official_contact_filter():
    return or_(cast(ChennaiLead.phones, String).like('%"official": true%'), cast(ChennaiLead.emails, String).like('%"official": true%'))


def overture_file() -> Path | None:
    files = sorted(MAPS_DIR.glob("overture-india-*.parquet"))
    return files[-1] if files else None


def _start_run(db: Session, what: str) -> ProspectRun:
    running = db.scalar(select(ProspectRun).where(ProspectRun.status.in_(("running", "stopping")),
                                                 cast(ProspectRun.areas, String).like(f"%{leads.RUN_LABEL}%")))
    if running:
        raise HTTPException(409, f"A Chennai lead job is already running (#{running.id})")
    run = ProspectRun(areas=[f"{leads.RUN_LABEL}: {what}"], status="running", log=[])
    db.add(run)
    db.commit()
    return run


# --- Lists -----------------------------------------------------------------------------------------
@router.get("/leads", response_model=LeadPage)
def list_leads(
    q: str | None = None,
    category: str | None = Query(None, pattern="^[ABCD](,[ABCD])*$"),
    industry: str | None = Query(None, pattern=f"^({lead_rules.WHOLESALE}|{lead_rules.EQUIPMENT})$"),
    difficulty: str | None = Query(None, pattern="^(easier|moderate|difficult|unknown)$"),
    confidence: str | None = Query(None, pattern="^(high|medium|low)$"),
    status: str | None = None,
    verified: bool | None = None,
    has_contact: bool | None = None,
    official_contact: bool | None = None,
    signal_days: int | None = Query(None, ge=1, le=730, description="has a non-rejected signal dated within N days"),
    ready: bool = False,
    sort: str = Query("best", pattern="^(best|recent|name)$"),
    paging: Paging = Depends(),
    db: Session = DB,
):
    stmt = select(ChennaiLead).options(selectinload(ChennaiLead.signals))
    if q:
        stmt = stmt.where(or_(ChennaiLead.name.ilike(f"%{q}%"), ChennaiLead.address.ilike(f"%{q}%"), ChennaiLead.locality.ilike(f"%{q}%")))
    if category:
        stmt = stmt.where(ChennaiLead.category.in_(category.split(",")))
    elif not status:
        stmt = stmt.where(ChennaiLead.category != "D")
    if industry:
        stmt = stmt.where(ChennaiLead.industry == industry)
    if difficulty:
        stmt = stmt.where(ChennaiLead.sales_difficulty == difficulty)
    if confidence:
        stmt = stmt.where(ChennaiLead.evidence_confidence == confidence)
    if status:
        stmt = stmt.where(ChennaiLead.status == status)
    elif not category or "D" not in category:
        stmt = stmt.where(ChennaiLead.status != "duplicate")
    if verified is not None:
        stmt = stmt.where(ChennaiLead.location_verified.is_(verified))
    if has_contact is not None:
        stmt = stmt.where(_contact_filter() if has_contact else ~_contact_filter())
    if official_contact:
        stmt = stmt.where(_official_contact_filter())
    if signal_days:
        since = utcnow() - timedelta(days=signal_days)
        stmt = stmt.where(exists().where(and_(LeadSignal.lead_id == ChennaiLead.id, LeadSignal.review_status != "rejected",
                                              LeadSignal.published_at >= since)))
    if ready:  # ready-for-review outreach list
        stmt = stmt.where(ChennaiLead.category.in_(("A", "B")), ChennaiLead.status.in_(("new", "reviewing", "approved")), _contact_filter())
    order = {"best": (ChennaiLead.category, ChennaiLead.prescore.desc(), ChennaiLead.id),
             "recent": (ChennaiLead.updated_at.desc(),), "name": (ChennaiLead.name,)}[sort]
    items, total = paginate(db, stmt.order_by(*order), paging)
    return LeadPage(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/leads/summary")
def summary(db: Session = DB):
    def count(*where) -> int:
        return db.scalar(select(func.count()).select_from(ChennaiLead).where(*where)) or 0

    not_dup = ChennaiLead.status != "duplicate"
    since = utcnow() - timedelta(days=90)
    f = overture_file()
    last = db.scalars(select(ProspectRun).where(cast(ProspectRun.areas, String).like(f"%{leads.RUN_LABEL}%")).order_by(ProspectRun.id.desc()).limit(5)).all()
    return {
        "scope": "Chennai city only" if get_settings().chennai_only else "All (nationwide discovery enabled)",
        "chennai_only": get_settings().chennai_only,
        "total": count(not_dup),
        "by_category": {c: count(ChennaiLead.category == c, not_dup) for c in "ABCD"},
        "by_industry": {i: count(ChennaiLead.industry == i, ChennaiLead.category != "D", not_dup) for i in (lead_rules.WHOLESALE, lead_rules.EQUIPMENT)},
        "by_difficulty": {d: count(ChennaiLead.sales_difficulty == d, ChennaiLead.category != "D", not_dup) for d in ("easier", "moderate", "difficult", "unknown")},
        "verified_location": count(ChennaiLead.location_verified.is_(True), not_dup),
        "official_contact": count(_official_contact_filter(), ChennaiLead.category != "D", not_dup),
        "websites_checked": count(ChennaiLead.website_checked_at.is_not(None)),
        "websites_pending": count(ChennaiLead.website.is_not(None), ChennaiLead.website_checked_at.is_(None), ChennaiLead.category != "D", not_dup),
        "recent_signals": db.scalar(select(func.count()).select_from(LeadSignal).where(LeadSignal.lead_id.is_not(None),
                                    LeadSignal.review_status != "rejected", LeadSignal.published_at >= since)) or 0,
        "signals_to_review": db.scalar(select(func.count()).select_from(LeadSignal).where(LeadSignal.review_status == "hypothesis")) or 0,
        "market_news": db.scalar(select(func.count()).select_from(LeadSignal).where(LeadSignal.lead_id.is_(None), LeadSignal.review_status != "rejected")) or 0,
        "ready_for_review": count(ChennaiLead.category.in_(("A", "B")), ChennaiLead.status.in_(("new", "reviewing", "approved")), _contact_filter()),
        "approved": count(ChennaiLead.status == "approved"),
        "contacted": count(ChennaiLead.status == "contacted"),
        "source_file": f.name if f else None,
        "approved_localities": get_setting(db, "chennai_approved_localities") or [],
        "runs": [RunOut.model_validate(r).model_dump() for r in last],
    }


@router.get("/lead-signals", response_model=list[SignalOut])
def list_signals(unmatched: bool = False, review_status: str | None = Query(None, pattern="^(hypothesis|confirmed|rejected)$"),
                 days: int = Query(90, ge=1, le=730), db: Session = DB):
    stmt = select(LeadSignal).order_by(LeadSignal.published_at.desc().nulls_last(), LeadSignal.id.desc()).limit(200)
    stmt = stmt.where(LeadSignal.lead_id.is_(None) if unmatched else LeadSignal.lead_id.is_not(None))
    if review_status:
        stmt = stmt.where(LeadSignal.review_status == review_status)
    else:
        stmt = stmt.where(LeadSignal.review_status != "rejected")
    stmt = stmt.where(or_(LeadSignal.published_at.is_(None), LeadSignal.published_at >= utcnow() - timedelta(days=days)))
    return list(db.scalars(stmt))


@router.get("/leads/runs", response_model=list[RunOut])
def runs(db: Session = DB):
    return list(db.scalars(select(ProspectRun).where(cast(ProspectRun.areas, String).like(f"%{leads.RUN_LABEL}%")).order_by(ProspectRun.id.desc()).limit(10)))


# --- Pipeline runs (manual, bounded) -------------------------------------------------------------
@router.post("/leads/collect", response_model=RunOut, status_code=202, dependencies=NATIONWIDE)
def collect(body: RunIn, db: Session = DB, who: str = Depends(actor)):
    f = overture_file()
    if not f:
        raise HTTPException(409, "No Overture file in backend/data/maps. Download it first (Prospects → Overture download).")
    run = _start_run(db, f"collect from {f.name}")
    log_activity(db, "leads", None, "collect_started", {"file": f.name, "max_keep": body.max_keep}, who)
    db.commit()
    jobs.submit_leads(run.id, "collect", path=str(f), max_keep=body.max_keep)
    return run


@router.post("/leads/research", response_model=RunOut, status_code=202, dependencies=NATIONWIDE)
def research(body: RunIn, db: Session = DB, who: str = Depends(actor)):
    run = _start_run(db, f"check top {body.limit} websites")
    log_activity(db, "leads", None, "research_started", {"limit": body.limit}, who)
    db.commit()
    jobs.submit_leads(run.id, "research", limit=body.limit)
    return run


@router.post("/leads/news", response_model=RunOut, status_code=202, dependencies=NATIONWIDE)
def news(db: Session = DB, who: str = Depends(actor)):
    run = _start_run(db, "news")
    log_activity(db, "leads", None, "news_scan_started", {}, who)
    db.commit()
    jobs.submit_leads(run.id, "news")
    return run


@router.post("/leads/runs/{run_id}/stop", response_model=RunOut)
def stop(run_id: int, db: Session = DB):
    run = db.get(ProspectRun, run_id)
    if not run or leads.RUN_LABEL not in " ".join(run.areas or []):
        raise HTTPException(404, "Run not found")
    if run.status == "running":
        run.status = "stopping"
        db.commit()
    return run


@router.get("/reset/preview", tags=["reset"])
def reset_preview(db: Session = DB):
    """Read-only: what the data reset would delete. Executing it is only possible from the command line."""
    from app.reset import preview

    conn = db.connection()
    out = preview(conn).as_dict()
    db.rollback()
    out["how_to_execute"] = "Command line only: uv run python -m app.reset backup, then execute with --backup and --confirm."
    return out


# --- One lead --------------------------------------------------------------------------------------
@router.post("/leads", response_model=LeadOut, status_code=201)
def create(body: LeadIn, db: Session = DB, who: str = Depends(actor)):
    try:
        lead = leads.add_manual_lead(db, body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_activity(db, "chennai_lead", lead.id, "created_manually", {"name": lead.name}, who)
    db.commit()
    return _get(db, lead.id)


@router.get("/leads/{lid}", response_model=LeadOut)
def get_lead(lid: int, db: Session = DB):
    return _get(db, lid)


@router.patch("/leads/{lid}", response_model=LeadOut)
def update(lid: int, body: LeadUpdate, db: Session = DB, who: str = Depends(actor)):
    lead = _get(db, lid)
    data = body.model_dump(exclude_unset=True)
    url = data.pop("location_verified_url", None)
    if url:
        if lead.location_status != "chennai_city":
            raise HTTPException(422, "The recorded address is not a Chennai-city address; fix the address first")
        lead.location_verified, lead.location_evidence_url = True, url
        lead.location_basis = f"Checked by {who} on {utcnow():%d %b %Y} at {url}. {lead.location_basis or ''}"
    if "outreach_draft" in data and data["outreach_draft"] != lead.outreach_draft:
        lead.outreach_approved_by = lead.outreach_approved_at = None  # editing invalidates an approval
        if lead.status == "approved":
            lead.status = "reviewing"
    for k, v in data.items():
        setattr(lead, k, v)
    leads.evaluate(lead)
    log_activity(db, "chennai_lead", lead.id, "updated", {k: (v if k != "outreach_draft" else "…") for k, v in data.items()}, who)
    db.commit()
    return _get(db, lid)


@router.post("/leads/{lid}/verify-website", response_model=LeadOut)
def verify(lid: int, db: Session = DB, who: str = Depends(actor)):
    lead = _get(db, lid)
    leads.verify_website(db, lead)
    log_activity(db, "chennai_lead", lead.id, "website_verified", {"error": lead.website_check_error}, who)
    db.commit()
    return _get(db, lid)


@router.post("/leads/{lid}/signals", response_model=SignalOut, status_code=201)
def add_signal(lid: int, body: SignalIn, db: Session = DB, who: str = Depends(actor)):
    lead = _get(db, lid)
    try:
        sig = leads.add_signal(db, lead, signal_type=body.signal_type, url=body.url, excerpt=body.excerpt,
                               published_at=body.published_at, title=body.title, actor=who)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_activity(db, "chennai_lead", lead.id, "signal_added", {"type": body.signal_type, "url": body.url}, who)
    db.commit()
    return sig


@router.post("/lead-signals/{sid}/review", response_model=SignalOut)
def review(sid: int, body: SignalReview, db: Session = DB, who: str = Depends(actor)):
    sig = db.get(LeadSignal, sid)
    if not sig:
        raise HTTPException(404, "Signal not found")
    lead = _get(db, body.lead_id) if body.lead_id else None
    if lead is not None and sig.lead_id not in (None, lead.id):
        raise HTTPException(422, "Signal already belongs to another lead")
    leads.review_signal(db, sig, body.decision, who, lead)
    log_activity(db, "lead_signal", sig.id, f"signal_{body.decision}", {"lead_id": sig.lead_id}, who)
    db.commit()
    return sig


@router.get("/leads/{lid}/brief")
def get_brief(lid: int, db: Session = DB):
    lead = _get(db, lid)
    return leads.brief(lead, str(get_setting(db, "sender_name") or ""), str(get_setting(db, "sender_link") or ""))


@router.post("/leads/{lid}/approve-outreach", response_model=LeadOut)
def approve(lid: int, db: Session = DB, who: str = Depends(actor)):
    """Record the owner's approval of the draft. Nothing is sent; the owner contacts them personally."""
    lead = _get(db, lid)
    if lead.category not in ("A", "B"):
        raise HTTPException(422, "Only Category A or B leads can be approved for outreach")
    if not (lead.phones or lead.emails):
        raise HTTPException(422, "No public contact route recorded")
    if not lead.outreach_draft:
        lead.outreach_draft = leads.brief(lead)["outreach_draft"]
    lead.outreach_approved_by, lead.outreach_approved_at, lead.status = who, utcnow(), "approved"
    log_activity(db, "chennai_lead", lead.id, "outreach_approved", {}, who)
    db.commit()
    return _get(db, lid)


@router.post("/leads/{lid}/mark-contacted", response_model=LeadOut)
def mark_contacted(lid: int, db: Session = DB, who: str = Depends(actor)):
    lead = _get(db, lid)
    if lead.status != "approved":
        raise HTTPException(422, "Approve the outreach first")
    lead.status = "contacted"
    log_activity(db, "chennai_lead", lead.id, "contacted_manually", {}, who)
    db.commit()
    return _get(db, lid)
