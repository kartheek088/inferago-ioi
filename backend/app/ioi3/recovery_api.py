"""Website Recovery API (/api/v3/recovery). Auth is applied by main.py like every other protected router.

Nothing here contacts a business. Evidence is recorded by the owner; outreach stays in the normal approval flow.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import DB, actor
from app.ioi3 import recovery_intel as intel
from app.ioi3 import website_recovery as wr
from app.ioi3.models import ActivityEvidence, Company
from app.settings_store import set_setting

router = APIRouter(prefix="/v3/recovery", tags=["website-recovery"])


class CheckIn(BaseModel):
    company_ids: list[int] | None = Field(None, max_length=200)
    limit: int = Field(10, ge=1, le=wr.MAX_PER_RUN)
    force: bool = False


class EvidenceIn(BaseModel):
    kind: Literal["phone_call", "official_social", "marketplace_listing", "official_website", "news", "other", "confirmed_need"]
    signal: Literal["active", "inactive", "closed"] = "active"
    statement: str = Field(..., min_length=3, max_length=500)
    source_url: str | None = Field(None, max_length=2048)
    published_on: date | None = None
    observed_on: date | None = None
    confirms_chennai: bool = False


class ReviewIn(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(None, max_length=200)


class ScopeIn(BaseModel):
    categories: list[str] | None = Field(None, max_length=200)  # None = every business type in the campaign industries
    window_days: Literal[30, 60, 90, 180] = 90


@router.get("/overview")
def overview(db: Session = DB):
    return intel.overview(db)


@router.get("/companies")
def companies(db: Session = DB, tab: str = Query("high_priority"), limit: int = Query(200, ge=1, le=500)):
    if tab not in intel.BUCKETS:
        raise HTTPException(400, f"tab must be one of {', '.join(intel.BUCKETS)}")
    return {"tab": tab, "items": [r for r in intel.board(db) if r["bucket"] == tab][:limit]}


@router.post("/check")
def check(body: CheckIn, db: Session = DB):
    """Runs a bounded batch of single-GET checks in this request. Recently checked sites are skipped unless forced."""
    return wr.run_checks(db, company_ids=body.company_ids, limit=body.limit, force=body.force)


@router.get("/companies/{company_id}")
def company_dossier(company_id: int, db: Session = DB):
    d = intel.dossier(db, company_id)
    if d is None:
        raise HTTPException(404, "not found")
    return d


@router.post("/companies/{company_id}/evidence", status_code=201)
def add_evidence(company_id: int, body: EvidenceIn, db: Session = DB, who: str = Depends(actor)):
    try:
        e = intel.add_evidence(db, company_id, actor=who, **body.model_dump())
    except LookupError:
        raise HTTPException(404, "not found") from None
    except intel.EvidenceError as exc:
        raise HTTPException(422, str(exc)) from None
    return intel.evidence_out(e)


@router.delete("/evidence/{evidence_id}", status_code=204)
def delete_evidence(evidence_id: int, db: Session = DB):
    """Retention control: the owner can remove any evidence row they recorded."""
    e = db.get(ActivityEvidence, evidence_id)
    if e is None:
        raise HTTPException(404, "not found")
    db.delete(e)
    db.commit()


@router.post("/contacts/{contact_id}/review")
def review_contact(contact_id: int, body: ReviewIn, db: Session = DB, who: str = Depends(actor)):
    """The owner confirms a flagged contact is the business's line (or marks it not to be used)."""
    try:
        return intel.review_contact(db, contact_id, decision=body.decision, note=body.note, actor=who)
    except LookupError:
        raise HTTPException(404, "not found") from None
    except intel.EvidenceError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/companies/{company_id}/alternatives")
def look_for_newer_site(company_id: int, db: Session = DB):
    c = db.get(Company, company_id)
    if c is None or c.channel != wr.B2B:
        raise HTTPException(404, "not found")
    db.rollback()  # no transaction open during the requests
    http = wr.SafeHttp(respect_robots=True, rate_limit_per_minute=20, max_bytes=2_000_000)
    return {"results": intel.find_alternatives(company_id, http)}


@router.get("/scope")
def get_scope(db: Session = DB):
    return {**intel.get_scope(db), "available": intel.categories(db)}


@router.put("/scope")
def put_scope(body: ScopeIn, db: Session = DB):
    known = {c["category"] for c in intel.categories(db)}
    if body.categories is not None:
        unknown = sorted(set(body.categories) - known)
        if unknown:
            raise HTTPException(422, f"Unknown business types: {', '.join(unknown[:5])}")
    set_setting(db, intel.SCOPE_KEY, {"categories": body.categories, "window_days": body.window_days})
    db.commit()
    return {**intel.get_scope(db), "available": intel.categories(db)}
