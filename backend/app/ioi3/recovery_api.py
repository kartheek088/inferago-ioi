"""Website Recovery API (/api/v3/recovery). Auth is applied by main.py like every other protected router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.api.deps import DB
from app.ioi3 import website_recovery as wr

router = APIRouter(prefix="/v3/recovery", tags=["website-recovery"])


class CheckIn(BaseModel):
    company_ids: list[int] | None = Field(None, max_length=200)
    limit: int = Field(10, ge=1, le=wr.MAX_PER_RUN)
    force: bool = False


@router.get("/overview")
def overview(db: Session = DB):
    return wr.overview(db)


@router.get("/companies")
def companies(db: Session = DB, tab: str = Query("high_priority"), limit: int = Query(200, ge=1, le=500)):
    if tab not in wr.TABS:
        raise HTTPException(400, f"tab must be one of {', '.join(wr.TABS)}")
    return {"tab": tab, "items": wr.list_tab(db, tab, limit)}


@router.post("/check")
def check(body: CheckIn, db: Session = DB):
    """Runs a bounded batch of single-GET checks in this request. Recently checked sites are skipped unless forced."""
    return wr.run_checks(db, company_ids=body.company_ids, limit=body.limit, force=body.force)


@router.get("/companies/{company_id}")
def company_dossier(company_id: int, db: Session = DB):
    d = wr.dossier(db, company_id)
    if d is None:
        raise HTTPException(404, "not found")
    return d
