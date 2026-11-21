"""Application settings persisted in the `app_settings` table, plus activity logging helper."""

from typing import Any

from sqlalchemy.orm import Session

from app.models import ActivityLog, AppSetting
from app.profile import BusinessProfile, load_profile

DEFAULT_SETTINGS: dict[str, Any] = {
    "search_terms": [
        "looking for developer",
        "need software development",
        "API integration required",
        "looking for development agency",
        "need workflow automation",
        "seeking technical implementation partner",
        "outsourcing software development",
        "looking for backend developer",
        "internal tool development",
        "ERP integration",
        "external delivery partner",
        "software implementation subcontractor",
        "need a website",
        "SEO help",
        "CRM implementation",
        "SAP consultant contract",
        "AI chatbot for business",
    ],
    # Added to ranking priority (not to the three scores) when geography is EXPLICITLY known.
    "country_priorities": [
        {"match": "Tamil Nadu", "level": "region", "bonus": 15},
        {"match": "India", "level": "country", "bonus": 8},
    ],
    "research_budget": {
        "raw_target": 500,
        "shortlist_target": 50,
        "deep_research_target": 20,
        "max_requests_per_task": 6,
        "max_ai_calls_per_batch": 20,
        "max_tokens_per_batch": 60000,
        "max_seconds_per_batch": 300,
        "min_priority_for_research": 35,
    },
    "profile_overrides": {},
    # Optional AI (only when IOI_OPENROUTER_* is set). AI locates evidence; rules decide eligibility.
    "ai_classification_refinement": True,
    "ai_document_extraction": True,
    # AI review agent (OpenRouter, or Claude if configured): reviews this many top new opportunities after each discovery run.
    "ai_auto_review_top_n": 3,
    # Prospect finder (OpenStreetMap): areas to scan for businesses with no / weak online presence.
    "prospect_areas": ["Chennai", "Coimbatore", "Madurai"],
    "prospect_radius_m": 3000,
    "prospect_max_per_area": 80,
    # New searches keep only businesses WITHOUT a website and WITH a usable phone number.
    "prospect_only_no_website": True,
    "prospect_require_phone": True,
    "big_projects_last_run": None,
    "prospect_rules_version": None,
}


def get_setting(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    if row is None:
        return DEFAULT_SETTINGS.get(key)
    return row.value


def set_setting(db: Session, key: str, value: Any) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def all_settings(db: Session) -> dict[str, Any]:
    return {k: get_setting(db, k) for k in DEFAULT_SETTINGS}


def get_profile(db: Session) -> BusinessProfile:
    return load_profile(get_setting(db, "profile_overrides") or {})


def log_activity(
    db: Session,
    entity_type: str,
    entity_id: int | None,
    action: str,
    detail: dict[str, Any] | None = None,
    actor: str = "system",
) -> None:
    db.add(ActivityLog(entity_type=entity_type, entity_id=entity_id, action=action, detail=detail or {}, actor=actor))
