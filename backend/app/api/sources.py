"""Sources, source runs, discovery jobs and manual imports."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.api.deps import DB, Paging, actor, paginate
from app.config import get_settings
from app.documents import DocumentError
from app.enums import ConnectorStatus
from app.http_client import FetchError
from app.imports import import_document, import_url
from app.models import DiscoveryJob, Source, SourceRun
from app.schemas import (
    DiscoveryJobIn,
    DiscoveryJobOut,
    ImportOut,
    Page,
    SourceCreate,
    SourceOut,
    SourceRunOut,
    SourceUpdate,
    UrlImportIn,
)
from app.settings_store import log_activity

router = APIRouter()


@router.get("/sources", response_model=list[SourceOut], tags=["sources"])
def list_sources(db: Session = DB):
    return db.scalars(select(Source).order_by(Source.connector_status, Source.name)).all()


@router.get("/sources/{source_id}", response_model=SourceOut, tags=["sources"])
def get_source(source_id: int, db: Session = DB):
    s = db.get(Source, source_id)
    if not s:
        raise HTTPException(404, "Source not found")
    return s


@router.post("/sources", response_model=SourceOut, status_code=201, tags=["sources"])
def create_rss_source(body: SourceCreate, db: Session = DB, who: str = Depends(actor)):
    """Add a permitted RSS/Atom feed source (the only kind that can be added at runtime)."""
    if db.scalar(select(Source.id).where(Source.key == body.key)):
        raise HTTPException(409, "Source key already exists")
    s = Source(
        key=body.key, name=body.name, base_url=str(body.feed_url), category="public_project_community", access_method="rss",
        connector="rss", connector_status=ConnectorStatus.LIVE.value, country=body.country, region=body.region,
        terms_notes=body.terms_notes or "Owner-added feed; owner confirms permission to consume.",
        collection_frequency_minutes=body.collection_frequency_minutes, enabled=False,
        config={"feed_url": str(body.feed_url), "require_term_match": body.require_term_match},
        coverage=f"RSS feed {body.feed_url}",
    )
    db.add(s)
    log_activity(db, "source", None, "created", {"key": body.key}, who)
    db.commit()
    return s


@router.patch("/sources/{source_id}", response_model=SourceOut, tags=["sources"])
def update_source(source_id: int, body: SourceUpdate, db: Session = DB, who: str = Depends(actor)):
    s = db.get(Source, source_id)
    if not s:
        raise HTTPException(404, "Source not found")
    data = body.model_dump(exclude_none=True)
    if data.get("enabled") and s.connector_status == ConnectorStatus.PLANNED.value:
        raise HTTPException(400, "Planned sources have no connector and cannot be enabled")
    if data.get("enabled") and s.connector_status == ConnectorStatus.CREDENTIAL_GATED.value and s.key == "reddit" and not get_settings().reddit_configured:
        raise HTTPException(400, "Reddit credentials are not configured (see docs/SOURCES.md)")
    if "config" in data:
        cfg = dict(s.config or {})
        cfg.update(data.pop("config"))
        if s.connector == "rss" and cfg.get("feed_url"):
            from pydantic import HttpUrl, TypeAdapter, ValidationError

            try:
                TypeAdapter(HttpUrl).validate_python(cfg["feed_url"])
            except ValidationError as exc:
                raise HTTPException(422, "feed_url must be a valid http(s) URL") from exc
        s.config = cfg
    for k, v in data.items():
        setattr(s, k, v)
    log_activity(db, "source", s.id, "updated", {"fields": list(body.model_dump(exclude_none=True))}, who)
    db.commit()
    jobs.sync_schedule()
    return s


@router.get("/source-runs", response_model=Page[SourceRunOut], tags=["source runs"])
def list_runs(source_id: int | None = None, status: str | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(SourceRun).order_by(SourceRun.id.desc())
    if source_id:
        stmt = stmt.where(SourceRun.source_id == source_id)
    if status:
        stmt = stmt.where(SourceRun.status == status)
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/source-runs/{run_id}", response_model=SourceRunOut, tags=["source runs"])
def get_run(run_id: int, db: Session = DB):
    r = db.get(SourceRun, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    return r


@router.post("/discovery/jobs", response_model=DiscoveryJobOut, status_code=202, tags=["discovery"])
def create_job(body: DiscoveryJobIn, wait: bool = False, db: Session = DB, who: str = Depends(actor)):
    """Start a manual discovery run. Runs in the background unless `wait=true`."""
    srcs = {s.key: s for s in db.scalars(select(Source).where(Source.key.in_(body.source_keys))).all()}
    missing = [k for k in body.source_keys if k not in srcs]
    if missing:
        raise HTTPException(404, f"Unknown sources: {missing}")
    not_runnable = [k for k, s in srcs.items() if not s.connector or not s.enabled]
    if not_runnable:
        raise HTTPException(400, f"Sources not runnable (disabled or no live connector): {not_runnable}")
    job = DiscoveryJob(trigger="manual", source_keys=body.source_keys, query_terms=body.query_terms, status="running")
    db.add(job)
    log_activity(db, "discovery_job", None, "started", {"sources": body.source_keys, "terms": body.query_terms}, who)
    db.commit()
    jobs.submit_discovery(job.id, background=not wait)
    db.refresh(job)
    return job


@router.get("/discovery/jobs", response_model=Page[DiscoveryJobOut], tags=["discovery"])
def list_jobs(paging: Paging = Depends(), db: Session = DB):
    items, total = paginate(db, select(DiscoveryJob).order_by(DiscoveryJob.id.desc()), paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/discovery/jobs/{job_id}", response_model=DiscoveryJobOut, tags=["discovery"])
def get_job(job_id: int, db: Session = DB):
    j = db.get(DiscoveryJob, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@router.post("/imports/url", response_model=ImportOut, tags=["discovery"])
def import_url_api(body: UrlImportIn, db: Session = DB, who: str = Depends(actor)):
    try:
        out = import_url(db, str(body.url), org_name=body.organisation_name, note=body.note, actor=who)
    except FetchError as exc:
        raise HTTPException(400, f"Could not fetch URL: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ImportOut(status=out.status, opportunity_id=out.opportunity_id, reason=out.reason)


@router.post("/imports/document", response_model=ImportOut, tags=["discovery"])
async def import_document_api(
    file: UploadFile = File(...),
    buyer: str | None = Form(None),
    source_url: str | None = Form(None),
    db: Session = DB,
    who: str = Depends(actor),
):
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "File too large")
    if source_url and not source_url.startswith(("http://", "https://")):
        raise HTTPException(422, "source_url must be http(s)")
    try:
        out, doc = import_document(db, file.filename or "document", data, buyer=buyer, source_url=source_url, actor=who)
    except DocumentError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ImportOut(status=out.status, opportunity_id=out.opportunity_id, reason=out.reason, document=doc)
