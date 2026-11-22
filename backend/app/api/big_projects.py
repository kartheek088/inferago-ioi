"""Big projects from public business news (vendor / delivery-partner leads)."""

import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import NATIONWIDE, DB, Paging, actor, paginate
from app.db import utcnow
import csv
import io

from fastapi.responses import StreamingResponse

from app.big_projects import DEFAULT_FEEDS, TYPE_LABEL, approach, record_contact, run_project_search
from app.models import ProjectLead
from app.schemas import LinkConfirmIn, Page, ProjectContactIn, ProjectLeadOut, ProjectLeadUpdate
from app.settings_store import get_setting, log_activity, set_setting

router = APIRouter(tags=["big-projects"])
_lock = threading.Lock()
OPEN = ("new", "shortlisted", "contacted", "interested")


def _get(db: Session, lid: int) -> ProjectLead:
    lead = db.get(ProjectLead, lid)
    if not lead:
        raise HTTPException(404, "Project not found")
    return lead


def _query(q, project_type, state, status, sector=None):
    stmt = select(ProjectLead)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(ProjectLead.title.ilike(like), ProjectLead.company.ilike(like)))
    if project_type:
        stmt = stmt.where(ProjectLead.project_type == project_type)
    if state:
        stmt = stmt.where(ProjectLead.state.is_(None) if state == "unknown" else ProjectLead.state == state)
    if sector:
        stmt = stmt.where(ProjectLead.score_reasons.cast(String).like(f'%fits us: {sector.lower()}%'))
    if status in (None, "", "open"):
        stmt = stmt.where(ProjectLead.status.in_(OPEN))
    elif status == "follow_up":
        stmt = stmt.where(ProjectLead.next_follow_up.is_not(None), ProjectLead.status.in_(OPEN))
    elif status != "all":
        stmt = stmt.where(ProjectLead.status == status)
    return stmt


@router.get("/big-projects", response_model=Page[ProjectLeadOut])
def list_projects(
    q: str | None = None,
    project_type: str | None = Query(None, pattern="^(new_facility|expansion|launch|partnership)$"),
    state: str | None = None,
    status: str | None = None,
    paging: Paging = Depends(),
    db: Session = DB,
):
    stmt = _query(q, project_type, state, status)
    if status == "follow_up":
        stmt = stmt.order_by(ProjectLead.next_follow_up.asc())
    else:
        stmt = stmt.order_by(ProjectLead.score.desc(), ProjectLead.published_at.desc().nulls_last())
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/big-projects/export.csv")
def export_projects(state: str | None = None, status: str | None = None, db: Session = DB):
    rows = db.scalars(_query(None, None, state, status).order_by(ProjectLead.score.desc()).limit(5000)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["score", "title", "company", "type", "state", "place", "amount", "how we fit", "connected companies", "status",
                "last contacted", "next follow-up", "article"])
    for r in rows:
        w.writerow([r.score, r.title, r.company, TYPE_LABEL.get(r.project_type, r.project_type), r.state, r.location, r.amount_text, r.fit,
                    "; ".join(f"{x['company']} ({x['role']})" for x in r.links or []), r.status, r.last_contacted_at, r.next_follow_up, r.url])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=big-projects.csv"})


@router.get("/big-projects/summary")
def projects_summary(db: Session = DB):
    open_q = ProjectLead.status.in_(OPEN)
    by_type = dict(db.execute(select(ProjectLead.project_type, func.count()).where(open_q).group_by(ProjectLead.project_type)).all())
    by_state = {k or "unknown": v for k, v in db.execute(
        select(ProjectLead.state, func.count()).where(open_q).group_by(ProjectLead.state).order_by(func.count().desc())).all()}
    return {
        "total": db.scalar(select(func.count(ProjectLead.id)).where(open_q)) or 0,
        "tamil_nadu": by_state.get("Tamil Nadu", 0),
        "follow_ups_due": db.scalar(select(func.count(ProjectLead.id)).where(open_q, ProjectLead.next_follow_up <= utcnow())) or 0,
        "by_type": by_type,
        "by_state": by_state,
        "type_labels": TYPE_LABEL,
        "feeds": DEFAULT_FEEDS,
        "last_run": get_setting(db, "big_projects_last_run"),
    }


@router.post("/big-projects/find", dependencies=NATIONWIDE)
def find_projects(db: Session = DB, who: str = Depends(actor)):
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "Already searching the news")
    try:
        stats = run_project_search(db)
    finally:
        _lock.release()
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


@router.post("/big-projects/{lid}/contact", response_model=ProjectLeadOut)
def log_project_contact(lid: int, body: ProjectContactIn, db: Session = DB, who: str = Depends(actor)):
    lead = _get(db, lid)
    record_contact(lead, body.channel, body.outcome, body.note, who)
    log_activity(db, "project_lead", lead.id, "contact_logged", body.model_dump(), who)
    db.commit()
    return lead


@router.post("/big-projects/{lid}/links/{index}", response_model=ProjectLeadOut)
def confirm_link(lid: int, index: int, body: LinkConfirmIn, db: Session = DB, who: str = Depends(actor)):
    """Owner confirms or rejects a connected company read from the article (evidence stays attached)."""
    lead = _get(db, lid)
    links = [dict(x) for x in (lead.links or [])]
    if not 0 <= index < len(links):
        raise HTTPException(404, "No such connected company")
    links[index]["confirmed"] = body.confirmed
    lead.links = links
    log_activity(db, "project_lead", lead.id, "link_confirmed" if body.confirmed else "link_rejected", {"company": links[index]["company"]}, who)
    db.commit()
    return lead
