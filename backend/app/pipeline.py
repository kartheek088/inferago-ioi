"""Ingestion pipeline: collect → raw record → classify → dedupe → organisation → evidence →
signals/contacts/requirements → eligibility → scoring.

Repeated runs are idempotent: raw records are unique per (source, external_id) and opportunities
per dedupe key; duplicates found via canonical URL or content hash are merged by attaching
evidence (provenance preserved) instead of creating a new opportunity.
"""

import threading
import time
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.extraction import AIBudget, ai_refine_classification, should_refine
from app.ai.openrouter import get_ai
from app.classification import ClassificationResult, classify
from app.connectors.base import CollectContext, CollectedItem, Connector, ConnectorUnavailable
from app.connectors.hackernews import PLATFORM_DOMAINS, HackerNewsConnector
from app.connectors.gem import GeMConnector
from app.connectors.reddit import RedditConnector
from app.connectors.rss import RSSConnector
from app.db import utcnow
from app.eligibility import extract_requirements, requirements_from_classification
from app.enums import Category, OpportunityStatus, RunStatus
from app.evaluation import evaluate_opportunity
from app.http_client import FetchError, SafeHttp
from app.models import (
    BuyingSignal,
    Contact,
    DiscoveryJob,
    EligibilityRequirement,
    Evidence,
    Opportunity,
    Organisation,
    RawRecord,
    Source,
    SourceRun,
)
from app.normalize import canonical_url, content_hash, domain_of, normalize_org_name, truncate
from app.relationships import find_relationships, link_same_buyer, record_found
from app.settings_store import get_setting, log_activity

CONNECTORS: dict[str, Connector] = {
    "hackernews": HackerNewsConnector(),
    "rss": RSSConnector(),
    "reddit": RedditConnector(),
    "gem": GeMConnector(),
}

_source_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()
STALE_RUN_AFTER = timedelta(hours=2)


def _lock_for(source_id: int) -> threading.Lock:
    with _locks_guard:
        return _source_locks.setdefault(source_id, threading.Lock())


@dataclass
class IngestOutcome:
    status: str  # new | duplicate | rejected | updated
    opportunity_id: int | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------------------------
# Organisation resolution (conservative)
# ---------------------------------------------------------------------------------------------


def resolve_organisation(db: Session, name: str | None, website: str | None, *, country: str | None = None, region: str | None = None, is_demo: bool = False) -> Organisation | None:
    dom = domain_of(website)
    if dom and any(dom == d or dom.endswith("." + d) for d in PLATFORM_DOMAINS):
        dom, website = None, None
    norm = normalize_org_name(name)
    if dom:
        org = db.scalar(select(Organisation).where(Organisation.domain == dom).order_by(Organisation.domain_verified.desc()).limit(1))
        if org:
            return org
    if norm:
        # Exact normalised-name match only, and never across conflicting domains.
        candidates = db.scalars(select(Organisation).where(Organisation.normalized_name == norm)).all()
        for org in candidates:
            if not org.domain or not dom:
                if dom and not org.domain:
                    org.domain, org.website = dom, website
                return org
    if not norm and not dom:
        return None
    org = Organisation(
        name=(name or dom or "Unknown").strip()[:300], normalized_name=norm or (dom or ""), domain=dom,
        website=website, country=country, region=region, is_demo=is_demo,
    )
    db.add(org)
    db.flush()
    return org


# ---------------------------------------------------------------------------------------------
# Item ingestion
# ---------------------------------------------------------------------------------------------


def find_duplicate(db: Session, dedupe_key: str, canon: str | None, chash: str) -> Opportunity | None:
    opp = db.scalar(select(Opportunity).where(Opportunity.dedupe_key == dedupe_key))
    if opp:
        return opp
    if canon:
        opp = db.scalar(select(Opportunity).where(Opportunity.canonical_url == canon, Opportunity.merged_into_id.is_(None)).limit(1))
        if opp:
            return opp
    return db.scalar(select(Opportunity).where(Opportunity.content_hash == chash, Opportunity.merged_into_id.is_(None)).limit(1))


def ingest_item(db: Session, source: Source, run: SourceRun | None, item: CollectedItem, *, is_demo: bool = False, actor: str = "system", ai_budget: AIBudget | None = None) -> IngestOutcome:
    chash = content_hash(item.title, item.content)
    canon = canonical_url(item.url)
    raw = db.scalar(select(RawRecord).where(RawRecord.source_id == source.id, RawRecord.external_id == item.external_id))
    if raw and raw.content_hash == chash:
        opp = db.scalar(select(Opportunity).where(Opportunity.dedupe_key == f"src:{source.key}:{item.external_id}"))
        return IngestOutcome("duplicate", opp.id if opp else None, "Already collected (unchanged)")
    changed = raw is not None
    if raw is None:
        raw = RawRecord(source_id=source.id, external_id=item.external_id)
        db.add(raw)
    raw.run_id = run.id if run else None
    raw.canonical_url, raw.title, raw.content, raw.author = canon, item.title, item.content, item.author
    raw.published_at, raw.retrieved_at, raw.content_hash, raw.raw_payload = item.published_at, utcnow(), chash, item.raw
    db.flush()

    cls = classify(item.title, item.content, source_category=source.category)
    if ai_budget is not None and should_refine(cls) and not item.needs_manual_review:
        ai = ai_budget.take()
        if ai is not None:
            ai_refine_classification(ai, item.title, item.content, cls)
    if cls.category in (Category.IRRELEVANT, Category.UNKNOWN) and not item.needs_manual_review:
        return IngestOutcome("rejected", None, f"{cls.category.value}: {'; '.join(cls.evidence)[:200]}")

    dedupe_key = f"src:{source.key}:{item.external_id}"
    existing = find_duplicate(db, dedupe_key, canon, chash)
    evidence = Evidence(
        raw_record_id=raw.id, source_id=source.id, evidence_type=item.evidence_type, url=item.url,
        excerpt=truncate(item.content, 4000) or (item.title or ""), published_at=item.published_at,
        document_name=item.document_name,
    )
    if existing is not None:
        evidence.opportunity_id = existing.id
        evidence.organisation_id = existing.organisation_id
        db.add(evidence)
        if changed and existing.dedupe_key == dedupe_key:
            existing.description, existing.content_hash = item.content, chash
            _apply_classification(existing, cls)
            evaluate_opportunity(db, existing)
            log_activity(db, "opportunity", existing.id, "updated_from_source", {"source": source.key, "external_id": item.external_id}, actor)
            return IngestOutcome("updated", existing.id, "Source content changed; evidence appended")
        log_activity(db, "opportunity", existing.id, "duplicate_merged", {"source": source.key, "external_id": item.external_id, "url": item.url}, actor)
        return IngestOutcome("duplicate", existing.id, "Matched existing opportunity; provenance recorded")

    org = resolve_organisation(db, item.org_name, item.org_website, country=cls.country, region=cls.region, is_demo=is_demo)
    opp = Opportunity(
        title=truncate(item.title or item.content.split("\n", 1)[0], 500),
        summary=truncate(item.content, 400),
        description=item.content,
        organisation_id=org.id if org else None,
        canonical_url=canon,
        source_id=source.id,
        dedupe_key=dedupe_key,
        content_hash=chash,
        published_at=item.published_at,
        retrieved_at=utcnow(),
        status=OpportunityStatus.NEEDS_MANUAL_REVIEW.value if item.needs_manual_review else OpportunityStatus.NEW.value,
        needs_manual_review=item.needs_manual_review,
        is_demo=is_demo,
        deadline=item.deadline,
    )
    _apply_classification(opp, cls)
    if item.budget_text and not opp.budget_text:
        opp.budget_text = item.budget_text[:300]
    db.add(opp)
    db.flush()
    evidence.opportunity_id = opp.id
    evidence.organisation_id = org.id if org else None
    db.add(evidence)
    db.flush()

    for s in cls.signals:
        db.add(BuyingSignal(opportunity_id=opp.id, signal_type=s.signal_type, strength=s.strength, text=s.text, evidence_id=evidence.id))
    for ctype, value, src_url, verified, method in item.contact_routes:
        db.add(Contact(
            organisation_id=org.id if org else None, opportunity_id=opp.id, contact_type=ctype, value=value[:500],
            source_url=src_url, verified=verified, verification_method=method,
            verification_date=utcnow() if verified else None,
        ))
    pages = item.pages or [(None, item.content)]
    reqs = extract_requirements(pages) + requirements_from_classification(cls.country_restrictions, cls.worldwide)
    for r in reqs:
        db.add(EligibilityRequirement(
            opportunity_id=opp.id, scope=r.scope.value, requirement_key=r.key.value, mandatory=r.mandatory,
            text=r.text, parameters=r.parameters, origin="document" if item.pages else "rules",
            evidence_id=evidence.id, page_reference=r.page_reference,
        ))
    db.flush()
    if org and item.url:
        record_found(db, org, item.url, find_relationships(item.content))
        link_same_buyer(db, opp)
    evaluate_opportunity(db, opp)
    log_activity(db, "opportunity", opp.id, "created", {"source": source.key, "category": opp.category, "pipeline": opp.pipeline}, actor)
    return IngestOutcome("new", opp.id)


def _apply_classification(opp: Opportunity, cls: ClassificationResult) -> None:
    opp.category = cls.category.value
    opp.pipeline = cls.pipeline.value
    opp.classification_confidence = cls.confidence
    opp.classification_method = cls.method
    opp.classification_evidence = cls.evidence
    opp.services_matched = cls.services
    opp.signals_matched = [s.signal_type for s in cls.signals]
    opp.country, opp.region, opp.geography_basis = cls.country, cls.region, cls.geography_basis
    opp.remote_ok = cls.remote_ok
    opp.budget_text = cls.budget_text


# ---------------------------------------------------------------------------------------------
# Source runs
# ---------------------------------------------------------------------------------------------


def run_source(
    db: Session,
    source: Source,
    *,
    trigger: str = "manual",
    query_terms: list[str] | None = None,
    discovery_job_id: int | None = None,
    http_client: httpx.Client | None = None,
    resolver=None,
) -> SourceRun:
    lock = _lock_for(source.id)
    now = utcnow()
    running = db.scalar(select(SourceRun).where(SourceRun.source_id == source.id, SourceRun.status == RunStatus.RUNNING.value).limit(1))
    if running and now - running.started_at > STALE_RUN_AFTER:
        running.status, running.error_message, running.finished_at = RunStatus.FAILED.value, "Marked stale (process ended mid-run)", now
        running = None
    if running or not lock.acquire(blocking=False):
        run = SourceRun(source_id=source.id, discovery_job_id=discovery_job_id, trigger=trigger, status=RunStatus.SKIPPED.value,
                        finished_at=now, error_message="Another run for this source is in progress (duplicate-run protection)")
        db.add(run)
        db.commit()
        return run
    try:
        return _run_source_locked(db, source, trigger, query_terms, discovery_job_id, http_client, resolver)
    finally:
        lock.release()


def _run_source_locked(db, source, trigger, query_terms, discovery_job_id, http_client, resolver) -> SourceRun:
    run = SourceRun(source_id=source.id, discovery_job_id=discovery_job_id, trigger=trigger, status=RunStatus.RUNNING.value, log=[])
    db.add(run)
    source.last_checked_at = utcnow()
    db.commit()
    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(f"{utcnow().isoformat(timespec='seconds')} {msg}")

    connector = CONNECTORS.get(source.connector or "")
    if not source.enabled or connector is None:
        run.status = RunStatus.FAILED.value
        run.error_message = "Source is disabled" if not source.enabled else f"No live connector for '{source.connector}' ({source.connector_status})"
        run.finished_at = utcnow()
        db.commit()
        return run

    kwargs = {"rate_limit_per_minute": source.rate_limit_per_minute}
    if resolver:
        kwargs["resolver"] = resolver
    http = SafeHttp(http_client, **kwargs)
    terms = query_terms if query_terms is not None else (source.config.get("query_terms") or get_setting(db, "search_terms"))
    cursor = dict(source.cursor or {})
    ctx = CollectContext(http=http, config=source.config or {}, cursor=cursor, query_terms=terms, max_items=source.max_items_per_run, log=log)
    item_errors = 0
    started = time.monotonic()
    ai_budget = None
    if get_setting(db, "ai_classification_refinement"):
        ai_budget = AIBudget(get_ai(db), int((source.config or {}).get("ai_refine_max_per_run", 10)))
    try:
        for item in connector.collect(ctx):
            run.items_fetched += 1
            try:
                with db.begin_nested():
                    outcome = ingest_item(db, source, run, item, ai_budget=ai_budget)
                if outcome.status == "new":
                    run.items_new += 1
                elif outcome.status in ("duplicate", "updated"):
                    run.items_duplicate += 1
                else:
                    run.items_rejected += 1
            except Exception as exc:  # noqa: BLE001 - per-item isolation
                item_errors += 1
                log(f"Item {item.external_id} failed: {type(exc).__name__}: {exc}")
        source.cursor = cursor
        run.status = RunStatus.PARTIAL.value if item_errors else RunStatus.SUCCESS.value
        source.last_success_at = utcnow()
        source.failure_status = None if not item_errors else f"{item_errors} item error(s) in last run"
        source.consecutive_failures = 0
    except ConnectorUnavailable as exc:
        run.status, run.error_message = RunStatus.FAILED.value, str(exc)
        source.failure_status, source.consecutive_failures = str(exc)[:500], source.consecutive_failures + 1
    except (FetchError, ValueError, httpx.HTTPError) as exc:
        run.status, run.error_message = RunStatus.FAILED.value, f"{type(exc).__name__}: {exc}"
        source.failure_status, source.consecutive_failures = run.error_message[:500], source.consecutive_failures + 1
        source.cursor = source.cursor  # cursor unchanged on failure → next run retries
    finally:
        run.requests_made = http.requests_made
        run.finished_at = utcnow()
        if ai_budget is not None and ai_budget.ai is not None:
            log(f"AI classification refinement calls: {ai_budget.ai.calls}")
        log(f"Finished in {time.monotonic() - started:.1f}s: fetched={run.items_fetched} new={run.items_new} dup={run.items_duplicate} rejected={run.items_rejected}")
        run.log = logs[-200:]
        log_activity(db, "source", source.id, f"run_{run.status}", {"run_id": run.id, "new": run.items_new})
        db.commit()
        if http_client is None:
            http.close()
    return run


def run_discovery_job(db: Session, job: DiscoveryJob, *, http_client: httpx.Client | None = None, resolver=None) -> DiscoveryJob:
    stats = {"runs": [], "new": 0, "duplicate": 0, "rejected": 0, "failed_sources": []}
    for key in job.source_keys:
        source = db.scalar(select(Source).where(Source.key == key))
        if not source:
            stats["failed_sources"].append({"source": key, "error": "unknown source"})
            continue
        run = run_source(db, source, trigger=job.trigger, query_terms=job.query_terms or None, discovery_job_id=job.id, http_client=http_client, resolver=resolver)
        stats["runs"].append(run.id)
        stats["new"] += run.items_new
        stats["duplicate"] += run.items_duplicate
        stats["rejected"] += run.items_rejected
        if run.status in (RunStatus.FAILED.value, RunStatus.SKIPPED.value):
            stats["failed_sources"].append({"source": key, "error": run.error_message})
    job.stats = stats
    job.status = "failed" if len(stats["failed_sources"]) == len(job.source_keys) and job.source_keys else ("partial" if stats["failed_sources"] else "success")
    job.finished_at = utcnow()
    db.commit()
    return job
