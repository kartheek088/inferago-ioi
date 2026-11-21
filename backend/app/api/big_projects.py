"""Big projects from public business news (vendor / delivery-partner leads)."""

import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import DB, Paging, actor, paginate
from app.big_projects import DEFAULT_FEEDS, TN_PLACES, TYPE_LABEL, approach, run_project_search
from app.models import ProjectLead
from app.schemas import Page, ProjectLeadOut, ProjectLeadUpdate
from app.settings_store import get_setting, log_activity, set_setting

router = APIRouter(tags=["big-projects"])
_lock = threading.Lock()
TN_LOCATIONS = [p.title() for p in TN_PLACES]  # analyse() stores locations title-cased


def _get(db: Session, lid: int) -> ProjectLead:
    lead = db.get(ProjectLead, lid)
    if not lead:
        raise HTTPException(404, "Project not found")
    return lead


@router.get("/big-projects", response_model=Page[ProjectLeadOut])
def list_projects(
    q: str | None = None,
    project_type: str | None = Query(None, pattern="^(contract_won|new_facility|investment|mou)$"),
    near: str | None = Query(None, pattern="^(tamil_nadu|india)$"),
    status: str | None = None,
    paging: Paging = Depends(),
    db: Session = DB,
):
    stmt = select(ProjectLead)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(ProjectLead.title.ilike(like), ProjectLead.company.ilike(like)))
    if project_type:
        stmt = stmt.where(ProjectLead.project_type == project_type)
    if near == "tamil_nadu":
        stmt = stmt.where(ProjectLead.location.in_(TN_LOCATIONS))
    elif near == "india":
        stmt = stmt.where(ProjectLead.location.is_not(None))
    if status == "open" or status is None:
        stmt = stmt.where(ProjectLead.status.in_(("new", "shortlisted", "contacted", "interested")))
    elif status:
        stmt = stmt.where(ProjectLead.status == status)
    stmt = stmt.order_by(ProjectLead.score.desc(), ProjectLead.published_at.desc().nulls_last())
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/big-projects/summary")
def projects_summary(db: Session = DB):
    open_q = ProjectLead.status.in_(("new", "shortlisted", "contacted", "interested"))
    by_type = dict(db.execute(select(ProjectLead.project_type, func.count()).where(open_q).group_by(ProjectLead.project_type)).all())
    return {
        "total": db.scalar(select(func.count(ProjectLead.id)).where(open_q)) or 0,
        "tamil_nadu": db.scalar(select(func.count(ProjectLead.id)).where(open_q, ProjectLead.location.in_(TN_LOCATIONS))) or 0,
        "by_type": by_type,
        "type_labels": TYPE_LABEL,
        "feeds": DEFAULT_FEEDS,
        "last_run": get_setting(db, "big_projects_last_run"),
    }


@router.post("/big-projects/find")
def find_projects(db: Session = DB, who: str = Depends(actor)):
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "Already searching the news")
    try:
        stats = run_project_search(db)
    finally:
        _lock.release()
    from app.db import utcnow

    set_setting(db, "big_projects_last_run", {"at": utcnow().isoformat(), **stats})
    log_activity(db, "big_projects", None, "searched", stats, who)
    db.commit()
    return stats


@router.patch("/big-projects/{lid}", response_model=ProjectLeadOut)
def update_project(lid: int, body: ProjectLeadUpdate, db: Session = DB, who: str = Depends(actor)):
    lead = _get(db, lid)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(lead, k, v)
    log_activity(db, "project_lead", lead.id, "updated", {k: str(v) for k, v in data.items()}, who)
    db.commit()
    return lead


@router.get("/big-projects/{lid}/approach")
def project_approach(lid: int, db: Session = DB):
    return approach(_get(db, lid))
