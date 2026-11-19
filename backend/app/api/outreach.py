"""Outreach drafts, approvals, call tasks and follow-ups. Nothing here sends anything."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, Paging, actor, paginate
from app.db import utcnow
from app.models import CallTask, FollowUpTask, Opportunity, OutreachApproval, OutreachDraft
from app.outreach import (
    WorkflowError,
    create_call_task,
    decide,
    generate_draft,
    mark_sent_manually,
    record_call_outcome,
    submit_for_approval,
    update_draft,
)
from app.schemas import (
    ApprovalOut,
    CallOutcomeIn,
    CallTaskIn,
    CallTaskOut,
    DecisionIn,
    DraftOut,
    DraftUpdate,
    FollowUpIn,
    FollowUpOut,
    FollowUpUpdate,
    Page,
)
from app.settings_store import log_activity

router = APIRouter()


def _draft(db: Session, draft_id: int) -> OutreachDraft:
    d = db.get(OutreachDraft, draft_id)
    if not d:
        raise HTTPException(404, "Draft not found")
    return d


def _wf(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except WorkflowError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/outreach/drafts", response_model=Page[DraftOut], tags=["outreach"])
def list_drafts(status: str | None = None, opportunity_id: int | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(OutreachDraft).order_by(OutreachDraft.id.desc())
    if status:
        stmt = stmt.where(OutreachDraft.status == status)
    if opportunity_id:
        stmt = stmt.where(OutreachDraft.opportunity_id == opportunity_id)
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.post("/opportunities/{opp_id}/outreach-drafts", response_model=DraftOut, status_code=201, tags=["outreach"])
def create_draft(opp_id: int, use_ai: bool = True, db: Session = DB, who: str = Depends(actor)):
    o = db.get(Opportunity, opp_id)
    if not o:
        raise HTTPException(404, "Opportunity not found")
    if o.eligibility_outcome == "not_eligible":
        raise HTTPException(409, "Opportunity is not eligible (mandatory requirement failed); outreach drafting blocked")
    d = generate_draft(db, o, use_ai=use_ai, actor=who)
    db.commit()
    return d


@router.get("/outreach/drafts/{draft_id}", response_model=DraftOut, tags=["outreach"])
def get_draft(draft_id: int, db: Session = DB):
    return _draft(db, draft_id)


@router.patch("/outreach/drafts/{draft_id}", response_model=DraftOut, tags=["outreach"])
def edit_draft(draft_id: int, body: DraftUpdate, db: Session = DB, who: str = Depends(actor)):
    d = _wf(update_draft, db, _draft(db, draft_id), body.model_dump(exclude_none=True), who)
    db.commit()
    return d


@router.post("/outreach/drafts/{draft_id}/submit", response_model=DraftOut, tags=["approvals"])
def submit(draft_id: int, db: Session = DB, who: str = Depends(actor)):
    d = _wf(submit_for_approval, db, _draft(db, draft_id), who)
    db.commit()
    return d


@router.post("/outreach/drafts/{draft_id}/decision", response_model=ApprovalOut, tags=["approvals"])
def decision(draft_id: int, body: DecisionIn, db: Session = DB):
    a = _wf(decide, db, _draft(db, draft_id), body.decision, body.decided_by, body.note)
    db.commit()
    return a


@router.post("/outreach/drafts/{draft_id}/mark-sent", response_model=DraftOut, tags=["approvals"])
def mark_sent(draft_id: int, db: Session = DB, who: str = Depends(actor)):
    """Record that a human sent the approved message themselves. The system never sends."""
    d = _wf(mark_sent_manually, db, _draft(db, draft_id), who)
    db.commit()
    return d


@router.get("/approvals", response_model=Page[ApprovalOut], tags=["approvals"])
def list_approvals(draft_id: int | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(OutreachApproval).order_by(OutreachApproval.id.desc())
    if draft_id:
        stmt = stmt.where(OutreachApproval.draft_id == draft_id)
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/call-tasks", response_model=Page[CallTaskOut], tags=["follow-ups"])
def list_calls(status: str | None = None, opportunity_id: int | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(CallTask).order_by(CallTask.id.desc())
    if status:
        stmt = stmt.where(CallTask.status == status)
    if opportunity_id:
        stmt = stmt.where(CallTask.opportunity_id == opportunity_id)
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.post("/call-tasks", response_model=CallTaskOut, status_code=201, tags=["follow-ups"])
def add_call(body: CallTaskIn, db: Session = DB, who: str = Depends(actor)):
    o = db.get(Opportunity, body.opportunity_id)
    if not o:
        raise HTTPException(404, "Opportunity not found")
    t = _wf(create_call_task, db, o, contact_id=body.contact_id, draft_id=body.draft_id, scheduled_for=body.scheduled_for, actor=who)
    db.commit()
    return t


@router.post("/call-tasks/{task_id}/outcome", response_model=FollowUpOut | None, tags=["follow-ups"])
def call_outcome(task_id: int, body: CallOutcomeIn, db: Session = DB, who: str = Depends(actor)):
    t = db.get(CallTask, task_id)
    if not t:
        raise HTTPException(404, "Call task not found")
    fu = _wf(record_call_outcome, db, t, body.outcome.value, body.notes, who, body.follow_up_date)
    db.commit()
    return fu


@router.get("/follow-ups", response_model=Page[FollowUpOut], tags=["follow-ups"])
def list_followups(status: str | None = "open", opportunity_id: int | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(FollowUpTask).order_by(FollowUpTask.due_date.asc().nulls_last(), FollowUpTask.id)
    if status:
        stmt = stmt.where(FollowUpTask.status == status)
    if opportunity_id:
        stmt = stmt.where(FollowUpTask.opportunity_id == opportunity_id)
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.post("/follow-ups", response_model=FollowUpOut, status_code=201, tags=["follow-ups"])
def add_followup(body: FollowUpIn, db: Session = DB, who: str = Depends(actor)):
    if not db.get(Opportunity, body.opportunity_id):
        raise HTTPException(404, "Opportunity not found")
    f = FollowUpTask(opportunity_id=body.opportunity_id, action=body.action, due_date=body.due_date, reason=body.reason)
    db.add(f)
    db.flush()
    log_activity(db, "follow_up", f.id, "created", {}, who)
    db.commit()
    return f


@router.patch("/follow-ups/{fu_id}", response_model=FollowUpOut, tags=["follow-ups"])
def update_followup(fu_id: int, body: FollowUpUpdate, db: Session = DB, who: str = Depends(actor)):
    f = db.get(FollowUpTask, fu_id)
    if not f:
        raise HTTPException(404, "Follow-up not found")
    if body.status:
        f.status = body.status
        f.completed_at = utcnow() if body.status == "done" else None
    if body.due_date:
        f.due_date = body.due_date
    log_activity(db, "follow_up", f.id, "updated", body.model_dump(exclude_none=True, mode="json"), who)
    db.commit()
    return f
