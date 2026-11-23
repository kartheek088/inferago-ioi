"""Social-commerce discovery jobs.

Runs on the shared job machinery from 3.1 (`ioi_jobs`, one worker thread, heartbeat, stale-job
recovery, graceful stop, retry, lock-safe short writes), with its own stages and its own sources.
The channel column on the job decides which runner executes it.

Progress is honest: counters are grouped as **this run**, **sources** and **campaign totals**, and a
source is only reported as working after a real successful retrieval.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select

from app.db import SessionLocal, utcnow
from app.http_client import SafeHttp
from app.ioi3.engine import ACTIVE, MODES, ConfigError, JobConflict, Runner, wake
from app.ioi3.fetch import CachedHttp, Stats, short_write
from app.ioi3.models import SOCIAL, Campaign, Company, Job, SocialProfile
from app.ioi3.social import collect, core, qualify, research, search

log = logging.getLogger("ioi3.social.engine")

STAGES = [
    ("finding", "Discovering seller profiles"),
    ("identity", "Checking business identity"),
    ("location", "Verifying Chennai"),
    ("activity", "Reviewing public activity"),
    ("workflows", "Detecting order workflows"),
    ("research", "Researching promising sellers"),
    ("qualify", "Qualifying leads"),
]
STAGE_KEYS = [k for k, _ in STAGES]


def active_job(db, campaign_id: int) -> Job | None:
    return db.scalar(select(Job).where(Job.campaign_id == campaign_id, Job.status.in_(ACTIVE)))


def preflight(db, campaign: Campaign) -> dict[str, Any]:
    """What can run right now, in plain language. Never claims a source works untested."""
    st = core.campaign_settings(campaign)
    enabled = st.get("sources") or {}
    checks = []
    checks.append({"source": "manual_profile", "enabled": bool(enabled.get("manual_profile", True)), "ready": True,
                   "message": "Adding a profile or catalogue link by hand always works"})
    checks.append({"source": "csv_import", "enabled": bool(enabled.get("csv_import", True)), "ready": True,
                   "message": "Importing an authorised list always works"})
    av = search.availability()
    checks.append({"source": "public_search", "enabled": bool(enabled.get("public_search", True)), "ready": av.ready,
                   "message": av.message})
    pages = st.get("market_pages") or []
    checks.append({"source": "market_listings", "enabled": bool(enabled.get("market_listings", True)),
                   "ready": bool(pages),
                   "message": (f"{len(pages)} public market/exhibitor page(s) configured" if pages else
                               "No market pages added yet — add public Chennai market or exhibitor page links in Settings")})
    checks.append({"source": "business_features", "enabled": bool(enabled.get("business_features", True)), "ready": True,
                   "message": "Public Chennai business-news feeds"})
    checks.append({"source": "meta_api", "enabled": False, "ready": False,
                   "message": "Instagram/Facebook APIs are not set up, so profiles are never read automatically. "
                              "Open a profile yourself and use 'Record what you saw'."})
    from app.config import get_settings

    ai = get_settings().ai_enabled
    checks.append({"source": "ai", "enabled": st.get("depth") == "deep" and int(st.get("ai_max_calls") or 0) > 0,
                   "ready": ai,
                   "message": (f"AI is configured (up to {st.get('ai_max_calls')} calls per Deep run)" if ai else
                               "AI not configured — rule-based research still works")})
    discovery = [c for c in checks if c["source"] in ("public_search", "market_listings")]
    return {"checks": checks,
            # Research and qualification always work on sellers already added, so a run is never pointless.
            "can_start": True,
            "can_find_new": any(c["enabled"] and c["ready"] for c in discovery)}


def start_job(db, campaign: Campaign, *, mode: str | None = None, trigger: str = "manual",
              retry_of: Job | None = None, only_sources: list[str] | None = None,
              overrides: dict | None = None) -> Job:
    if active_job(db, campaign.id) is not None:
        raise JobConflict("A social-commerce discovery run is already in progress.")
    st = {**core.campaign_settings(campaign), **(overrides or {})}
    mode = mode or st.get("depth") or "balanced"
    if mode not in MODES:
        raise ConfigError(f"Unknown research depth '{mode}'")
    sources = [k for k, on in (st.get("sources") or {}).items() if on and k != "meta_api"]
    if only_sources:
        sources = [s for s in sources if s in only_sources]
    job = Job(
        campaign_id=campaign.id, channel=SOCIAL, mode=mode, status="queued", stage=None, stage_index=0,
        trigger=trigger, retry_of_id=retry_of.id if retry_of else None,
        counters={"run": {}, "sources": {}, "campaign": {}},
        sources={k: {"status": "waiting", "records": 0, "error": None} for k in sources},
        params={"max_candidates": int(st.get("max_candidates") or 40),
                "max_research": int(st.get("max_research") or 12),
                "daily_shortlist": int(st.get("daily_shortlist") or 5),
                "ai_max_calls": int(st.get("ai_max_calls") or 0),
                "categories": list(st.get("categories") or []),
                "search_terms": list(st.get("search_terms") or []),
                "market_pages": list(st.get("market_pages") or []),
                "sources": sources},
        log=[f"{datetime.now():%H:%M:%S} Queued ({mode})"])
    db.add(job)
    db.commit()
    wake()
    return job


class SocialRunner(Runner):
    """Runs one social-commerce discovery job, reusing the shared progress/heartbeat machinery."""

    STAGES = STAGES

    def stage(self, key: str) -> None:  # the social stage list, not the B2B one
        def f(j: Job) -> None:
            j.stage, j.stage_index = key, STAGE_KEYS.index(key) + 1
            j.summary = {**(j.summary or {}), "stage_started_at": utcnow().isoformat()}
        self._w(f)
        self.say(dict(STAGES)[key])

    def run(self) -> None:
        with SessionLocal() as db:
            self.db = db
            job = db.get(Job, self.job_id)
            campaign_id, mode, p = job.campaign_id, job.mode, dict(job.params or {})
            db.commit()

            def start(j: Job) -> None:
                j.status, j.started_at = "running", utcnow()
                j.counters = {"run": {"found": 0, "reviewed": 0, "added": 0, "duplicates": 0, "rejected": 0,
                                      "researched": 0, "research_failed": 0, "newly_qualified": 0, "ai_calls": 0},
                              "sources": {}, "campaign": {}}
            self._w(start)
            campaign = db.get(Campaign, campaign_id)
            srcs = set(p.get("sources") or [])
            self.ready_before = {c.id for c in db.scalars(
                select(Company).where(Company.campaign_id == campaign_id)) if qualify.ready(c.gates or [])}
            db.commit()
            http = self.http_factory()
            status, error = "completed", None
            try:
                self._search(campaign, p, srcs, http)
                if not self.stopping():
                    self._markets(campaign, p, srcs, http)
                if not self.stopping() and mode != "quick":
                    self._research(campaign, p, deep=mode == "deep")
                if not self.stopping() and mode == "deep" and not getattr(self, "network_down", False):
                    self._agent(campaign, p)
                self._shortlist(campaign, p)
                if self.stopping():
                    status = "stopped"
            except Exception as exc:  # noqa: BLE001
                log.exception("social job failed")
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
                j.log = [*(j.log or []),
                         f"{datetime.now():%H:%M:%S} {'Stopped' if status == 'stopped' else status.title()}"
                         + (f" — {len(failed)} source(s) failed" if failed else "")]
            self._w(finish)

    # --- stages ----------------------------------------------------------------------------------
    def _search(self, campaign: Campaign, p: dict, srcs: set[str], http: SafeHttp) -> None:
        self.stage("finding")
        if "public_search" not in srcs:
            self.say("Public web search is switched off for this run")
            return
        av = search.availability()
        if not av.ready:
            core.mark_source_failed(self.db, "public_search", f"needs_setup: {av.message}")
            self.source("public_search", status="failed", error=av.message, kind="permanent")
            self.say(f"Public web search unavailable: {av.message}")
            return
        self.source("public_search", status="running")
        queries = search.queries_for(list(p.get("categories") or []), list(p.get("search_terms") or []))
        limit = int(p.get("max_candidates") or 40)
        stats = {"queries": 0, "hits": 0, "processed": 0, "accepted": 0, "duplicate": 0, "outside_chennai": 0,
                 "not_social_category": 0, "no_profile": 0, "already_seen": 0}
        cands = []
        for q in queries:
            if self.stopping():
                break
            try:
                hits = search.run(http, q)
            except Exception as exc:  # noqa: BLE001 — one failed query must not end the run
                self.say(f"Search failed for '{q[:50]}': {str(exc)[:120]}")
                continue
            stats["queries"] += 1
            stats["hits"] += len(hits)
            for h in hits:
                cnd = search.hit_to_candidate(h)
                if cnd is not None:
                    cands.append(cnd)
        self.say(f"{stats['queries']} search(es) returned {stats['hits']} results, {len(cands)} look like seller profiles",
                 ok=stats["queries"] > 0)
        self.stage("identity")
        for cnd in cands[:limit]:
            if self.stopping():
                break
            r = collect.ingest(self.db, campaign, cnd, job_id=self.job_id, require_category=True)
            self.db.commit()
            stats[r.outcome] = stats.get(r.outcome, 0) + 1
            stats["processed"] += 1
            self.metrics("run", found=len(cands), reviewed=stats["processed"], added=stats["accepted"],
                         duplicates=stats["duplicate"],
                         rejected=stats["outside_chennai"] + stats["not_social_category"] + stats["no_profile"])
        ok = stats["queries"] > 0
        if ok:
            core.mark_source_ok(self.db, "public_search", records=stats["accepted"],
                                freshness=f"{stats['queries']} queries on {utcnow():%d %b %Y}")
            self.db.commit()
        self.source("public_search", status="done" if ok else "failed", records=stats["accepted"])
        self.say(f"This run: {stats['processed']} reviewed · {stats['accepted']} added · {stats['duplicate']} duplicates · "
                 f"{stats['outside_chennai']} outside Chennai · {stats['not_social_category']} wrong category", ok=ok)
        self._campaign_metrics(campaign)

    def _markets(self, campaign: Campaign, p: dict, srcs: set[str], http: SafeHttp) -> None:
        pages = list(p.get("market_pages") or [])
        if "market_listings" not in srcs or not pages:
            if "market_listings" in srcs:
                self.say("No public market or exhibitor pages are configured — skipping")
            return
        self.source("market_listings", status="running")
        self.say(f"Reading {len(pages)} public market/exhibitor page(s)")
        stats = collect.collect_market_pages(
            self.db, campaign, CachedHttp(http), pages, limit=int(p.get("max_candidates") or 40),
            job_id=self.job_id, progress=lambda msg, st: self.say(msg), should_stop=self.stopping)
        ok = stats["pages_read"] > 0
        if ok:
            core.mark_source_ok(self.db, "market_listings", records=stats["accepted"],
                                freshness=f"{stats['pages_read']} page(s) read {utcnow():%d %b %Y}")
        else:
            core.mark_source_failed(self.db, "market_listings", "; ".join(stats["errors"])[:400] or "No page could be read")
        self.db.commit()
        self.source("market_listings", status="done" if ok else "failed", records=stats["accepted"],
                    error="; ".join(stats["errors"])[:200] or None)
        self.say(f"Market pages: {stats['pages_read']} read, {stats['pages_failed']} failed · {stats['found']} sellers named · "
                 f"{stats['accepted']} added · {stats['duplicate']} duplicates", ok=ok)
        self._campaign_metrics(campaign)

    def _research(self, campaign: Campaign, p: dict, *, deep: bool) -> None:
        self.stage("location")
        limit = int(p.get("max_research") or 12)
        now = utcnow()
        want = ("profile", "public") if deep else ("profile",)
        rows = list(self.db.scalars(
            select(Company).join(SocialProfile, SocialProfile.company_id == Company.id)
            .where(Company.campaign_id == campaign.id, Company.archived.is_(False),
                   Company.qualification != qualify.S3,
                   Company.review_status.in_(("new", "shortlisted", "watchlist")),
                   SocialProfile.research_level.in_(want),
                   or_(SocialProfile.research_retry_after.is_(None), SocialProfile.research_retry_after <= now))
            .order_by(Company.prescore.desc(), Company.id).limit(limit)))
        if not rows:
            self.say("No sellers are waiting to be researched")
            self._campaign_metrics(campaign)
            return
        self.stage("activity")
        self.source("seller_pages", status="running")
        readable = sum(1 for c in rows if research.readable_targets(c))
        blocked = len(rows) - readable
        self.say(f"Researching {len(rows)} seller(s), 4 at a time. {readable} have a page IOI can read"
                 + (f"; {blocked} only have a social profile, which a person has to open" if blocked else ""))
        self.stage("workflows")
        done = {"n": 0, "failed": 0, "nq": 0}
        stats = Stats()

        def on_done(c: Company) -> None:
            done["n"] += 1
            if c.social and c.social.research_error:
                done["failed"] += 1
            if qualify.ready(c.gates or []) and c.id not in self.ready_before:
                self.ready_before.add(c.id)
                done["nq"] += 1
            self.metrics("run", researched=done["n"], research_failed=done["failed"], newly_qualified=done["nq"])
            detail = ((c.social.research_error or "")[:110] if c.social and c.social.research_error
                      else ("passes every check" if qualify.ready(c.gates or []) else (c.next_action or c.qualification)))
            self.say(f"Researched {done['n']} of {len(rows)}: {c.name} — {detail}",
                     ok=not (c.social and c.social.research_error))

        self.stage("research")
        res = research.research_many(self.db, rows, deep=deep, on_done=on_done, should_stop=self.stopping, stats=stats,
                                    ai_calls_left=int(p.get("ai_max_calls") or 0) if deep else 0)
        if res.get("network_outage"):
            self.network_down = True
            core.mark_source_failed(self.db, "manual_profile", "Network/DNS problem on this computer")
            self.source("seller_pages", status="failed", records=res["researched"],
                        error="Network/DNS problem on this computer", kind="retryable")
            self.say("This computer couldn't reach the internet (DNS lookups failing), so research stopped early. "
                     "Nothing was blamed on the sellers; they'll be retried in about 15 minutes.")
        else:
            self.source("seller_pages", status="done", records=res["researched"],
                        error=(f"{res['failed']} seller page(s) could not be loaded" if res["failed"] else None))
            self.say(f"Research: {res['researched']} done · {res['failed']} failed · "
                     f"{res['nothing_readable']} need a person to open their profile", ok=res["researched"] > 0)
        self.metrics("run", pages_fetched=res["pages_fetched"], cache_hits=res["cache_hits"],
                     revalidated_304=res["revalidated_304"], ai_calls=res.get("ai_calls", 0))
        self._campaign_metrics(campaign)

    def _agent(self, campaign: Campaign, p: dict) -> None:
        from app.ioi3.social import agent

        budget = int(p.get("ai_max_calls") or 0)
        if budget <= 0:
            self.say("AI research is switched off for this run (AI call limit is 0) — rule-based research only")
            return
        if not agent.available(self.db):
            self.say("AI unavailable — rule-based research active")
            self.source("ai_agent", status="failed", error="AI not configured or not reachable", kind="permanent")
            return
        rows = [c for c in self.db.scalars(
            select(Company).join(SocialProfile, SocialProfile.company_id == Company.id)
            .where(Company.campaign_id == campaign.id, Company.archived.is_(False),
                   Company.qualification != qualify.S3,
                   Company.review_status.in_(("new", "shortlisted", "watchlist")),
                   SocialProfile.research_error.is_(None), SocialProfile.research_level != "profile")
            .order_by(Company.score.desc(), Company.id))
            if c.ai_status in ("not_run", "failed", "unavailable") and research.readable_targets(c)
        ][: max(1, min(5, budget // 4))]
        self.db.commit()
        if not rows:
            self.say("No seller has a readable page for the AI agent to investigate yet")
            return
        self.source("ai_agent", status="running")
        self.say(f"AI research agent: investigating {len(rows)} strongest seller(s) "
                 f"(max {agent.LIMITS.max_model_calls} AI calls each, their own pages only)")
        calls = 0
        for c in rows:
            if self.stopping() or calls >= budget:
                break
            out = agent.investigate(self.db, c, job_id=self.job_id,
                                    max_model_calls=min(agent.LIMITS.max_model_calls, budget - calls),
                                    should_stop=self.stopping)
            calls += out.model_calls
            self.say(f"AI agent finished {c.name}: {out.outcome} ({out.model_calls} AI calls, {out.facts} new facts, "
                     f"{out.complexity} complexity indicators)", ok=out.outcome != "failed")
            if out.outcome == "failed" and out.model_calls == 0:
                self.say("AI provider unreachable — stopping AI research for this run. Rule-based results are kept.")
                self.source("ai_agent", status="failed", error="AI provider unreachable", kind="retryable")
                self.metrics("run", ai_calls=calls)
                return
        self.source("ai_agent", status="done", records=len(rows))
        self.metrics("run", ai_calls=calls)

    def _shortlist(self, campaign: Campaign, p: dict) -> None:
        self.stage("qualify")
        rows = list(self.db.scalars(select(Company).where(
            Company.campaign_id == campaign.id, Company.archived.is_(False),
            Company.review_status.in_(("new", "shortlisted")))))
        from app.ioi3 import core as b2b_core

        for c in rows:
            b2b_core.evaluate(c)
        waiting = sum(1 for c in rows if c.review_status == "shortlisted")
        room = max(0, int(p.get("daily_shortlist") or 5) - waiting)
        order = {qualify.S0: 0, qualify.S1: 1, qualify.S2: 2}
        ready = sorted((c for c in rows if c.review_status == "new" and qualify.ready(c.gates or [])
                        and c.qualification != qualify.S3),
                       key=lambda c: (order.get(c.qualification, 9), -c.score))
        for c in ready[:room]:
            c.review_status = "shortlisted"
        from app.ioi3.fetch import with_retry

        with_retry(self._commit_or_rollback)
        self.say(f"{min(room, len(ready))} new seller(s) added to Ready to Review "
                 f"({len(ready)} passed every check; {waiting} were already waiting)", ok=True)
        self._campaign_metrics(campaign)

    def _campaign_metrics(self, campaign: Campaign) -> None:
        rows = self.db.query(Company).filter(Company.campaign_id == campaign.id,
                                             Company.archived.is_(False)).all()
        self.db.commit()
        from app.ioi3.social import geo as geomod

        self.metrics("campaign", sellers=len(rows),
                     verified_sellers=sum(1 for c in rows if c.social and c.social.geo_confidence == geomod.VERIFIED),
                     needs_verification=sum(1 for c in rows if c.qualification != qualify.S3
                                            and not qualify.ready(c.gates or [])),
                     high_fit=sum(1 for c in rows if c.qualification in (qualify.S0, qualify.S1)),
                     ready_to_review=sum(1 for c in rows if c.review_status == "shortlisted"))

    def _summary(self, campaign: Campaign) -> dict[str, Any]:
        q = self.db.query(Company).filter(Company.campaign_id == campaign.id, Company.archived.is_(False))
        out = {"sellers": q.count(),
               "by_category": {k: q.filter(Company.qualification == k).count()
                               for k in (qualify.S0, qualify.S1, qualify.S2, qualify.S3)},
               "ready_to_review": q.filter(Company.review_status == "shortlisted").count()}
        self.db.commit()
        return out
