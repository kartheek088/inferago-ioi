"""Discovery engine: persistent jobs run by one background worker thread.

- Job state lives in `ioi_jobs` (status, stage, counters, per-source results, log, heartbeat).
- One worker thread → no two jobs run at once; plus a DB check → no duplicate active job per campaign.
- Stop is graceful: checked between items; completed work is already committed.
- On restart, jobs that were running are marked `interrupted` (never resumed automatically). Queued
  jobs that never started do run.
- No Redis/Celery: a single-server internal tool doesn't need them.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, utcnow
from app.http_client import SafeHttp
from app.ioi3 import collect, core, qualify, research
from app.ioi3.models import Campaign, Company, Job

log = logging.getLogger("ioi3.engine")

STAGES = [
    ("finding", "Finding businesses"),
    ("locations", "Checking Chennai locations"),
    ("industry", "Checking industry relevance"),
    ("signals", "Looking for operational signals"),
    ("research", "Researching promising candidates"),
    ("shortlist", "Preparing qualified prospects"),
]
ACTIVE = ("queued", "running", "stopping")
MODES = ("quick", "balanced", "deep")


class JobConflict(Exception):
    pass


class ConfigError(Exception):
    pass


# ------------------------------------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------------------------------------
def active_job(db: Session, campaign_id: int) -> Job | None:
    return db.scalar(select(Job).where(Job.campaign_id == campaign_id, Job.status.in_(ACTIVE)))


def preflight(db: Session, campaign: Campaign) -> dict[str, Any]:
    """What can run right now, in plain language."""
    st = core.campaign_settings(campaign)
    enabled = st.get("sources") or {}
    checks = []
    f = collect.overture_file()
    checks.append({"source": "overture_places", "enabled": bool(enabled.get("overture_places", True)), "ready": f is not None,
                   "message": f"Business directory file ready ({f.name})" if f else
                   "Business directory file is missing — download it in Settings → Advanced → Sources"})
    checks.append({"source": "official_websites", "enabled": bool(enabled.get("official_websites", True)), "ready": True,
                   "message": "Company websites are checked over the internet (a few pages each)"})
    checks.append({"source": "news_rss", "enabled": bool(enabled.get("news_rss", True)), "ready": True,
                   "message": "Chennai business news feeds"})
    from app.config import get_settings

    ai = get_settings().ai_enabled
    checks.append({"source": "ai", "enabled": st.get("depth") == "deep" and int(st.get("ai_max_calls") or 0) > 0, "ready": ai,
                   "message": f"AI is configured (up to {st.get('ai_max_calls')} calls per Deep run)" if ai else
                   "AI not configured — research works without it"})
    can_find = checks[0]["enabled"] and checks[0]["ready"]
    return {"checks": checks, "can_start": any(c["enabled"] and c["ready"] for c in checks[:3]), "can_find_new": can_find}


def start_job(db: Session, campaign: Campaign, *, mode: str | None = None, trigger: str = "manual",
              retry_of: Job | None = None, only_sources: list[str] | None = None, overrides: dict | None = None) -> Job:
    if active_job(db, campaign.id) is not None:
        raise JobConflict("A discovery run is already in progress for this campaign.")
    st = {**core.campaign_settings(campaign), **(overrides or {})}
    mode = mode or st.get("depth") or "balanced"
    if mode not in MODES:
        raise ConfigError(f"Unknown research depth '{mode}'")
    pf = preflight(db, campaign)
    if not pf["can_start"]:
        raise ConfigError("No discovery source is available. " + " ".join(c["message"] for c in pf["checks"] if not c["ready"]))
    sources = [k for k, on in (st.get("sources") or {}).items() if on]
    if only_sources:
        sources = [s for s in sources if s in only_sources]
    job = Job(
        campaign_id=campaign.id, mode=mode, status="queued", stage=None, stage_index=0, trigger=trigger,
        retry_of_id=retry_of.id if retry_of else None,
        counters={"processed": 0, "accepted": 0, "rejected": 0, "pending": 0, "total": 0},
        sources={k: {"status": "waiting", "records": 0, "error": None} for k in sources},
        params={"max_candidates": int(st.get("max_candidates") or 50), "max_deep": int(st.get("max_deep") or 10),
                "daily_shortlist": int(st.get("daily_shortlist") or 5), "ai_max_calls": int(st.get("ai_max_calls") or 0),
                "sources": sources},
        log=[f"{utcnow():%H:%M:%S} Queued ({mode})"],
    )
    db.add(job)
    db.commit()
    wake()
    return job


def request_stop(db: Session, job: Job) -> Job:
    if job.status == "queued":
        job.status, job.finished_at = "stopped", utcnow()
        job.log = [*job.log, f"{utcnow():%H:%M:%S} Stopped before it started"]
    elif job.status == "running":
        job.cancel_requested, job.status = True, "stopping"
        job.log = [*job.log, f"{utcnow():%H:%M:%S} Stop requested — finishing the current item"]
    db.commit()
    return job


def recover(db: Session) -> int:
    """At startup: running/stopping jobs died with the old process."""
    n = 0
    for job in db.scalars(select(Job).where(Job.status.in_(("running", "stopping")))):
        job.status, job.finished_at = "interrupted", utcnow()
        job.error = "The app was restarted while this run was in progress. Completed work was saved; use Retry to continue."
        job.log = [*job.log, f"{utcnow():%H:%M:%S} Interrupted by an app restart"]
        n += 1
    db.commit()
    return n


# ------------------------------------------------------------------------------------------------
# Worker
# ------------------------------------------------------------------------------------------------
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None


def wake() -> None:
    _wake.set()


def start_worker() -> None:
    global _thread
    from app.config import get_settings

    if not get_settings().ioi3_worker or (_thread is not None and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="ioi3-engine", daemon=True)
    _thread.start()


def stop_worker(timeout: float = 10) -> None:
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout)


def _loop() -> None:
    while not _stop.is_set():
        _wake.wait(5)
        _wake.clear()
        while not _stop.is_set() and run_next():
            pass


def run_next(http_factory: Callable[[], SafeHttp] | None = None) -> bool:
    """Run the oldest queued job, if any. Returns True if a job ran. (Called by the worker and by tests.)"""
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.status == "queued").order_by(Job.id))
        if job is None:
            return False
        job_id = job.id
    try:
        Runner(job_id, http_factory).run()
    except Exception:  # noqa: BLE001 — never let the worker thread die
        log.exception("Discovery job %s crashed", job_id)
    return True


class Runner:
    def __init__(self, job_id: int, http_factory: Callable[[], SafeHttp] | None = None) -> None:
        self.job_id = job_id
        self.http_factory = http_factory or (lambda: SafeHttp(rate_limit_per_minute=20))

    # --- state helpers ---------------------------------------------------------------------------
    def _job(self) -> Job:
        return self.db.get(Job, self.job_id)

    def say(self, msg: str) -> None:
        job = self._job()
        job.log = [*(job.log or [])[-199:], f"{utcnow():%H:%M:%S} {msg}"]
        job.heartbeat_at = utcnow()
        self.db.commit()

    def stage(self, key: str) -> None:
        job = self._job()
        job.stage, job.stage_index = key, [k for k, _ in STAGES].index(key) + 1
        job.heartbeat_at = utcnow()
        self.db.commit()
        self.say(dict(STAGES)[key])

    def count(self, **delta: int) -> None:
        job = self._job()
        c = dict(job.counters or {})
        for k, v in delta.items():
            c[k] = c.get(k, 0) + v
        job.counters, job.heartbeat_at = c, utcnow()
        self.db.commit()

    def source(self, key: str, **kw: Any) -> None:
        job = self._job()
        src = dict(job.sources or {})
        src[key] = {**src.get(key, {}), **kw}
        job.sources = src
        self.db.commit()

    def stopping(self) -> bool:
        self.db.expire_all()
        return bool(self._job().cancel_requested)

    # --- run -------------------------------------------------------------------------------------
    def run(self) -> None:
        with SessionLocal() as db:
            self.db = db
            job = self._job()
            job.status, job.started_at, job.heartbeat_at = "running", utcnow(), utcnow()
            db.commit()
            campaign = db.get(Campaign, job.campaign_id)
            p = job.params or {}
            srcs = set(p.get("sources") or [])
            http = self.http_factory()
            touched: set[int] = set()
            try:
                self._find(campaign, p, srcs, touched)
                if not self.stopping() and job.mode != "quick" and "news_rss" in srcs:
                    self._news(campaign, http)
                if not self.stopping() and job.mode != "quick" and "official_websites" in srcs:
                    self._research(campaign, p, http, deep=job.mode == "deep", touched=touched)
                self._shortlist(campaign, p)
                job = self._job()
                job.status = "stopped" if job.cancel_requested else "completed"
            except Exception as exc:  # noqa: BLE001
                log.exception("job failed")
                db.rollback()
                job = self._job()
                job.status, job.error = "failed", f"{type(exc).__name__}: {str(exc)[:400]}"
                job.log = [*(job.log or []), f"{utcnow():%H:%M:%S} Failed: {job.error}"]
            finally:
                http.close()
            job.finished_at = utcnow()
            job.sources = {k: ({**v, "status": "skipped", "error": None} if v.get("status") == "waiting" else v)
                           for k, v in (job.sources or {}).items()}
            job.summary = self._summary(campaign)
            failed = [k for k, v in (job.sources or {}).items() if v.get("status") == "failed"]
            job.log = [*(job.log or []), f"{utcnow():%H:%M:%S} {'Stopped' if job.status == 'stopped' else job.status.title()}"
                       + (f" — {len(failed)} source(s) failed" if failed else "")]
            db.commit()

    def _find(self, campaign: Campaign, p: dict, srcs: set[str], touched: set[int]) -> None:
        self.stage("finding")
        if "overture_places" not in srcs:
            self.say("Business directory is switched off — skipping new businesses")
            return
        self.source("overture_places", status="running")
        try:
            path = collect.overture_file()
            if path is None:
                raise FileNotFoundError("needs_setup: the business directory file is not downloaded")
            cands = collect.overture_candidates(path)
            core.mark_source(self.db, "overture_places", ok=True, records=len(cands), freshness=f"File {path.name}")
            self.db.commit()
            self.say(f"Read {len(cands):,} real business listings in the Chennai area")
        except Exception as exc:  # noqa: BLE001
            core.mark_source(self.db, "overture_places", ok=False, error=str(exc))
            self.source("overture_places", status="failed", error=str(exc).removeprefix("needs_setup: "))
            self.say(f"Business directory unavailable: {str(exc).removeprefix('needs_setup: ')}")
            return
        self.stage("locations")
        total = {"n": 0}

        def progress(msg: str, stats: dict) -> None:
            job = self._job()
            job.counters = {**(job.counters or {}), "processed": stats["processed"], "accepted": stats["accepted"],
                            "rejected": stats["outside_chennai"] + stats["chain_outlet"] + stats["wrong_industry"],
                            "duplicates": stats["duplicate"], "total": stats["new_relevant"]}
            job.heartbeat_at = utcnow()
            self.db.commit()
            total["n"] = stats["processed"]
            if stats["processed"] % 10 == 0 or stats["processed"] == stats["new_relevant"]:
                self.say(msg)

        stats = collect.collect_overture(self.db, campaign, limit=int(p.get("max_candidates") or 50), job_id=self.job_id,
                                         progress=progress, should_stop=self.stopping, cands=cands)
        self.source("overture_places", status="done", records=stats["accepted"])
        if stats["new_relevant"] == 0:
            self.say("No new relevant businesses left in the directory file for this campaign")
        self.stage("industry")
        out = stats["outside_chennai"] + stats["prefiltered_outside"]
        chain = stats["chain_outlet"] + stats["prefiltered_chain"]
        self.say(f"{stats['accepted']} businesses kept · {out} outside Chennai city · {stats['duplicate']} duplicates · "
                 f"{chain} brand outlets skipped")
        job = self._job()
        job.counters = {**job.counters, "rejected_outside_total": out, "chain_outlets_total": chain}
        self.db.commit()
        job = self._job()
        job.counters = {**job.counters, "pending": self.db.query(Company).filter(
            Company.campaign_id == campaign.id, Company.archived.is_(False), Company.qualification == "P2").count()}
        self.db.commit()

    def _news(self, campaign: Campaign, http: SafeHttp) -> None:
        self.stage("signals")
        self.source("news_rss", status="running")
        feed_errors: list[str] = []

        def on_feed(name: str, ok: bool) -> None:
            if not ok:
                feed_errors.append(name)

        try:
            st = research.scan_news(self.db, campaign, http, job_id=self.job_id, on_feed=on_feed)
        except Exception as exc:  # noqa: BLE001
            core.mark_source(self.db, "news_rss", ok=False, error=str(exc))
            self.source("news_rss", status="failed", error=str(exc)[:200])
            self.say(f"News feeds failed: {str(exc)[:150]}")
            return
        ok = st["feeds_ok"] > 0
        core.mark_source(self.db, "news_rss", ok=ok, records=st["articles"], error=None if ok else "; ".join(st["feeds_failed"])[:400],
                         freshness=f"{st['articles']} articles read {utcnow():%d %b}")
        self.source("news_rss", status="done" if ok else "failed", records=st["articles"],
                    error=("; ".join(st["feeds_failed"]) or None))
        self.db.commit()
        self.say(f"News: {st['articles']} articles from {st['feeds_ok']} feeds · {st['relevant']} relevant Chennai items · "
                 f"{st['matched']} matched a business · {st['new_signals']} new signals"
                 + (f" · {len(st['feeds_failed'])} feed(s) failed" if st["feeds_failed"] else ""))

    def _research(self, campaign: Campaign, p: dict, http: SafeHttp, *, deep: bool, touched: set[int]) -> None:
        self.stage("research")
        limit = int(p.get("max_deep") or 10)
        want = ("directory", "website") if deep else ("directory",)
        pool = list(self.db.scalars(select(Company).where(
            Company.campaign_id == campaign.id, Company.archived.is_(False), Company.website.is_not(None),
            Company.research_level.in_(want), Company.qualification != "P3",
            Company.review_status.in_(("new", "shortlisted", "watchlist"))).order_by(Company.prescore.desc(), Company.id)))
        # Respect the campaign's industry mix (e.g. 70/30) in research effort too; fill any unused share.
        mix = campaign.industry_mix or core.DEFAULT_MIX
        total = sum(mix.values()) or 1
        rows: list[Company] = []
        for ind, share in mix.items():
            rows += [c for c in pool if c.industry == ind][: round(limit * share / total)]
        rows += [c for c in pool if c not in rows][: max(0, limit - len(rows))]
        rows = sorted(rows[:limit], key=lambda c: (-c.prescore, c.id))
        self.source("official_websites", status="running")
        self.say(f"Researching {len(rows)} company websites (up to {7 if deep else 4} pages each, robots.txt respected)")
        ai_left = int(p.get("ai_max_calls") or 0) if deep else 0
        ok = failed = 0
        for i, c in enumerate(rows, start=1):
            if self.stopping():
                break
            used = research.research_company(self.db, c, http, deep=deep, ai_calls_left=ai_left)
            ai_left -= used
            self.db.commit()
            touched.add(c.id)
            if c.research_error:
                failed += 1
            else:
                ok += 1
            self.say(f"Researched {i} of {len(rows)}: {c.name} — {c.qualification}"
                     + (f" ({c.research_error[:80]})" if c.research_error else ""))
        if ok:
            core.mark_source(self.db, "official_websites", ok=True, records=ok, freshness=f"Last check {utcnow():%d %b %Y}")
        elif failed:
            core.mark_source(self.db, "official_websites", ok=False, error=f"All {failed} websites failed to load")
        self.source("official_websites", status="done" if ok or not failed else "failed", records=ok,
                    error=f"{failed} website(s) could not be loaded" if failed else None)
        self.db.commit()

    def _shortlist(self, campaign: Campaign, p: dict) -> None:
        self.stage("shortlist")
        rows = list(self.db.scalars(select(Company).where(Company.campaign_id == campaign.id, Company.archived.is_(False),
                                                          Company.review_status.in_(("new", "shortlisted")))))
        for c in rows:
            core.evaluate(c)
        self.db.commit()
        waiting = sum(1 for c in rows if c.review_status == "shortlisted")
        room = max(0, int(p.get("daily_shortlist") or 5) - waiting)
        order = {"P0": 0, "P1": 1, "P2": 2}
        ready = sorted((c for c in rows if c.review_status == "new" and qualify.sales_ready(c.gates) and c.qualification != "P3"),
                       key=lambda c: (order.get(c.qualification, 9), -c.score))
        for c in ready[:room]:
            c.review_status = "shortlisted"
        self.db.commit()
        self.say(f"{min(room, len(ready))} new prospect(s) added to Ready to Review "
                 f"({len(ready)} passed every check; {waiting} were already waiting)")

    def _summary(self, campaign: Campaign) -> dict[str, Any]:
        q = self.db.query(Company).filter(Company.campaign_id == campaign.id, Company.archived.is_(False))
        return {"companies": q.count(),
                "by_category": {k: q.filter(Company.qualification == k).count() for k in ("P0", "P1", "P2", "P3")},
                "ready_to_review": q.filter(Company.review_status == "shortlisted").count(),
                "verified_locations": q.filter(Company.location_confidence == "verified").count()}
