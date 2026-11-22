"""Multi-branch (regional) businesses: list, search, log contacts."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import jobs
from app.api.deps import NATIONWIDE, DB, Paging, actor, paginate
from app.db import utcnow
from app.models import BusinessChain, ProspectRun
from app.schemas import ChainContactIn, ChainOut, ChainUpdate, Page, ProspectRunOut
from app.settings_store import log_activity

router = APIRouter(tags=["chains"])
OPEN = ("new", "shortlisted", "contacted", "no_answer", "callback", "interested", "qualified", "proposal")


def _get(db: Session, cid: int) -> BusinessChain:
    c = db.get(BusinessChain, cid)
    if not c:
        raise HTTPException(404, "Not found")
    return c


@router.get("/multi-branch", response_model=Page[ChainOut])
def list_chains(q: str | None = None, state: str | None = None, has_website: bool | None = None, min_branches: int | None = None,
                evidence: str | None = Query(None, pattern="^(shared_contact|same_name_one_state)$"), status: str | None = None,
                paging: Paging = Depends(), db: Session = DB):
    stmt = select(BusinessChain)
    if q:
        stmt = stmt.where(or_(BusinessChain.name.ilike(f"%{q}%"), BusinessChain.type_label.ilike(f"%{q}%")))
    if state:
        stmt = stmt.where(BusinessChain.main_state.is_(None) if state == "unknown" else BusinessChain.main_state == state)
    if has_website is not None:
        stmt = stmt.where(BusinessChain.has_website.is_(has_website))
    if min_branches:
        stmt = stmt.where(BusinessChain.branch_count >= min_branches)
    if evidence:
        stmt = stmt.where(BusinessChain.evidence == evidence)
    if status in (None, "", "open"):
        stmt = stmt.where(BusinessChain.status.in_(OPEN))
    elif status != "all":
        stmt = stmt.where(BusinessChain.status == status)
    items, total = paginate(db, stmt.order_by(BusinessChain.score.desc(), BusinessChain.branch_count.desc()), paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/multi-branch/summary")
def chains_summary(db: Session = DB):
    open_q = BusinessChain.status.in_(OPEN)
    return {
        "total": db.scalar(select(func.count(BusinessChain.id)).where(open_q)) or 0,
        "no_website": db.scalar(select(func.count(BusinessChain.id)).where(open_q, BusinessChain.has_website.is_(False))) or 0,
        "branches": db.scalar(select(func.sum(BusinessChain.branch_count)).where(open_q)) or 0,
        "strong": db.scalar(select(func.count(BusinessChain.id)).where(open_q, BusinessChain.evidence == "shared_contact")) or 0,
        "by_state": {k or "unknown": v for k, v in db.execute(select(BusinessChain.main_state, func.count()).where(open_q)
                                                               .group_by(BusinessChain.main_state).order_by(func.count().desc())).all()},
    }


@router.post("/multi-branch/find", response_model=ProspectRunOut, status_code=202, dependencies=NATIONWIDE)
def find_chains(db: Session = DB, who: str = Depends(actor)):
    from app.api.prospects import _busy, map_folders

    files = sorted(map_folders()["maps"].glob("overture-*.parquet"))
    if not files:
        raise HTTPException(404, "Download the business directory first (Prospects → Find prospects → Business directory).")
    _busy(db)
    run = ProspectRun(areas=[f"Overture (multi-branch): {files[-1].name}"], status="running", log=[])
    db.add(run)
    log_activity(db, "chains", None, "search_started", {"file": files[-1].name}, who)
    db.commit()
    jobs.submit_chains(run.id, str(files[-1]))
    db.refresh(run)
    return run


@router.patch("/multi-branch/{cid}", response_model=ChainOut)
def update_chain(cid: int, body: ChainUpdate, db: Session = DB, who: str = Depends(actor)):
    c = _get(db, cid)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(c, k, v)
    log_activity(db, "chain", c.id, "updated", {k: str(v) for k, v in data.items()}, who)
    db.commit()
    return c


@router.post("/multi-branch/{cid}/contact", response_model=ChainOut)
def log_chain_contact(cid: int, body: ChainContactIn, db: Session = DB, who: str = Depends(actor)):
    c = _get(db, cid)
    now = utcnow()
    c.contact_log = [*(c.contact_log or []), {"at": now.isoformat(), "channel": body.channel, "outcome": body.outcome, "note": body.note, "by": who}]
    c.last_contacted_at, c.status = now, body.outcome
    days = {"contacted": 3, "no_answer": 1, "interested": 2, "qualified": 2, "proposal": 3}.get(body.outcome)
    c.next_follow_up = body.callback_at if body.outcome == "callback" else (now + timedelta(days=days) if days else None)
    log_activity(db, "chain", c.id, "contact_logged", body.model_dump(mode="json"), who)
    db.commit()
    return c
