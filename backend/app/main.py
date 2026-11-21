"""FastAPI application entrypoint.

Run: `uv run python -m app.main` (binds to 127.0.0.1 by default).
"""

import ipaddress
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import jobs
from app.api import big_projects, core, opportunities, outreach, prospects, sources
from app.api.deps import require_auth
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.actions import seed_default_actions
    from app.db import SessionLocal
    from app.source_registry import seed_sources

    with SessionLocal() as db:
        seed_sources(db)
        seed_default_actions(db)
        _recover_prospect_runs(db)
    jobs.start()
    try:
        yield
    finally:
        jobs.shutdown()


def _recover_prospect_runs(db) -> None:
    """A prospect search still 'running' at startup died with the previous process."""
    from sqlalchemy import update

    from app.db import utcnow
    from app.models import ProspectRun

    db.execute(update(ProspectRun).where(ProspectRun.status.in_(("running", "stopping"))).values(status="failed", finished_at=utcnow()))
    # Prospects saved before phone checking existed: check their numbers once.
    from sqlalchemy import select

    from app.models import Prospect
    from app.prospects import evaluate

    from app.prospects import exclusion_reason

    for p in db.scalars(select(Prospect)):  # cheap; rules may have changed since last start
        evaluate(p)
        # Apply the chain / college / IT / government rules to prospects found before those rules existed.
        why = exclusion_reason(p.raw_tags or {}, p.name, p.business_type)
        if not why and p.status == "rejected" and (p.notes or "").startswith("Auto-skipped:"):
            p.status = "new"  # a rule that skipped it has since been relaxed (e.g. dealers are allowed)
            p.notes = (p.notes or "").split("\n", 1)[1] if "\n" in (p.notes or "") else None
        if why and p.status in ("new", "shortlisted"):
            p.status = "rejected"
            p.notes = f"Auto-skipped: {why}." + (f"\n{p.notes}" if p.notes else "")
    db.commit()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Inferago Opportunity Intelligence (IOI)",
        version="0.1.0",
        description="Internal opportunity discovery, qualification and outreach-preparation API. Never sends outreach automatically.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-IOI-Actor"],
    )
    app.include_router(core.public, prefix="/api")
    protected = [Depends(require_auth)]
    for r in (core.router, sources.router, opportunities.router, outreach.router, prospects.router, big_projects.router):
        app.include_router(r, prefix="/api", dependencies=protected)
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built React app (frontend/dist) from the same origin, if it has been built.

    This makes a single process enough for hosting: `npm run build` once, then run the backend.
    The UI is static; all data still goes through the authenticated /api routes.
    """
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    index = dist / "index.html"
    if not index.is_file():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(404, "Not found")
        return FileResponse(index)


app = create_app()


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def migrate() -> None:
    """Apply Alembic migrations up to head."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(cfg, "head")


def main() -> None:
    import uvicorn

    s = get_settings()
    if not _is_loopback_host(s.host) and not s.api_token:
        raise SystemExit(
            f"Refusing to bind to {s.host} without IOI_API_TOKEN. Set a strong token or bind to 127.0.0.1."
        )
    migrate()
    uvicorn.run("app.main:app", host=s.host, port=s.port, log_level="info")


if __name__ == "__main__":
    main()
