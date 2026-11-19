"""Outbound HTTP with SSRF protection, timeouts, response-size limits, robots.txt and rate limiting.

All network access to third-party sources goes through `SafeHttp`. Tests inject an
`httpx.MockTransport` so no test touches the live internet.
"""

import ipaddress
import socket
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import get_settings


class FetchError(Exception):
    pass


class BlockedURLError(FetchError):
    pass


class RobotsDisallowedError(FetchError):
    pass


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped and not _ip_is_public(ip.ipv4_mapped))
    )


def default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return list({info[4][0] for info in infos})


def validate_url(url: str, *, resolver=default_resolver, allow_private: bool | None = None) -> str:
    """Raise BlockedURLError unless `url` is an http(s) URL resolving only to public addresses."""
    if allow_private is None:
        allow_private = get_settings().allow_private_network
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise BlockedURLError(f"Malformed URL: {exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise BlockedURLError("Only http and https URLs are allowed")
    if not parts.hostname:
        raise BlockedURLError("URL has no host")
    if parts.username or parts.password:
        raise BlockedURLError("Credentials in URLs are not allowed")
    if parts.port not in (None, 80, 443, 8080, 8443):
        raise BlockedURLError(f"Port {parts.port} not allowed")
    host = parts.hostname
    if allow_private:
        return url
    if host.lower() in ("localhost",) or host.lower().endswith((".localhost", ".local", ".internal")):
        raise BlockedURLError("Local hostnames are not allowed")
    try:
        literal = ipaddress.ip_address(host)
        addrs = [str(literal)]
    except ValueError:
        try:
            addrs = resolver(host)
        except OSError as exc:
            raise BlockedURLError(f"Could not resolve host {host}") from exc
    if not addrs:
        raise BlockedURLError(f"Host {host} did not resolve")
    for a in addrs:
        if not _ip_is_public(ipaddress.ip_address(a)):
            raise BlockedURLError(f"Host {host} resolves to non-public address {a}")
    return url


@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        import json

        return json.loads(self.content)


class _RateLimiter:
    """Simple per-host minimum-interval limiter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def wait(self, host: str, per_minute: int) -> None:
        if per_minute <= 0:
            return
        interval = 60.0 / per_minute
        with self._lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            delay = max(0.0, last + interval - now)
            self._last[host] = now + delay
        if delay:
            time.sleep(delay)


_rate_limiter = _RateLimiter()


def client_factory() -> httpx.Client:
    """Builds the outbound client. Tests replace this to inject an httpx.MockTransport."""
    s = get_settings()
    return httpx.Client(
        timeout=httpx.Timeout(s.http_timeout_seconds),
        headers={"User-Agent": s.http_user_agent},
        follow_redirects=False,
    )


class SafeHttp:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        resolver=None,
        rate_limit_per_minute: int = 30,
        respect_robots: bool = True,
        max_bytes: int | None = None,
        allow_private: bool | None = None,
    ) -> None:
        s = get_settings()
        self.client = client or client_factory()
        self.resolver = resolver or (lambda host: globals()["default_resolver"](host))
        self.rate_limit = rate_limit_per_minute
        self.respect_robots = respect_robots
        self.max_bytes = max_bytes or s.http_max_bytes
        self.allow_private = allow_private
        self.user_agent = s.http_user_agent
        self.requests_made = 0
        self._robots: dict[str, RobotFileParser | None] = {}

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp: RobotFileParser | None = RobotFileParser()
            try:
                res = self._get_raw(urljoin(origin, "/robots.txt"), check_robots=False, max_redirects=2)
                if res.status_code in (401, 403):
                    rp.disallow_all = True  # type: ignore[union-attr]
                elif res.status_code >= 400:
                    rp.allow_all = True  # type: ignore[union-attr]
                else:
                    rp.parse(res.text.splitlines())  # type: ignore[union-attr]
            except FetchError:
                rp = None  # robots unreachable → treat as allowed (standard behaviour)
            self._robots[origin] = rp
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def _get_raw(self, url: str, *, check_robots: bool, max_redirects: int = 3, headers=None, params=None) -> FetchResult:
        current = url
        for _ in range(max_redirects + 1):
            validate_url(current, resolver=self.resolver, allow_private=self.allow_private)
            if check_robots and self.respect_robots and not self._robots_allows(current):
                raise RobotsDisallowedError(f"robots.txt disallows {current}")
            _rate_limiter.wait(urlsplit(current).hostname or "", self.rate_limit)
            self.requests_made += 1
            try:
                with self.client.stream("GET", current, headers=headers, params=params) as resp:
                    if resp.is_redirect:
                        loc = resp.headers.get("location")
                        if not loc:
                            raise FetchError("Redirect without location")
                        current = urljoin(current, loc)
                        params = None
                        continue
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > self.max_bytes:
                        raise FetchError(f"Response too large ({declared} bytes)")
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > self.max_bytes:
                            raise FetchError(f"Response exceeded {self.max_bytes} bytes")
                    return FetchResult(
                        url=current,
                        status_code=resp.status_code,
                        content_type=resp.headers.get("content-type", ""),
                        content=bytes(buf),
                    )
            except httpx.TimeoutException as exc:
                raise FetchError(f"Timeout fetching {current}") from exc
            except httpx.HTTPError as exc:
                raise FetchError(f"HTTP error fetching {current}: {exc}") from exc
        raise FetchError("Too many redirects")

    def get(self, url: str, *, check_robots: bool | None = None, headers=None, params=None) -> FetchResult:
        """GET a URL. Raises FetchError on network/safety failure or HTTP status >= 400."""
        res = self._get_raw(
            url,
            check_robots=self.respect_robots if check_robots is None else check_robots,
            headers=headers,
            params=params,
        )
        if res.status_code >= 400:
            raise FetchError(f"HTTP {res.status_code} from {res.url}")
        return res

    def close(self) -> None:
        self.client.close()
