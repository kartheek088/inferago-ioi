"""Health, business profile, settings, dashboard summary, activity log."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import jobs
from app.api.deps import DB, Paging, actor, paginate
from app.config import get_settings
from app.db import utcnow
from app.enums import DraftStatus, ResearchStatus, TaskStatus
from app.models import (
    ActionItem,
    ActivityLog,
    AIUsageLog,
    FollowUpTask,
    Opportunity,
    Organisation,
    OrganisationRelationship,
    OutreachDraft,
    RawRecord,
    ResearchTask,
    Source,
    SourceRun,
)
from app.profile import DEFAULT_PROFILE, load_profile
from app.schemas import ActionIn, ActionOut, ActionUpdate, ActivityOut, Page, SettingsUpdate
from app.settings_store import DEFAULT_SETTINGS, all_settings, get_profile, log_activity, set_setting

public = APIRouter(tags=["health"])
router = APIRouter()


@public.get("/health")
def health(db: Session = DB):
    db.execute(select(1))
    s = get_settings()
    return {"status": "ok", "time": utcnow().isoformat(), "ai_enabled": s.ai_enabled, "scheduler": jobs.scheduler_state()["enabled"], "auth": "token" if s.api_token else "loopback-only"}


@router.get("/profile", tags=["profile"])
def profile(db: Session = DB):
    p = get_profile(db)
    return {"profile": p.model_dump(), "defaults": DEFAULT_PROFILE.model_dump(), "note": "Services cannot be changed via the API (owner approval in code)."}


@router.get("/settings", tags=["settings"])
def get_settings_api(db: Session = DB):
    s = get_settings()
    return {
        **all_settings(db),
        "runtime": {
            "ai_enabled": s.ai_enabled,
            "ai_model": s.openrouter_model if s.ai_enabled else None,
            "reddit_configured": s.reddit_configured,
            "scheduler": jobs.scheduler_state(),
            "auth_mode": "token" if s.api_token else "loopback-only",
        },
    }


@router.put("/settings", tags=["settings"])
def update_settings(body: SettingsUpdate, db: Session = DB, who: str = Depends(actor)):
    data = body.model_dump(exclude_none=True)
    if "profile_overrides" in data:
        data["profile_overrides"].pop("services", None)
        unknown = set(data["profile_overrides"]) - set(DEFAULT_PROFILE.model_dump())
        if unknown:
            raise HTTPException(422, f"Unknown profile fields: {sorted(unknown)}")
        try:
            load_profile(data["profile_overrides"])
        except ValidationError as exc:
            raise HTTPException(422, f"Invalid profile override: {exc.errors()[0]['msg']}") from exc
    if "research_budget" in data:
        merged = {**DEFAULT_SETTINGS["research_budget"], **data["research_budget"]}
        try:
            data["research_budget"] = {k: (float(v) if k == "min_priority_for_research" else int(v)) for k, v in merged.items() if k in DEFAULT_SETTINGS["research_budget"]}
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "Research budget values must be numbers") from exc
        if any(v < 0 for v in data["research_budget"].values()):
            raise HTTPException(422, "Research budget values must be non-negative")
    if "country_priorities" in data:
        for p in data["country_priorities"]:
            if not isinstance(p, dict) or p.get("level") not in ("region", "country") or not isinstance(p.get("match"), str) or not isinstance(p.get("bonus"), int | float):
                raise HTTPException(422, "Each priority needs match (str), level ('region'|'country') and bonus (number)")
    for k, v in data.items():
        set_setting(db, k, v)
    log_activity(db, "settings", None, "updated", {"keys": list(data)}, who)
    db.commit()
    return get_settings_api(db)


@router.get("/dashboard/summary", tags=["dashboard"])
def dashboard(db: Session = DB):
    def count(stmt):
        return db.scalar(stmt) or 0

    active = Opportunity.merged_into_id.is_(None)
    by_pipeline = dict(db.execute(select(Opportunity.pipeline, func.count()).where(active).group_by(Opportunity.pipeline)).all())
    by_status = dict(db.execute(select(Opportunity.status, func.count()).where(active).group_by(Opportunity.status)).all())
    by_elig = dict(db.execute(select(Opportunity.eligibility_outcome, func.count()).where(active).group_by(Opportunity.eligibility_outcome)).all())
    by_category = dict(db.execute(select(Opportunity.category, func.count()).where(active).group_by(Opportunity.category)).all())
    by_country = dict(db.execute(select(func.coalesce(Opportunity.country, "Unknown"), func.count()).where(active).group_by(func.coalesce(Opportunity.country, "Unknown"))).all())
    top = db.scalars(select(Opportunity).where(active, Opportunity.priority > 0).order_by(Opportunity.priority.desc()).limit(8)).all()
    week_ago = utcnow() - timedelta(days=7)
    recent_runs = db.scalars(select(SourceRun).order_by(SourceRun.id.desc()).limit(8)).all()
    src_names = dict(db.execute(select(Source.id, Source.name)).all())
    return {
        "totals": {
            "opportunities": count(select(func.count()).select_from(Opportunity).where(active)),
            "opportunities_7d": count(select(func.count()).select_from(Opportunity).where(active, Opportunity.created_at >= week_ago)),
            "organisations": count(select(func.count()).select_from(Organisation)),
            "raw_records": count(select(func.count()).select_from(RawRecord)),
            "demo_opportunities": count(select(func.count()).select_from(Opportunity).where(Opportunity.is_demo.is_(True))),
            "research_queued": count(select(func.count()).select_from(ResearchTask).where(ResearchTask.status.in_([ResearchStatus.QUEUED.value, ResearchStatus.IN_PROGRESS.value]))),
            "drafts_pending_approval": count(select(func.count()).select_from(OutreachDraft).where(OutreachDraft.status == DraftStatus.PENDING_APPROVAL.value)),
            "follow_ups_due": count(select(func.count()).select_from(FollowUpTask).where(FollowUpTask.status == TaskStatus.OPEN.value, FollowUpTask.due_date <= utcnow() + timedelta(days=1))),
            "relationships_confirmed": count(select(func.count()).select_from(OrganisationRelationship).where(OrganisationRelationship.verification_status == "confirmed")),
            "relationships_hypotheses": count(select(func.count()).select_from(OrganisationRelationship).where(OrganisationRelationship.verification_status == "hypothesis")),
            "ai_calls": count(select(func.count()).select_from(AIUsageLog)),
        },
        "by_pipeline": by_pipeline,
        "by_status": by_status,
        "by_eligibility": {(k or "not_assessed"): v for k, v in by_elig.items()},
        "by_category": by_category,
        "by_country": by_country,
        "top_opportunities": [{"id": o.id, "title": o.title, "priority": o.priority, "pipeline": o.pipeline, "eligibility": o.eligibility_outcome, "country": o.country, "is_demo": o.is_demo} for o in top],
        "recent_runs": [{"id": r.id, "source": src_names.get(r.source_id), "status": r.status, "started_at": r.started_at, "items_new": r.items_new, "error": r.error_message} for r in recent_runs],
        "source_health": [
            {"key": s.key, "name": s.name, "enabled": s.enabled, "status": s.connector_status, "last_success_at": s.last_success_at, "failure_status": s.failure_status}
            for s in db.scalars(select(Source).where(Source.enabled.is_(True))).all()
        ],
    }


@router.get("/activity", response_model=Page[ActivityOut], tags=["activity"])
def activity(entity_type: str | None = None, entity_id: int | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(ActivityLog).order_by(ActivityLog.id.desc())
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(ActivityLog.entity_id == entity_id)
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/actions", response_model=list[ActionOut], tags=["actions"])
def list_actions(status: str | None = "open", db: Session = DB):
    stmt = select(ActionItem).order_by(ActionItem.status, ActionItem.due_date.asc().nulls_last(), ActionItem.sort_order, ActionItem.id)
    if status:
        stmt = stmt.where(ActionItem.status == status)
    return db.scalars(stmt).all()


@router.post("/actions", response_model=ActionOut, status_code=201, tags=["actions"])
def add_action(body: ActionIn, db: Session = DB, who: str = Depends(actor)):
    if body.opportunity_id and not db.get(Opportunity, body.opportunity_id):
        raise HTTPException(404, "Opportunity not found")
    a = ActionItem(**body.model_dump())
    db.add(a)
    db.flush()
    log_activity(db, "action", a.id, "created", {"title": a.title}, who)
    db.commit()
    return a


@router.patch("/actions/{action_id}", response_model=ActionOut, tags=["actions"])
def update_action(action_id: int, body: ActionUpdate, db: Session = DB, who: str = Depends(actor)):
    a = db.get(ActionItem, action_id)
    if not a:
        raise HTTPException(404, "Action not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(a, k, v)
    if "status" in data:
        a.completed_at = utcnow() if a.status == "done" else None
    log_activity(db, "action", a.id, "updated", {k: str(v) for k, v in data.items()}, who)
    db.commit()
    return a


@router.delete("/actions/{action_id}", status_code=204, tags=["actions"])
def delete_action(action_id: int, db: Session = DB, who: str = Depends(actor)):
    a = db.get(ActionItem, action_id)
    if not a:
        raise HTTPException(404, "Action not found")
    db.delete(a)
    log_activity(db, "action", action_id, "deleted", {}, who)
    db.commit()
