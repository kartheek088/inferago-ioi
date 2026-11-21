"""Bounded background execution for discovery and research jobs, plus the opt-in scheduler.

- Manual jobs run on a small thread pool (max 2 workers) — no uncontrolled loops.
- The APScheduler BackgroundScheduler only starts when IOI_SCHEDULER_ENABLED=true and only
  schedules sources with `enabled` AND `schedule_enabled` AND a collection frequency.
- Duplicate runs are prevented in pipeline.run_source (DB + in-process lock) and by
  APScheduler max_instances=1.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import DiscoveryJob, Source

log = logging.getLogger("ioi.jobs")

_executor: ThreadPoolExecutor | None = None
_scheduler: BackgroundScheduler | None = None


def executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ioi-job")
    return _executor


def _run_discovery(job_id: int) -> None:
    from app.pipeline import run_discovery_job

    with SessionLocal() as db:
        job = db.get(DiscoveryJob, job_id)
        if not job:
            return
        try:
            run_discovery_job(db, job)
            _auto_review(db)
        except Exception as exc:  # noqa: BLE001
            log.exception("Discovery job %s failed", job_id)
            db.rollback()
            job = db.get(DiscoveryJob, job_id)
            job.status, job.stats = "failed", {**(job.stats or {}), "error": str(exc)}
            db.commit()


def _auto_review(db) -> None:
    """After discovery, let the AI agent review the top new opportunities (setting ai_auto_review_top_n)."""
    from app.ai.agent import review_candidates, run_review
    from app.config import get_settings
    from app.settings_store import get_setting

    if not get_settings().ai_enabled:
        return
    for opp in review_candidates(db, int(get_setting(db, "ai_auto_review_top_n") or 0)):
        try:
            run_review(db, opp, trigger="auto")
        except Exception:  # noqa: BLE001 - one failed review must not stop the rest
            log.exception("AI review of opportunity %s failed", opp.id)
            db.rollback()


def _run_review(opp_id: int) -> None:
    from app.ai.agent import run_review
    from app.models import Opportunity

    with SessionLocal() as db:
        opp = db.get(Opportunity, opp_id)
        if opp:
            try:
                run_review(db, opp)
            except Exception:  # noqa: BLE001
                log.exception("AI review of opportunity %s failed", opp_id)


def submit_review(opp_id: int) -> None:
    executor().submit(_run_review, opp_id)


def submit_review_batch(limit: int) -> None:
    def _batch() -> None:
        from app.ai.agent import review_candidates, run_review

        with SessionLocal() as db:
            for opp in review_candidates(db, limit):
                try:
                    run_review(db, opp, trigger="batch")
                except Exception:  # noqa: BLE001
                    log.exception("AI review of opportunity %s failed", opp.id)
                    db.rollback()

    executor().submit(_batch)


def submit_discovery(job_id: int, *, background: bool = True) -> None:
    if background:
        executor().submit(_run_discovery, job_id)
    else:
        _run_discovery(job_id)


def _run_prospect_search(run_id: int, radius_m: int, max_per_area: int, rules=None) -> None:
    from app.models import ProspectRun
    from app.prospects import run_prospect_search

    with SessionLocal() as db:
        run = db.get(ProspectRun, run_id)
        if not run:
            return
        try:
            run_prospect_search(db, run, radius_m=radius_m, max_per_area=max_per_area, rules=rules)
        except Exception as exc:  # noqa: BLE001
            log.exception("Prospect search %s failed", run_id)
            db.rollback()
            run = db.get(ProspectRun, run_id)
            run.status, run.log = "failed", [*(run.log or []), str(exc)[:500]]
            db.commit()


def submit_prospect_search(run_id: int, *, radius_m: int, max_per_area: int, rules=None) -> None:
    executor().submit(_run_prospect_search, run_id, radius_m, max_per_area, rules)


def _run_map_scan(run_id: int, path: str, kwargs: dict) -> None:
    from app.models import ProspectRun
    from app.prospects import run_map_file_scan

    with SessionLocal() as db:
        run = db.get(ProspectRun, run_id)
        if run:
            run_map_file_scan(db, run, path, **kwargs)


def submit_map_scan(run_id: int, path: str, **kwargs) -> None:
    executor().submit(_run_map_scan, run_id, path, kwargs)


def _run_research() -> None:
    from app.research import run_research_batch

    with SessionLocal() as db:
        try:
            run_research_batch(db)
        except Exception:  # noqa: BLE001
            log.exception("Research batch failed")


def submit_research() -> None:
    executor().submit(_run_research)


def _scheduled_source_run(source_key: str) -> None:
    with SessionLocal() as db:
        job = DiscoveryJob(trigger="scheduled", source_keys=[source_key], query_terms=[], status="running")
        db.add(job)
        db.commit()
        _run_discovery(job.id)


def _scheduled_big_projects() -> None:
    """Twice a day: read the news feeds for new big projects (read-only; nothing is sent)."""
    from app.big_projects import run_project_search
    from app.db import utcnow
    from app.settings_store import set_setting

    with SessionLocal() as db:
        try:
            stats = run_project_search(db)
            set_setting(db, "big_projects_last_run", {"at": utcnow().isoformat(), "trigger": "scheduled", **stats})
            db.commit()
        except Exception:  # noqa: BLE001
            log.exception("Scheduled big-project search failed")


def sync_schedule() -> list[str]:
    """(Re)register per-source interval jobs. Returns the scheduled source keys."""
    if _scheduler is None:
        return []
    with SessionLocal() as db:
        sources = db.scalars(select(Source).where(Source.enabled.is_(True), Source.schedule_enabled.is_(True))).all()
        wanted = {f"source:{s.key}": s for s in sources if s.collection_frequency_minutes and s.connector}
    for job in _scheduler.get_jobs():
        if job.id.startswith("source:") and job.id not in wanted:
            job.remove()
    for jid, s in wanted.items():
        _scheduler.add_job(
            _scheduled_source_run, "interval", minutes=max(15, s.collection_frequency_minutes), id=jid,
            args=[s.key], replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=600,
        )
    return [j.removeprefix("source:") for j in wanted]


def start() -> None:
    global _scheduler
    if get_settings().scheduler_enabled and _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.start()
        keys = sync_schedule()
        _scheduler.add_job(_scheduled_big_projects, "interval", hours=12, id="big_projects", replace_existing=True,
                           max_instances=1, coalesce=True, misfire_grace_time=3600)
        log.info("Scheduler started for sources: %s", keys)


def scheduler_state() -> dict:
    if _scheduler is None:
        return {"enabled": False, "jobs": []}
    return {
        "enabled": True,
        "jobs": [{"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None} for j in _scheduler.get_jobs()],
    }


def shutdown() -> None:
    """Graceful shutdown: stop the scheduler and wait for running jobs."""
    global _scheduler, _executor
    if _scheduler is not None:
        _scheduler.shutdown(wait=True)
        _scheduler = None
    if _executor is not None:
        _executor.shutdown(wait=True, cancel_futures=True)
        _executor = None
