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

from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, utcnow
from app.http_client import SafeHttp
from app.ioi3 import collect, core, qualify, research
from app.ioi3.fetch import Stats, short_write, with_retry
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
        log=[f"{datetime.now():%H:%M:%S} Queued ({mode})"],
    )
    db.add(job)
    db.commit()
    wake()
    return job


def request_stop(db: Session, job: Job) -> Job:
    if job.status == "queued":
        job.status, job.finished_at = "stopped", utcnow()
        job.log = [*job.log, f"{datetime.now():%H:%M:%S} Stopped before it started"]
    elif job.status == "running":
        job.cancel_requested, job.status = True, "stopping"
        job.log = [*job.log, f"{datetime.now():%H:%M:%S} Stop requested — finishing the current item"]
    db.commit()
    return job


def recover(db: Session) -> int:
    """At startup: running/stopping jobs died with the old process."""
    n = 0
    for job in db.scalars(select(Job).where(Job.status.in_(("running", "stopping")))):
        job.status, job.finished_at = "interrupted", utcnow()
        job.error = "The app was restarted while this run was in progress. Completed work was saved; use Retry to continue."
        job.log = [*job.log, f"{datetime.now():%H:%M:%S} Interrupted by an app restart"]
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


_current_job: int | None = None  # job being run by this process's worker (for stale-job detection)
STALE_AFTER = timedelta(minutes=3)


def _loop() -> None:
    while not _stop.is_set():
        _wake.wait(5)
        _wake.clear()
        try:
            with SessionLocal() as db:
                recover_stale(db)
        except Exception:  # noqa: BLE001
            log.exception("stale-job check failed")
        while not _stop.is_set() and run_next():
            pass


def recover_stale(db: Session) -> int:
    """A running job whose heartbeat stopped (worker crashed / thread died) is marked interrupted."""
    n = 0
    cutoff = utcnow() - STALE_AFTER
    for job in db.scalars(select(Job).where(Job.status.in_(("running", "stopping")))):
        if job.id == _current_job:
            continue
        if (job.heartbeat_at or job.started_at or job.created_at) < cutoff:
            job.status, job.finished_at = "interrupted", utcnow()
            job.error = "The discovery worker stopped responding (no progress for 3 minutes). Completed work was saved; use Retry."
            job.log = [*(job.log or []), f"{datetime.now():%H:%M:%S} Marked interrupted: no heartbeat since {job.heartbeat_at:%H:%M:%S}"
                       if job.heartbeat_at else f"{datetime.now():%H:%M:%S} Marked interrupted: never reported progress"]
            n += 1
    if n:
        db.commit()
    return n


def runner_for(channel: str | None):
    """Which runner executes a job. Each acquisition channel has its own stages and sources."""
    from app.ioi3 import models

    if channel == models.SOCIAL:
        from app.ioi3.social.engine import SocialRunner

        return SocialRunner
    return Runner


def run_next(http_factory: Callable[[], SafeHttp] | None = None) -> bool:
    """Run the oldest queued job, if any. Returns True if a job ran. (Called by the worker and by tests.)"""
    global _current_job
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.status == "queued").order_by(Job.id))
        if job is None:
            return False
        job_id, channel = job.id, job.channel
    _current_job = job_id
    try:
        runner_for(channel)(job_id, http_factory).run()
    except Exception:  # noqa: BLE001 — never let the worker thread die
        log.exception("Discovery job %s crashed", job_id)
        try:
            def mark(s):
                j = s.get(Job, job_id)
                if j and j.status in ("running", "stopping", "queued"):
                    j.status, j.finished_at, j.error = "failed", utcnow(), "Internal error — see Settings → Advanced → Job history"
            short_write(mark)
        except Exception:  # noqa: BLE001
            pass
    finally:
        _current_job = None
    return True


class Runner:
    """Runs one job. Progress is written in short, retried transactions separate from the work session,
    so a click in the UI can never make the job fail with 'database is locked'."""

    def __init__(self, job_id: int, http_factory: Callable[[], SafeHttp] | None = None) -> None:
        self.job_id = job_id
        self.http_factory = http_factory or (lambda: SafeHttp(rate_limit_per_minute=20))

    # --- progress (own short transactions) -------------------------------------------------------
    def _w(self, fn: Callable[[Job], None]) -> None:
        def go(s):
            j = s.get(Job, self.job_id)
            fn(j)
            j.heartbeat_at = utcnow()
        short_write(go)

    def say(self, msg: str, *, ok: bool = False) -> None:
        line = f"{datetime.now():%H:%M:%S} {msg}"

        def f(j: Job) -> None:
            j.log = [*(j.log or [])[-199:], line]
            if ok:
                j.summary = {**(j.summary or {}), "last_success": line}
        self._w(f)

    def stage(self, key: str) -> None:
        def f(j: Job) -> None:
            j.stage, j.stage_index = key, [k for k, _ in STAGES].index(key) + 1
            j.summary = {**(j.summary or {}), "stage_started_at": utcnow().isoformat()}
        self._w(f)
        self.say(dict(STAGES)[key])

    def metrics(self, group: str, **values: Any) -> None:
        """group: run | pool | campaign. Values replace previous ones in that group."""
        def f(j: Job) -> None:
            m = dict(j.counters or {})
            m[group] = {**(m.get(group) or {}), **values}
            j.counters = m
        self._w(f)

    def source(self, key: str, **kw: Any) -> None:
        def f(j: Job) -> None:
            src = dict(j.sources or {})
            src[key] = {**src.get(key, {}), **kw}
            j.sources = src
        self._w(f)

    def stopping(self) -> bool:
        with SessionLocal() as s:
            return bool(s.scalar(select(Job.cancel_requested).where(Job.id == self.job_id)))

    # --- run -------------------------------------------------------------------------------------
    def run(self) -> None:
        with SessionLocal() as db:
            self.db = db
            job = db.get(Job, self.job_id)
            campaign_id, mode, p = job.campaign_id, job.mode, dict(job.params or {})
            db.commit()

            def start(j: Job) -> None:
                j.status, j.started_at = "running", utcnow()
                j.counters = {"run": {"reviewed": 0, "added": 0, "duplicates": 0, "rejected": 0, "researched": 0,
                                      "research_failed": 0, "newly_qualified": 0}, "pool": {}, "campaign": {}}
            self._w(start)
            campaign = db.get(Campaign, campaign_id)
            srcs = set(p.get("sources") or [])
            self.ready_before = {c.id for c in db.scalars(select(Company).where(Company.campaign_id == campaign_id))
                                 if qualify.sales_ready(c.gates or [])}
            db.commit()
            http = self.http_factory()
            status, error = "completed", None
            try:
                self._find(campaign, p, srcs)
                if not self.stopping() and mode != "quick" and "news_rss" in srcs:
                    self._news(campaign, http)
                if not self.stopping() and mode != "quick" and "official_websites" in srcs:
                    self._research(campaign, p, deep=mode == "deep")
                if not self.stopping() and mode == "deep" and not getattr(self, "network_down", False):
                    self._agent(campaign, p)
                self._shortlist(campaign, p)
                if self.stopping():
                    status = "stopped"
            except Exception as exc:  # noqa: BLE001
                log.exception("job failed")
                db.rollback()
                status, error = "failed", f"{type(exc).__name__}: {str(exc)[:400]}"
                self.say(f"Failed: {error}")
            finally:
                http.close()
            summary = self._summary(campaign)
            failed = [k for k, v in (self._snapshot().sources or {}).items() if v.get("status") == "failed"]

            def finish(j: Job) -> None:
                j.status, j.error, j.finished_at = status, error, utcnow()
                j.sources = {k: ({**v, "status": "skipped", "error": None} if v.get("status") == "waiting" else v)
                             for k, v in (j.sources or {}).items()}
                j.summary = {**(j.summary or {}), **summary}
                j.log = [*(j.log or []), f"{datetime.now():%H:%M:%S} {'Stopped' if status == 'stopped' else status.title()}"
                         + (f" — {len(failed)} source(s) failed" if failed else "")]
            self._w(finish)

    def _snapshot(self) -> Job:
        with SessionLocal() as s:
            j = s.get(Job, self.job_id)
            s.expunge(j)
            return j

    def _campaign_metrics(self, campaign: Campaign) -> None:
        q = self.db.query(Company).filter(Company.campaign_id == campaign.id, Company.archived.is_(False))
        rows = q.all()
        self.db.commit()
        self.metrics("campaign", companies=len(rows),
                     needs_verification=sum(1 for c in rows if c.qualification != "P3" and not qualify.sales_ready(c.gates or [])),
                     ready_to_review=sum(1 for c in rows if c.review_status == "shortlisted"),
                     sales_ready=sum(1 for c in rows if qualify.sales_ready(c.gates or []) and c.qualification != "P3"))

    def _find(self, campaign: Campaign, p: dict, srcs: set[str]) -> None:
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
            short_write(lambda s: core.mark_source(s, "overture_places", ok=True, records=len(cands), freshness=f"File {path.name}"))
            self.say(f"Read {len(cands):,} business listings in the Chennai area from the directory file", ok=True)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).removeprefix("needs_setup: ")
            short_write(lambda s: core.mark_source(s, "overture_places", ok=False, error=str(exc)))
            self.source("overture_places", status="failed", error=msg, kind="permanent" if "needs_setup" in str(exc) else "retryable")
            self.say(f"Business directory unavailable: {msg}")
            return
        self.stage("locations")

        def progress(msg: str, stats: dict) -> None:
            self.metrics("run", reviewed=stats["processed"], added=stats["accepted"], duplicates=stats["duplicate"],
                         rejected=stats["outside_chennai"] + stats["chain_outlet"] + stats["wrong_industry"], to_review=stats["new_relevant"])
            if stats["processed"] % 10 == 0 or stats["processed"] == stats["new_relevant"]:
                self.say(msg)

        stats = collect.collect_overture(self.db, campaign, limit=int(p.get("max_candidates") or 50), job_id=self.job_id,
                                         progress=progress, should_stop=self.stopping, cands=cands)
        self.db.commit()
        self.source("overture_places", status="done", records=stats["accepted"])
        self.metrics("pool", unseen_relevant=stats.get("unseen_relevant", 0), outside_city=stats["prefiltered_outside"],
                     chain_outlets=stats["prefiltered_chain"])
        self.stage("industry")
        self.say(f"This run: {stats['processed']} reviewed · {stats['accepted']} added · {stats['duplicate']} duplicates. "
                 f"Directory file: {stats.get('unseen_relevant', 0)} relevant listings not yet reviewed "
                 f"({stats['prefiltered_outside']} outside the city and {stats['prefiltered_chain']} chain outlets are never added)", ok=True)
        if stats["new_relevant"] == 0:
            self.say("No new relevant businesses left in the directory file for this campaign")
        self._campaign_metrics(campaign)

    def _news(self, campaign: Campaign, http: SafeHttp) -> None:
        self.stage("signals")
        self.source("news_rss", status="running")
        try:
            st = research.scan_news(self.db, campaign, http, job_id=self.job_id)
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            short_write(lambda s: core.mark_source(s, "news_rss", ok=False, error=str(exc)))
            self.source("news_rss", status="failed", error=str(exc)[:200], kind="retryable")
            self.say(f"News feeds failed: {str(exc)[:150]}")
            return
        ok = st["feeds_ok"] > 0
        short_write(lambda s: core.mark_source(s, "news_rss", ok=ok, records=st["articles"],
                                               error=None if ok else "; ".join(st["feeds_failed"])[:400],
                                               freshness=f"{st['articles']} articles read {utcnow():%d %b}"))
        self.source("news_rss", status="done" if ok else "failed", records=st["articles"],
                    error=("; ".join(st["feeds_failed"]) or None), kind="retryable" if st["feeds_failed"] else None,
                    skipped_backoff=st.get("skipped_backoff", 0))
        self.say(f"News: {st['articles']} articles from {st['feeds_ok']} feeds · {st['relevant']} relevant Chennai items · "
                 f"{st['matched']} matched a business · {st['new_signals']} new signals"
                 + (f" · {len(st['feeds_failed'])} feed(s) failed" if st["feeds_failed"] else "")
                 + (f" · {st['skipped_backoff']} feed(s) skipped after recent failures" if st.get("skipped_backoff") else ""), ok=ok)

    def _research(self, campaign: Campaign, p: dict, *, deep: bool) -> None:
        self.stage("research")
        limit = int(p.get("max_deep") or 10)
        want = ("directory", "website") if deep else ("directory",)
        now = utcnow()
        pool = list(self.db.scalars(select(Company).where(
            Company.campaign_id == campaign.id, Company.archived.is_(False), Company.website.is_not(None),
            Company.research_level.in_(want), Company.qualification != "P3",
            Company.review_status.in_(("new", "shortlisted", "watchlist")),
            # Back off failed websites: 1 day for temporary problems, 30 days for permanent ones ("Research further" still works).
            or_(Company.research_retry_after.is_(None), Company.research_retry_after <= now))
            .order_by(Company.prescore.desc(), Company.id)))
        mix = campaign.industry_mix or core.DEFAULT_MIX
        total = sum(mix.values()) or 1
        rows: list[Company] = []
        for ind, share in mix.items():
            rows += [c for c in pool if c.industry == ind][: round(limit * share / total)]
        rows += [c for c in pool if c not in rows][: max(0, limit - len(rows))]
        rows = sorted(rows[:limit], key=lambda c: (-c.prescore, c.id))
        self.source("official_websites", status="running")
        self.say(f"Researching {len(rows)} company websites, 4 at a time (up to {7 if deep else 4} pages each, robots.txt respected)")
        done = {"n": 0}
        stats = Stats()

        def on_done(c: Company) -> None:
            done["n"] += 1
            qualified = qualify.sales_ready(c.gates or []) and c.id not in self.ready_before
            self.metrics("run", researched=done["n"], research_failed=getattr(self, "_rf", 0) + (1 if c.research_error else 0))
            self._rf = getattr(self, "_rf", 0) + (1 if c.research_error else 0)
            if qualified:
                self.ready_before.add(c.id)
                self._nq = getattr(self, "_nq", 0) + 1
                self.metrics("run", newly_qualified=self._nq)
            self.say(f"Researched {done['n']} of {len(rows)}: {c.name} — "
                     + (c.research_error[:120] if c.research_error else ("passes every check" if qualify.sales_ready(c.gates or []) else c.next_action or c.qualification)),
                     ok=not c.research_error)

        res = research.research_many(self.db, rows, deep=deep, on_done=on_done, should_stop=self.stopping, stats=stats)
        ok, failed = res["researched"], res["failed"]
        if res.get("network_outage"):
            self.network_down = True
            msg = ("This computer couldn't reach the internet (DNS lookups failing), so website research stopped early. "
                   "Nothing was blamed on the companies; they'll be retried in about 15 minutes. Check the internet connection, then use Retry.")
            short_write(lambda s: core.mark_source(s, "official_websites", ok=False, error="Network/DNS problem on this computer"))
            self.source("official_websites", status="failed", records=ok, error="Network/DNS problem on this computer", kind="retryable")
            self.say(msg)
            self.metrics("run", pages_fetched=res["pages_fetched"], cache_hits=res["cache_hits"], revalidated_304=res["revalidated_304"])
            self._campaign_metrics(campaign)
            return
        if ok:
            short_write(lambda s: core.mark_source(s, "official_websites", ok=True, records=ok, freshness=f"Last check {utcnow():%d %b %Y}"))
        elif failed:
            short_write(lambda s: core.mark_source(s, "official_websites", ok=False, error=f"All {failed} websites failed to load"))
        self.source("official_websites", status="done" if ok or not failed else "failed", records=ok,
                    error=f"{failed} website(s) could not be loaded" if failed else None)
        self.metrics("run", pages_fetched=res["pages_fetched"], cache_hits=res["cache_hits"], revalidated_304=res["revalidated_304"])
        self._campaign_metrics(campaign)

    def _agent(self, campaign: Campaign, p: dict) -> None:
        """Deep mode: the bounded AI research agent investigates the strongest researched candidates."""
        from app.ioi3 import agent

        budget = int(p.get("ai_max_calls") or 0)
        if budget <= 0:
            self.say("AI research is switched off for this run (AI call limit is 0) — rule-based research only")
            return
        if not agent.available(self.db):
            self.say("AI unavailable — rule-based research active")
            self.source("ai_agent", status="failed", error="AI not configured or not reachable", kind="permanent")
            return
        rows = [c for c in self.db.scalars(select(Company).where(
            Company.campaign_id == campaign.id, Company.archived.is_(False), Company.website.is_not(None),
            Company.research_error.is_(None), Company.research_level != "directory", Company.qualification != "P3",
            Company.review_status.in_(("new", "shortlisted", "watchlist"))).order_by(Company.score.desc(), Company.id))
            if c.ai_status in ("not_run", "failed", "unavailable")][: max(1, min(5, budget // 4))]
        self.db.commit()
        self.source("ai_agent", status="running")
        self.say(f"AI research agent: investigating {len(rows)} strongest candidate(s) (max {agent.LIMITS.max_model_calls} AI calls each)")
        calls = 0
        for c in rows:
            if self.stopping() or calls >= budget:
                break
            out = agent.investigate(self.db, c, job_id=self.job_id, max_model_calls=min(agent.LIMITS.max_model_calls, budget - calls),
                                    should_stop=self.stopping)
            calls += out.model_calls
            self.say(f"AI agent finished {c.name}: {out.outcome} ({out.model_calls} AI calls, {out.facts} new facts, {out.people} people)",
                     ok=out.outcome != "failed")
            if out.outcome == "failed" and out.model_calls == 0:
                self.say("AI provider unreachable — stopping AI research for this run. Rule-based results are kept; use Retry AI research later.")
                self.source("ai_agent", status="failed", error="AI provider unreachable", kind="retryable")
                self.metrics("run", ai_calls=calls)
                return
        self.source("ai_agent", status="done", records=len(rows))
        self.metrics("run", ai_calls=calls)

    def _shortlist(self, campaign: Campaign, p: dict) -> None:
        self.stage("shortlist")
        rows = list(self.db.scalars(select(Company).where(Company.campaign_id == campaign.id, Company.archived.is_(False),
                                                          Company.review_status.in_(("new", "shortlisted")))))
        for c in rows:
            core.evaluate(c)
        waiting = sum(1 for c in rows if c.review_status == "shortlisted")
        room = max(0, int(p.get("daily_shortlist") or 5) - waiting)
        order = {"P0": 0, "P1": 1, "P2": 2}
        ready = sorted((c for c in rows if c.review_status == "new" and qualify.sales_ready(c.gates) and c.qualification != "P3"),
                       key=lambda c: (order.get(c.qualification, 9), -c.score))
        for c in ready[:room]:
            c.review_status = "shortlisted"
        with_retry(self._commit_or_rollback)
        self.say(f"{min(room, len(ready))} new prospect(s) added to Ready to Review "
                 f"({len(ready)} passed every check; {waiting} were already waiting)", ok=True)
        self._campaign_metrics(campaign)

    def _commit_or_rollback(self) -> None:
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _summary(self, campaign: Campaign) -> dict[str, Any]:
        q = self.db.query(Company).filter(Company.campaign_id == campaign.id, Company.archived.is_(False))
        out = {"companies": q.count(),
               "by_category": {k: q.filter(Company.qualification == k).count() for k in ("P0", "P1", "P2", "P3")},
               "ready_to_review": q.filter(Company.review_status == "shortlisted").count(),
               "verified_locations": q.filter(Company.location_confidence == "verified").count()}
        self.db.commit()
        return out
