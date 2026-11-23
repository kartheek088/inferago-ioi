"""Reproducible research benchmark (no internet).

Serves N synthetic company websites on 127.0.0.2..N+1:8080 with a fixed per-response delay, then
researches them with whatever IOI code is importable, on a throwaway database. Runs two passes:
cold (first visit) and warm (re-research), and prints JSON metrics.

    cd backend && uv run python scripts/bench_research.py [--sites 12] [--delay 0.25]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--sites", type=int, default=12)
ap.add_argument("--delay", type=float, default=0.25)
args = ap.parse_args()

tmp = tempfile.mkdtemp(prefix="ioi-bench-")
os.environ.update({"IOI_DATABASE_URL": f"sqlite:///{tmp}/bench.db", "IOI_ALLOW_PRIVATE_NETWORK": "true", "IOI_API_TOKEN": "",
                   "IOI_SCHEDULER_ENABLED": "false", "IOI_OPENROUTER_API_KEY": "", "IOI_ANTHROPIC_API_KEY": "", "IOI_IOI3_WORKER": "false"})
sys.path.insert(0, os.getcwd())

PAGES = {
    "/": "<h1>{name}</h1><a href='/contact-us'>Contact</a> <a href='/services'>Services</a> <a href='/about'>About</a> <p>Installation and commissioning of equipment. © 2026</p>",
    "/contact-us": "<p>{name}, 12 Usman Road, T Nagar, Chennai 600017. Email: <a href='mailto:info@site{i}.example'>info@site{i}.example</a> Phone: 044 2434 00{i:02d}</p>",
    "/services": "<p>Annual maintenance contracts (AMC) and breakdown service by our service engineers. Raise a complaint with our service request form.</p>",
    "/about": "<p>Founded in 1998. Our Managing Director, R. Kumar, leads a team of 20 technicians.</p>",
}
REQUESTS = {"n": 0}


class H(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        REQUESTS["n"] += 1
        time.sleep(args.delay)
        i = int(self.server.server_address[0].rsplit(".", 1)[1]) - 1
        body = PAGES.get(self.path.split("?")[0])
        if body is None:
            self.send_response(404); self.end_headers(); return
        data = f"<html><body>{body.format(name=f'Bench Equipment Services {i}', i=i)}</body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Last-Modified", "Mon, 02 Nov 2026 10:00:00 GMT")
        self.send_header("ETag", f'"site{i}{self.path}"')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


servers = []
for i in range(1, args.sites + 1):
    s = ThreadingHTTPServer((f"127.0.0.{i + 1}", 8080), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    servers.append(s)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

cfg = Config("alembic.ini")
cfg.set_main_option("script_location", "alembic")
command.upgrade(cfg, "head")

from sqlalchemy import select  # noqa: E402

from app import http_client  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.ioi3 import collect, core, qualify, research  # noqa: E402
from app.ioi3.models import Company  # noqa: E402

http_client._rate_limiter.wait = lambda host, per_minute: None if per_minute > 1000 else http_client._RateLimiter.wait(http_client._rate_limiter, host, per_minute)

with SessionLocal() as db:
    core.seed_sources(db)
    camp = core.active_campaign(db)
    for i in range(1, args.sites + 1):
        collect.add_manual(db, camp, {"name": f"Bench Equipment Services {i}", "industry": "equipment_sales_service",
                                      "address": "Usman Road, T Nagar, Chennai 600017", "website": f"http://127.0.0.{i + 1}:8080/",
                                      "source_url": "https://example.org/bench"})
    ids = [c.id for c in db.scalars(select(Company).order_by(Company.id))]


def run_pass(label: str) -> dict:
    REQUESTS["n"] = 0
    first_ready = None
    t0 = time.monotonic()
    with SessionLocal() as db:
        rows = [db.get(Company, i) for i in ids]
        if hasattr(research, "research_many"):
            def on_done(c):
                nonlocal first_ready
                if first_ready is None and qualify.sales_ready(c.gates or []):
                    first_ready = time.monotonic() - t0
            stats = research.research_many(db, rows, on_done=on_done)
        else:
            http = http_client.SafeHttp(rate_limit_per_minute=20)
            for c in rows:
                research.research_company(db, c, http)
                db.commit()
                if first_ready is None and qualify.sales_ready(c.gates or []):
                    first_ready = time.monotonic() - t0
            http.close()
            stats = {}
        ok = sum(1 for c in rows if not c.research_error)
        ready = sum(1 for c in rows if qualify.sales_ready(c.gates or []))
    return {"pass": label, "elapsed_s": round(time.monotonic() - t0, 2), "time_to_first_ready_s": round(first_ready, 2) if first_ready else None,
            "server_requests": REQUESTS["n"], "companies_ok": ok, "sales_ready": ready, **{k: v for k, v in stats.items() if k != "companies"}}


print(json.dumps({"sites": args.sites, "delay_s": args.delay, "results": [run_pass("cold"), run_pass("warm")]}, indent=2))
for s in servers:
    s.shutdown()
