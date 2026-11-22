"""Prospects: businesses/professionals with potential but weak or no online presence."""

import csv
import io
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Float, Integer, func, or_, select
from sqlalchemy.orm import Session

from app import jobs
from app.api.deps import NATIONWIDE, DB, Paging, actor, paginate
from app.config import get_settings
from app.db import utcnow
from app.models import Prospect, ProspectRun
from app.profile import SERVICE_KEYS
from app.prospects import AREA_GROUPS, AREAS, OPEN_STATUSES, REGIONS, SearchRules, audit_website, evaluate, pitch, record_contact, resolve_area
from app.schemas import CheckWebsitesIn, MapScanIn, OvertureScanIn, Page, ProspectContactIn, ProspectOut, ProspectRunOut, ProspectSearchIn, ProspectUpdate
from app.settings_store import get_setting, log_activity

router = APIRouter(tags=["prospects"])

def _rules(db: Session) -> SearchRules:
    return SearchRules(
        only_no_website=bool(get_setting(db, "prospect_only_no_website")),
        require_phone=bool(get_setting(db, "prospect_require_phone")),
    )


SORTS = {
    "score": Prospect.score.desc(),
    "newest": Prospect.created_at.desc(),
    "follow_up": Prospect.next_follow_up.asc(),
    "name": Prospect.name.asc(),
}


def _get(db: Session, pid: int) -> Prospect:
    p = db.get(Prospect, pid)
    if not p:
        raise HTTPException(404, "Prospect not found")
    return p


FOCUS_PATTERN = "^(new|hidden|shops|real_estate|delivery|art|partners)$"


def _focus(stmt, focus):
    from sqlalchemy import String as _S

    from app.prospects import NICHES

    if not focus:
        return stmt
    if focus == "new":
        return stmt.where(Prospect.new_listing.is_(True))
    if focus == "hidden":  # good business, no website and no social page: nobody is helping them online yet
        return stmt.where(Prospect.quality_level.in_(("good", "established")), Prospect.has_website.is_(False),
                          Prospect.social_links.cast(_S).in_(("[]", "null")))
    words = [w for w in NICHES[focus]["match"].split("|") if w]
    # type label + the category part of business_type ("shop=bakery" → "bakery", "overture=dentist" → "dentist")
    kind = func.lower(Prospect.type_label + " " + func.substr(Prospect.business_type, func.instr(Prospect.business_type, "=") + 1))
    return stmt.where(or_(*[kind.like(f"%{w.replace('_', ' ')}%") for w in words], *[kind.like(f"%{w}%") for w in words]))


REAL_MIN = {"strong": 0.8, "good": 0.6}


def _real(stmt, real):
    """Only listings we're confident are real, running businesses (OSM records are community-checked)."""
    if not real or real == "any":
        return stmt
    conf = func.cast(func.json_extract(Prospect.raw_tags, '$."overture:confidence"'), Float)
    return stmt.where(or_(Prospect.source != "overture", (conf >= REAL_MIN[real]) & Prospect.address.is_not(None)))


def _filtered(q, segment, status, area, country, has_website, service, min_score, phone=None, need=None, state=None, quality=None, focus=None,
              real=None):
    stmt = _real(_focus(select(Prospect), focus), real)
    if quality == "established":
        stmt = stmt.where(Prospect.quality_level == "established")
    elif quality == "good":
        stmt = stmt.where(Prospect.quality_level.in_(("established", "good")))
    if state:
        stmt = stmt.where(Prospect.state.is_(None) if state == "unknown" else Prospect.state == state)
    if need == "definite":
        stmt = stmt.where(Prospect.need_level == "definite")
    elif need == "likely":
        stmt = stmt.where(Prospect.need_level.in_(("definite", "likely")))
    elif need in ("upgrade", "check_site"):
        stmt = stmt.where(Prospect.need_level == need)
    if phone == "verified":
        stmt = stmt.where(Prospect.phone_verified.is_(True))
    elif phone == "mobile":
        stmt = stmt.where(Prospect.phone_type == "mobile")
    elif phone == "usable":
        stmt = stmt.where(Prospect.phone_type.in_(("mobile", "landline", "international")))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Prospect.name.ilike(like), Prospect.type_label.ilike(like), Prospect.address.ilike(like)))
    for col, val in ((Prospect.segment, segment), (Prospect.area, area), (Prospect.country, country)):
        if val:
            stmt = stmt.where(col == val)
    if status == "open":
        stmt = stmt.where(Prospect.status.in_(OPEN_STATUSES))
    elif status:
        stmt = stmt.where(Prospect.status == status)
    if has_website is not None:
        stmt = stmt.where(Prospect.has_website.is_(has_website))
    if service:
        stmt = stmt.where(func.json_extract(Prospect.recommended_services, "$").like(f'%"{service}"%'))
    if min_score is not None:
        stmt = stmt.where(Prospect.score >= min_score)
    return stmt


@router.get("/prospects", response_model=Page[ProspectOut])
def list_prospects(
    q: str | None = None,
    segment: str | None = Query(None, pattern="^(small_business|professional|enterprise|college)$"),
    status: str | None = None,
    area: str | None = None,
    country: str | None = None,
    has_website: bool | None = None,
    service: str | None = None,
    min_score: float | None = None,
    phone: str | None = Query(None, pattern="^(verified|mobile|usable)$"),
    need: str | None = Query(None, pattern="^(definite|likely|upgrade|check_site)$"),
    state: str | None = None,
    quality: str | None = Query(None, pattern="^(established|good)$"),
    focus: str | None = Query(None, pattern=FOCUS_PATTERN),
    real: str | None = Query("good", pattern="^(strong|good|any)$"),
    sort: str = Query("score", pattern="^(score|newest|follow_up|name)$"),
    paging: Paging = Depends(),
    db: Session = DB,
):
    stmt = _filtered(q, segment, status, area, country, has_website, service, min_score, phone, need, state, quality, focus, real)
    if sort == "follow_up":
        stmt = stmt.where(Prospect.next_follow_up.is_not(None))
    stmt = stmt.order_by(SORTS[sort], Prospect.id.desc())
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/prospects/map-points")
def map_points(
    min_lat: float = Query(..., ge=-90, le=90), min_lon: float = Query(..., ge=-180, le=180),
    max_lat: float = Query(..., ge=-90, le=90), max_lon: float = Query(..., ge=-180, le=180),
    segment: str | None = Query(None, pattern="^(small_business|professional|enterprise|college)$"),
    status: str | None = None, need: str | None = Query(None, pattern="^(definite|likely|upgrade|check_site)$"),
    quality: str | None = Query(None, pattern="^(established|good)$"),
    has_website: bool | None = None, phone: str | None = Query(None, pattern="^(verified|mobile|usable)$"),
    service: str | None = None, q: str | None = None, state: str | None = None,
    focus: str | None = Query(None, pattern=FOCUS_PATTERN), real: str | None = Query("good", pattern="^(strong|good|any)$"),
    limit: int = Query(3000, ge=1, le=10000), db: Session = DB,
):
    """Compact points for the map view: the best `limit` prospects inside the visible area."""
    stmt = _filtered(q, segment, status, None, None, has_website, service, None, phone, need, state, quality, focus, real).where(
        Prospect.lat.between(min_lat, max_lat), Prospect.lon.between(min_lon, max_lon))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    # Spread the points over the visible area: split it into a grid and take the best few per cell, so a
    # zoomed-out map shows the whole country instead of one region full of equal top scores.
    cell = max(max_lat - min_lat, max_lon - min_lon) / 60 or 1e-6
    per_cell = max(1, limit // 900)
    cell_key = func.cast(Prospect.lat / cell, Integer) * 100000 + func.cast(Prospect.lon / cell, Integer)
    ranked = stmt.with_only_columns(
        Prospect.id, Prospect.lat, Prospect.lon, Prospect.score, Prospect.need_level, Prospect.name,
        func.row_number().over(partition_by=cell_key, order_by=(Prospect.score.desc(), Prospect.id)).label("rn"),
    ).order_by(None).subquery()
    rows = db.execute(select(ranked).where(ranked.c.rn <= per_cell).order_by(ranked.c.rn, ranked.c.score.desc()).limit(limit)).all()
    return {"total": total, "shown": len(rows), "points": [[r.id, round(r.lat, 5), round(r.lon, 5), r.score, r.need_level, r.name] for r in rows]}


@router.get("/prospects/next")
def next_to_call(
    group: str = Query("no_website", pattern="^(no_website|upgrade|colleges|all)$"),
    state: str | None = None, quality: str | None = Query("good", pattern="^(established|good|any)$"),
    need: str | None = Query(None, pattern="^(definite|likely)$"), phone: str | None = Query("usable", pattern="^(mobile|usable)$"),
    segment: str | None = Query(None, pattern="^(small_business|professional|enterprise|college)$"),
    exclude: str | None = Query(None, max_length=4000, description="comma-separated ids skipped this session"),
    focus: str | None = Query(None, pattern=FOCUS_PATTERN),
    real: str | None = Query("good", pattern="^(strong|good|any)$"),
    db: Session = DB,
):
    """The next prospect for the call list: due callbacks / retries first, then the best new one."""
    skip = [int(x) for x in (exclude or "").split(",") if x.strip().isdigit()][:500]
    q_level = None if quality == "any" else quality

    def base():
        stmt = _filtered(None, segment, None, None, None, None, None, None, phone, None, state, q_level, focus, real)
        if group == "no_website":
            stmt = stmt.where(Prospect.has_website.is_(False), Prospect.segment != "college")
            if need:
                stmt = _filtered_need(stmt, need)
        elif group == "upgrade":
            stmt = stmt.where(Prospect.has_website.is_(True), Prospect.need_level == "upgrade")
        elif group == "colleges":
            stmt = stmt.where(Prospect.segment == "college")
        if skip:
            stmt = stmt.where(Prospect.id.not_in(skip))
        return stmt

    now = utcnow()
    due = db.scalar(base().where(Prospect.status.in_(("callback", "no_answer", "contacted", "interested", "qualified", "proposal")),
                                 Prospect.next_follow_up <= now).order_by(Prospect.next_follow_up.asc()).limit(1))
    if due:
        return {"prospect": ProspectOut.model_validate(due), "reason": "follow-up due", "remaining_new": None}
    stmt = base().where(Prospect.status.in_(("new", "shortlisted")))
    nxt = db.scalar(stmt.order_by((Prospect.status == "shortlisted").desc(), Prospect.score.desc(), Prospect.id).limit(1))
    remaining = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    return {"prospect": ProspectOut.model_validate(nxt) if nxt else None, "reason": "new" if nxt else None, "remaining_new": remaining}


def _filtered_need(stmt, need):
    if need == "definite":
        return stmt.where(Prospect.need_level == "definite")
    return stmt.where(Prospect.need_level.in_(("definite", "likely")))


@router.get("/prospects/outreach-status")
def outreach_status(db: Session = DB):
    """Daily limit and sending hours, so outreach stays personal and never spammy."""
    from datetime import timedelta

    from app.settings_store import get_setting

    now_ist = utcnow() + timedelta(hours=5, minutes=30)
    hours = get_setting(db, "outreach_hours") or {"start": 10, "end": 19, "days": [0, 1, 2, 3, 4, 5]}
    in_hours = now_ist.weekday() in hours.get("days", []) and hours.get("start", 10) <= now_ist.hour < hours.get("end", 19)
    sent = _calls_today(db)
    whatsapp_sent = _whatsapp_today(db)
    cap = int(get_setting(db, "outreach_daily_cap") or 25)
    return {
        "sent_today": whatsapp_sent, "cap": cap, "cap_reached": whatsapp_sent >= cap, "logged_today": sent,
        "in_hours": in_hours, "hours": hours, "now_ist": now_ist.strftime("%a %H:%M"),
        "sender_name": get_setting(db, "sender_name") or "", "sender_link": get_setting(db, "sender_link") or "",
        "max_messages_without_reply": int(get_setting(db, "max_messages_without_reply") or 2),
    }


def _whatsapp_today(db: Session) -> int:
    from datetime import timedelta

    ist_midnight = (utcnow() + timedelta(hours=5, minutes=30)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=5, minutes=30)
    n = 0
    for p in db.scalars(select(Prospect).where(Prospect.last_contacted_at >= ist_midnight)).all():
        n += sum(1 for c in p.contact_log or [] if c.get("at", "") >= ist_midnight.isoformat() and c.get("channel") == "whatsapp"
                 and c.get("outcome") == "contacted")
    return n


@router.get("/prospects/summary")
def prospects_summary(db: Session = DB):
    def grouped(col):
        return {k or "unknown": v for k, v in db.execute(select(col, func.count()).group_by(col)).all()}

    now = utcnow()
    return {
        "total": db.scalar(select(func.count(Prospect.id))) or 0,
        "no_website": db.scalar(select(func.count(Prospect.id)).where(Prospect.has_website.is_(False))) or 0,
        "hot": db.scalar(select(func.count(Prospect.id)).where(Prospect.score >= 70, Prospect.status.in_(("new", "shortlisted")))) or 0,
        "follow_ups_due": db.scalar(select(func.count(Prospect.id)).where(Prospect.next_follow_up.is_not(None), Prospect.next_follow_up <= now)) or 0,
        "by_segment": grouped(Prospect.segment),
        "definite": db.scalar(select(func.count(Prospect.id)).where(Prospect.need_level == "definite", Prospect.status.in_(OPEN_STATUSES))) or 0,
        "by_need": {k or "unknown": v for k, v in db.execute(select(Prospect.need_level, func.count()).where(Prospect.status.in_(OPEN_STATUSES)).group_by(Prospect.need_level)).all()},
        "new_listings": db.scalar(select(func.count(Prospect.id)).where(Prospect.new_listing.is_(True), Prospect.status.in_(OPEN_STATUSES))) or 0,
        "focus": {k: v["label"] for k, v in __import__("app.prospects", fromlist=["NICHES"]).NICHES.items()},
        "by_quality": {k or "unknown": v for k, v in db.execute(select(Prospect.quality_level, func.count()).where(Prospect.status.in_(OPEN_STATUSES)).group_by(Prospect.quality_level)).all()},
        "calls_today": _calls_today(db),
        "by_status": grouped(Prospect.status),
        "by_area": grouped(Prospect.area),
        "by_state": {k or "unknown": v for k, v in db.execute(
            select(Prospect.state, func.count()).where(Prospect.status.in_(OPEN_STATUSES))
            .group_by(Prospect.state).order_by(func.count().desc())).all()},
        "services": SERVICE_KEYS,
    }


@router.get("/prospects/areas")
def prospect_areas(db: Session = DB):
    return {
        "groups": AREA_GROUPS,
        "areas": {k: {"country": v[2], "region": v[3]} for k, v in AREAS.items()},
        "selected": get_setting(db, "prospect_areas"),
        "radius_m": get_setting(db, "prospect_radius_m"),
        "max_per_area": get_setting(db, "prospect_max_per_area"),
        "custom_format": "Name@lat,lon",
    }


@router.get("/prospects/runs", response_model=list[ProspectRunOut])
def prospect_runs(limit: int = Query(10, ge=1, le=100), db: Session = DB):
    return db.scalars(select(ProspectRun).order_by(ProspectRun.id.desc()).limit(limit)).all()


@router.post("/prospects/find", response_model=ProspectRunOut, status_code=202, dependencies=NATIONWIDE)
def find_prospects(body: ProspectSearchIn, db: Session = DB, who: str = Depends(actor)):
    areas = body.areas or get_setting(db, "prospect_areas") or []
    if not areas:
        raise HTTPException(422, "Choose at least one area")
    for a in areas:
        try:
            resolve_area(a)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if db.scalar(select(ProspectRun).where(ProspectRun.status.in_(("running", "stopping")))):
        raise HTTPException(409, "A prospect search is already running")
    run = ProspectRun(areas=list(areas), status="running", log=[])
    db.add(run)
    log_activity(db, "prospect_run", None, "started", {"areas": areas}, who)
    db.commit()
    jobs.submit_prospect_search(
        run.id,
        radius_m=body.radius_m or int(get_setting(db, "prospect_radius_m") or 3000),
        max_per_area=body.max_per_area or int(get_setting(db, "prospect_max_per_area") or 80),
        rules=_rules(db),
    )
    db.refresh(run)
    return run


@router.post("/prospects/runs/{run_id}/stop", response_model=ProspectRunOut)
def stop_run(run_id: int, db: Session = DB, who: str = Depends(actor)):
    run = db.get(ProspectRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status == "running":
        run.status = "stopping"  # the worker stops before the next city
        log_activity(db, "prospect_run", run.id, "stop_requested", {}, who)
        db.commit()
    return run


def map_folders() -> dict[str, Path]:
    """Only these two folders are ever read. The API never accepts a free-form path."""
    return {"maps": Path(get_settings().upload_dir).parent / "maps", "downloads": Path.home() / "Downloads"}


MAP_DOWNLOAD = {
    "All India (1.7 GB)": "https://download.geofabrik.de/asia/india-latest.osm.pbf",
    "All India zones (pick one)": "https://download.geofabrik.de/asia/india.html",
    "Other countries": "https://download.geofabrik.de/",
}


def _still_downloading(f: Path) -> bool:
    """A file written to in the last 2 minutes is probably still downloading."""
    import time

    return time.time() - f.stat().st_mtime < 120


@router.get("/prospects/map-files")
def map_files():
    files = []
    for key, folder in map_folders().items():
        if folder.is_dir():
            for f in sorted(folder.glob("*.osm.pbf")):
                st = f.stat()
                files.append({"folder": key, "file": f.name, "path": str(f), "size_mb": round(st.st_size / 1e6, 1),
                              "modified": datetime.fromtimestamp(st.st_mtime, UTC).replace(tzinfo=None).isoformat(),
                              "downloading": _still_downloading(f)})
    return {"files": files, "folders": {k: str(v) for k, v in map_folders().items()}, "download_links": MAP_DOWNLOAD,
            "regions": list(REGIONS)}


@router.post("/prospects/scan-map-file", response_model=ProspectRunOut, status_code=202, dependencies=NATIONWIDE)
def scan_map_file(body: MapScanIn, db: Session = DB, who: str = Depends(actor)):
    folder = map_folders()[body.folder].resolve()
    path = (folder / body.file).resolve()
    if path.parent != folder or not path.is_file():
        raise HTTPException(404, "Map file not found in that folder")
    if _still_downloading(path):
        raise HTTPException(409, "This map file is still downloading. Wait until the download finishes, then scan.")
    for c in body.cities or []:
        try:
            resolve_area(c)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if db.scalar(select(ProspectRun).where(ProspectRun.status.in_(("running", "stopping")))):
        raise HTTPException(409, "A prospect search is already running")
    run = ProspectRun(areas=[f"map file: {body.file}"], status="running", log=[])
    db.add(run)
    log_activity(db, "prospect_run", None, "map_scan_started", body.model_dump(), who)
    db.commit()
    jobs.submit_map_scan(run.id, str(path), region=body.region, max_keep=body.max_keep, cities=body.cities, radius_km=body.radius_km,
                         rules=_rules(db))
    db.refresh(run)
    return run


def _calls_today(db: Session) -> dict[str, int]:
    """Contacts logged since local midnight (IST) — for the daily target on the call queue."""
    from datetime import timedelta

    ist_midnight = (utcnow() + timedelta(hours=5, minutes=30)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=5, minutes=30)
    rows = db.scalars(select(Prospect).where(Prospect.last_contacted_at >= ist_midnight)).all()
    out = {"total": 0}
    for p in rows:
        for c in p.contact_log or []:
            if c.get("at", "") >= ist_midnight.isoformat():
                out["total"] += 1
                out[c.get("outcome", "other")] = out.get(c.get("outcome", "other"), 0) + 1
    return out


@router.post("/prospects/check-websites", response_model=ProspectRunOut, status_code=202, dependencies=NATIONWIDE)
def check_websites(body: CheckWebsitesIn, db: Session = DB, who: str = Depends(actor)):
    """Check the homepages of businesses that have a website, best first, to find who needs an upgrade."""
    _busy(db)
    run = ProspectRun(areas=[f"Website check: {body.limit}"], status="running", log=[])
    db.add(run)
    log_activity(db, "prospect_run", None, "check_websites", body.model_dump(), who)
    db.commit()
    jobs.submit_website_checks(run.id, limit=body.limit, state=body.state, segment=body.segment)
    db.refresh(run)
    return run


def _busy(db: Session) -> None:
    if db.scalar(select(ProspectRun).where(ProspectRun.status.in_(("running", "stopping")))):
        raise HTTPException(409, "A prospect search is already running")


@router.get("/prospects/overture")
def overture_status():
    folder = map_folders()["maps"]
    files = []
    if folder.is_dir():
        for f in sorted(folder.glob("overture-*.parquet")):
            st = f.stat()
            files.append({"file": f.name, "size_mb": round(st.st_size / 1e6, 1),
                          "modified": datetime.fromtimestamp(st.st_mtime, UTC).replace(tzinfo=None).isoformat()})
    downloading = folder.is_dir() and any(folder.glob("overture-*.part"))
    return {"files": files, "downloading": downloading, "folder": str(folder),
            "about": "Overture Maps places: open data (CDLA-Permissive-2.0) from Meta, Microsoft, Foursquare and others."}


@router.post("/prospects/overture/download", response_model=ProspectRunOut, status_code=202)
def overture_download(db: Session = DB, who: str = Depends(actor)):
    _busy(db)
    folder = map_folders()["maps"]
    folder.mkdir(parents=True, exist_ok=True)
    run = ProspectRun(areas=["Overture: download India"], status="running", log=[])
    db.add(run)
    log_activity(db, "prospect_run", None, "overture_download", {}, who)
    db.commit()
    jobs.submit_overture(run.id, "download", folder=str(folder))
    db.refresh(run)
    return run


def _prev_ids(current: Path) -> str | None:
    """The newest 'overture-ids-<release>.parquet' older than the scanned release (for 'newly listed')."""
    rel = current.name.removeprefix("overture-india-").removesuffix(".parquet")
    older = sorted(f for f in current.parent.glob("overture-ids-*.parquet") if f.name.removeprefix("overture-ids-").removesuffix(".parquet") < rel)
    return str(older[-1]) if older else None


@router.post("/prospects/scan-overture", response_model=ProspectRunOut, status_code=202, dependencies=NATIONWIDE)
def scan_overture(body: OvertureScanIn, db: Session = DB, who: str = Depends(actor)):
    folder = map_folders()["maps"].resolve()
    path = (folder / body.file).resolve()
    if path.parent != folder or not path.is_file():
        raise HTTPException(404, "Overture file not found. Download it first.")
    for c in body.cities or []:
        try:
            resolve_area(c)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    _busy(db)
    run = ProspectRun(areas=[f"Overture ({body.mode.replace('_', ' ')}): {body.file}"], status="running", log=[])
    db.add(run)
    log_activity(db, "prospect_run", None, "overture_scan", body.model_dump(), who)
    db.commit()
    jobs.submit_overture(run.id, "scan", path=str(path), max_keep=body.max_keep, min_confidence=body.min_confidence,
                         cities=body.cities, radius_km=body.radius_km, rules=_rules(db), mode=body.mode, prev_ids=_prev_ids(path))
    db.refresh(run)
    return run


@router.get("/prospects/export.csv")
def export_csv(
    segment: str | None = None, status: str | None = None, area: str | None = None, has_website: bool | None = None,
    service: str | None = None, min_score: float | None = None, phone: str | None = None, need: str | None = None,
    state: str | None = None, quality: str | None = None, focus: str | None = Query(None, pattern=FOCUS_PATTERN), real: str | None = Query("good", pattern="^(strong|good|any)$"),
    db: Session = DB,
):
    rows = db.scalars(_filtered(None, segment, status, area, None, has_website, service, min_score, phone, need, state, quality, focus, real).order_by(Prospect.score.desc()).limit(5000)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "type", "segment", "need", "quality", "area", "state", "country", "score", "status", "phone", "phone_checked", "phone_type", "phone_confirmed", "email", "website", "address", "gaps", "services", "source"])
    for p in rows:
        w.writerow([p.name, p.type_label, p.segment, p.need_level, p.quality_level, p.area, p.state, p.country, p.score, p.status, p.phone, p.phone_normalized, p.phone_type, "yes" if p.phone_verified else "no", p.email, p.website, p.address,
                    "; ".join(g["label"] for g in p.gaps or []), "; ".join(SERVICE_KEYS.get(s, s) for s in p.recommended_services or []), p.source_url])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=prospects.csv"})


@router.get("/prospects/{pid}", response_model=ProspectOut)
def get_prospect(pid: int, db: Session = DB):
    return _get(db, pid)


@router.patch("/prospects/{pid}", response_model=ProspectOut)
def update_prospect(pid: int, body: ProspectUpdate, db: Session = DB, who: str = Depends(actor)):
    p = _get(db, pid)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    log_activity(db, "prospect", p.id, "updated", {k: str(v) for k, v in data.items()}, who)
    db.commit()
    return p


@router.post("/prospects/{pid}/audit", response_model=ProspectOut)
def audit_prospect(pid: int, db: Session = DB, who: str = Depends(actor)):
    p = _get(db, pid)
    try:
        audit_website(db, p)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    log_activity(db, "prospect", p.id, "website_checked", {"gaps": len((p.audit or {}).get("gaps") or [])}, who)
    db.commit()
    return p


@router.get("/prospects/{pid}/pitch")
def prospect_pitch(pid: int, db: Session = DB):
    from app.settings_store import get_setting

    return pitch(_get(db, pid), sender_name=get_setting(db, "sender_name") or "", sender_link=get_setting(db, "sender_link") or "")


@router.post("/prospects/{pid}/phone-verified", response_model=ProspectOut)
def mark_phone_verified(pid: int, verified: bool = True, db: Session = DB, who: str = Depends(actor)):
    """Owner confirms (after a call or WhatsApp reply) that the listed number reaches this business."""
    p = _get(db, pid)
    if verified and not p.phone_normalized:
        raise HTTPException(422, "No usable phone number to confirm")
    p.phone_verified, p.phone_verified_at = verified, (utcnow() if verified else None)
    evaluate(p)
    log_activity(db, "prospect", p.id, "phone_verified" if verified else "phone_unverified", {"phone": p.phone_normalized}, who)
    db.commit()
    return p


@router.post("/prospects/{pid}/social-activity", response_model=ProspectOut)
def set_social_activity(pid: int, activity: str | None = Query(None, pattern="^(very_active|some|inactive)$"), db: Session = DB,
                        who: str = Depends(actor)):
    """Owner looked at their Facebook / Instagram and says how active it is (IOI does not scrape social sites)."""
    p = _get(db, pid)
    audit = dict(p.audit or {})
    if activity:
        audit["social_activity"] = activity
    else:
        audit.pop("social_activity", None)
    p.audit = audit
    evaluate(p)
    log_activity(db, "prospect", p.id, "social_activity", {"activity": activity}, who)
    db.commit()
    return p


@router.post("/prospects/{pid}/contact", response_model=ProspectOut)
def log_contact(pid: int, body: ProspectContactIn, db: Session = DB, who: str = Depends(actor)):
    p = _get(db, pid)
    from app.settings_store import get_setting

    record_contact(p, body.channel, body.outcome, body.note, who, callback_at=body.callback_at, qualification=body.qualification,
                   max_unanswered=int(get_setting(db, "max_messages_without_reply") or 2))
    log_activity(db, "prospect", p.id, "contact_logged", body.model_dump(), who)
    db.commit()
    return p
