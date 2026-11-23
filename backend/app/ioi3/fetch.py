"""Fetching with a page cache, error classification, and SQLite-lock-safe short writes.

- Every request still goes through `SafeHttp` (SSRF guard, robots.txt, size/time limits, per-host rate limit).
- Cache: a page fetched within `FRESH_DAYS` is reused without a request; an older one is re-validated with
  If-None-Match / If-Modified-Since when the site sent ETag / Last-Modified (a 304 reuses the stored body).
- Errors are classified as retryable (timeouts, 5xx, connection problems) or permanent (domain not found,
  access forbidden, not a web page) so the engine can back off sensibly.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.db import SessionLocal, utcnow
from app.http_client import FetchError, FetchResult, SafeHttp
from app.ioi3.models import PageCache

log = logging.getLogger("ioi3.fetch")
T = TypeVar("T")

FRESH_DAYS = 7
MAX_CACHED_BYTES = 600_000
RETRY_AFTER = {"retryable": timedelta(days=1), "permanent": timedelta(days=30), "outage": timedelta(minutes=15)}


def classify_error(msg: str) -> tuple[str, str]:
    """(kind, plain-language message) for a fetch failure."""
    m = msg.lower()
    if is_network_outage(msg):
        return "retryable", "This computer couldn't look up website addresses (temporary DNS/network problem). IOI will try again soon."
    if "could not resolve host" in m or "did not resolve" in m:
        return "permanent", "The website's domain doesn't exist any more (DNS lookup failed)."
    if "http 403" in m or "http 401" in m:
        return "permanent", "The website blocks automated visitors (access forbidden)."
    if "http 404" in m or "http 410" in m:
        return "permanent", "The website address returns 'not found'."
    if "robots.txt disallows" in m:
        return "permanent", "The website's robots.txt asks automated visitors not to read this page."
    if "not a web page" in m or "port" in m and "not allowed" in m or "non-public address" in m or "only http" in m:
        return "permanent", f"Not a readable public website ({msg[:120]})."
    if "timeout" in m or "took longer" in m:
        return "retryable", "The website was too slow to respond. IOI will try again later."
    if "http 5" in m or "http error" in m or "connection" in m:
        return "retryable", f"The website had a temporary problem ({msg[:100]}). IOI will try again later."
    return "retryable", msg[:200]


def is_network_outage(msg: str) -> bool:
    """A failure of *this computer's* name resolution / network, not of the website (EAI_AGAIN, unreachable network)."""
    m = msg.lower()
    return ("temporary failure in name resolution" in m or "errno -3" in m or "network is unreachable" in m
            or "no address associated" in m and "errno -5" in m)


def is_locked(exc: BaseException) -> bool:
    return isinstance(exc, OperationalError) and "database is locked" in str(exc).lower()


def with_retry(fn: Callable[[], T], attempts: int = 6, base_delay: float = 0.15) -> T:
    """Run a short DB operation; on a SQLite lock/snapshot conflict roll back and retry with backoff.

    In WAL mode a transaction that read before another connection committed fails its first write
    immediately with "database is locked" (busy_timeout doesn't apply). Retrying in a fresh transaction is
    the correct fix.
    """
    for i in range(attempts):
        try:
            return fn()
        except OperationalError as exc:
            if not is_locked(exc) or i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i))
    raise RuntimeError("unreachable")


def short_write(fn: Callable, attempts: int = 6) -> None:
    """Apply `fn(session)` in its own short transaction, retrying on lock conflicts."""
    def go():
        with SessionLocal() as s:
            fn(s)
            s.commit()
    with_retry(go, attempts)


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.network = 0
        self.cache_hits = 0
        self.revalidated = 0
        self.failures = 0

    def add(self, **kw: int) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, getattr(self, k) + v)

    def as_dict(self) -> dict[str, int]:
        return {"pages_fetched": self.network, "cache_hits": self.cache_hits, "revalidated_304": self.revalidated,
                "fetch_failures": self.failures}


class CachedHttp:
    """`get(url)` like SafeHttp, backed by ioi_page_cache. Thread-safe (one instance per worker thread is fine)."""

    def __init__(self, http: SafeHttp, stats: Stats | None = None, *, use_cache: bool = True, fresh_days: int = FRESH_DAYS) -> None:
        self.http = http
        self.stats = stats or Stats()
        self.use_cache = use_cache
        self.fresh = timedelta(days=fresh_days)

    def _load(self, url: str) -> PageCache | None:
        with SessionLocal() as s:
            row = s.scalar(select(PageCache).where(PageCache.url == url))
            if row is not None:
                s.expunge(row)
            return row

    def _store(self, url: str, res: FetchResult, etag: str | None, last_mod: str | None) -> None:
        body = res.content[:MAX_CACHED_BYTES].decode("utf-8", errors="replace")

        def put(s):
            row = s.scalar(select(PageCache).where(PageCache.url == url))
            now = utcnow()
            if row is None:
                s.add(PageCache(url=url, final_url=res.url, status_code=res.status_code, content_type=res.content_type, etag=etag,
                                last_modified=last_mod, body=body, fetched_at=now, validated_at=now))
            else:
                row.final_url, row.status_code, row.content_type, row.body = res.url, res.status_code, res.content_type, body
                row.etag, row.last_modified, row.fetched_at, row.validated_at = etag, last_mod, now, now
        try:
            short_write(put)
        except Exception:  # noqa: BLE001 — caching is an optimisation; never fail research because of it
            log.warning("page cache write failed for %s", url, exc_info=True)

    def get(self, url: str) -> FetchResult:
        cached = self._load(url) if self.use_cache else None
        now = utcnow()
        if cached is not None and now - cached.validated_at < self.fresh:
            self.stats.add(cache_hits=1)
            return FetchResult(url=cached.final_url, status_code=cached.status_code, content_type=cached.content_type or "",
                               content=cached.body.encode())
        headers = {}
        if cached is not None:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified
        try:
            res = self.http._get_raw(url, check_robots=self.http.respect_robots, headers=headers or None)
        except FetchError:
            self.stats.add(network=1, failures=1)
            raise
        self.stats.add(network=1)
        if res.status_code == 304 and cached is not None:
            self.stats.add(revalidated=1)

            def touch(s):
                row = s.scalar(select(PageCache).where(PageCache.url == url))
                if row is not None:
                    row.validated_at = utcnow()
            try:
                short_write(touch)
            except Exception:  # noqa: BLE001
                pass
            return FetchResult(url=cached.final_url, status_code=200, content_type=cached.content_type or "", content=cached.body.encode())
        if res.status_code >= 400:
            self.stats.add(failures=1)
            raise FetchError(f"HTTP {res.status_code} from {res.url}")
        if self.use_cache and "html" in (res.content_type or "html").lower():
            self._store(url, res, res.headers.get("etag"), res.headers.get("last-modified"))
        return res
