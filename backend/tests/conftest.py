"""Test fixtures. No test touches the live internet: all HTTP goes through an httpx.MockTransport."""

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="ioi-test-")
os.environ["IOI_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["IOI_UPLOAD_DIR"] = f"{_TMP}/uploads"
os.environ["IOI_API_TOKEN"] = ""
os.environ["IOI_SCHEDULER_ENABLED"] = "false"
# Legacy tests exercise nationwide discovery; Chennai-only scope tests switch it on explicitly (chennai_scope fixture).
os.environ["IOI_DISCOVERY_SCOPE"] = "all"
os.environ["IOI_IOI3_WORKER"] = "false"  # tests run discovery jobs synchronously via engine.run_next
os.environ["IOI_OPENROUTER_API_KEY"] = ""
os.environ["IOI_REDDIT_CLIENT_ID"] = ""

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import http_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.source_registry import seed_sources  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema():
    get_settings.cache_clear()
    command.upgrade(alembic_config(os.environ["IOI_DATABASE_URL"]), "head")
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.execute(text("PRAGMA foreign_keys=ON"))
    with SessionLocal() as db:
        seed_sources(db)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


class MockWeb:
    """Route table for httpx.MockTransport: exact URL (without query) → response factory."""

    def __init__(self) -> None:
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.calls: list[str] = []

    def json(self, url: str, payload, status: int = 200) -> None:
        self.routes[url] = lambda req: httpx.Response(status, json=payload)

    def text(self, url: str, body: str, status: int = 200, content_type: str = "text/html") -> None:
        self.routes[url] = lambda req: httpx.Response(status, text=body, headers={"content-type": content_type})

    def error(self, url: str, status: int) -> None:
        self.routes[url] = lambda req: httpx.Response(status, text="error")

    def raise_timeout(self, url: str) -> None:
        def _r(req):
            raise httpx.ConnectTimeout("timed out", request=req)

        self.routes[url] = _r

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        self.calls.append(str(request.url))
        if url in self.routes:
            return self.routes[url](request)
        if url.endswith("/robots.txt"):
            return httpx.Response(404, text="")
        return httpx.Response(404, text="not found")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def web(monkeypatch) -> MockWeb:
    w = MockWeb()
    monkeypatch.setattr(http_client, "client_factory", w.client)
    monkeypatch.setattr(http_client, "default_resolver", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(http_client._rate_limiter, "wait", lambda host, per_minute: None)
    return w


@pytest.fixture
def chennai_scope(monkeypatch):
    """Production default: Chennai-only discovery."""
    monkeypatch.setenv("IOI_DISCOVERY_SCOPE", "chennai")
    get_settings.cache_clear()
    yield
    monkeypatch.setenv("IOI_DISCOVERY_SCOPE", "all")
    get_settings.cache_clear()


@pytest.fixture
def client(web):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


# --- Hacker News mock data -------------------------------------------------------------------

HN_FIREBASE = "https://hacker-news.firebaseio.com/v0"
HN_ALGOLIA = "https://hn.algolia.com/api/v1"
NOW_TS = 1_790_000_000  # fixed epoch used by fixtures

FREELANCER_POSTS = [
    {"id": 9001, "author": "acmebuyer", "created_at_i": NOW_TS, "text":
        "SEEKING FREELANCER | Acme Logistics | Remote (worldwide)<p>We need a backend developer to build a REST API "
        "integration between our warehouse system and Shopify, and automate our order workflow. Budget $8,000. "
        "Timeline 6 weeks. Contact ops@acmelogistics.example or see https://acmelogistics.example</p>"},
    {"id": 9002, "author": "dev1", "created_at_i": NOW_TS, "text": "SEEKING WORK | Python developer | Remote<p>I build APIs.</p>"},
    {"id": 9003, "author": "usbuyer", "created_at_i": NOW_TS, "text":
        "SEEKING FREELANCER | Stateside Co | Remote (US only)<p>Looking for a contract developer for Django internal tools. "
        "Must be based in the US.</p>"},
]
HIRING_POSTS = [
    {"id": 9101, "author": "tnfirm", "created_at_i": NOW_TS, "text":
        "Kaveri Textiles | Integration Engineer | Coimbatore, Tamil Nadu | Contract<p>We are digitising our mill: ERP integration "
        "with Tally and a workflow automation for purchase approvals. 3-month contract. https://kaveritextiles.example</p>"},
    {"id": 9102, "author": "bigco", "created_at_i": NOW_TS, "text": "BigCo | Staff Engineer | NYC | Full-time<p>Join us.</p>"},
]


def install_hn(web: MockWeb, *, freelancer=None, hiring=None, search_hits=None) -> None:
    freelancer = FREELANCER_POSTS if freelancer is None else freelancer
    hiring = HIRING_POSTS if hiring is None else hiring
    web.json(f"{HN_FIREBASE}/user/whoishiring.json", {"id": "whoishiring", "submitted": [800, 801]})
    web.json(f"{HN_FIREBASE}/item/800.json", {"id": 800, "type": "story", "title": "Ask HN: Who is hiring? (December 2026)"})
    web.json(f"{HN_FIREBASE}/item/801.json", {"id": 801, "type": "story", "title": "Ask HN: Freelancer? Seeking freelancer? (December 2026)"})
    web.json(f"{HN_ALGOLIA}/items/800", {"id": 800, "title": "Ask HN: Who is hiring? (December 2026)", "children": hiring})
    web.json(f"{HN_ALGOLIA}/items/801", {"id": 801, "title": "Ask HN: Freelancer? Seeking freelancer? (December 2026)", "children": freelancer})
    web.json(f"{HN_ALGOLIA}/search_by_date", {"hits": search_hits or []})
