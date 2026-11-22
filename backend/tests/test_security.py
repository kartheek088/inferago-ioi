"""SSRF protection, response limits, robots.txt, API access control."""

import httpx
import pytest

from app.config import get_settings
from app.http_client import BlockedURLError, FetchError, RobotsDisallowedError, SafeHttp, validate_url


def public(host):
    return ["93.184.216.34"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000/api",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://user:pass@example.com/",
        "http://example.com:22/",
        "http://printer.local/",
    ],
)
def test_validate_url_blocks_unsafe(url):
    with pytest.raises(BlockedURLError):
        validate_url(url, resolver=public, allow_private=False)


def test_validate_url_nat64_judges_embedded_ipv4():
    # DNS64 maps public IPv4 hosts into 64:ff9b::/96 — allowed; a private IPv4 behind it stays blocked.
    assert validate_url("https://hn.example/", resolver=lambda h: ["64:ff9b::22a0:a8b5"], allow_private=False)
    for bad in ("64:ff9b::a01:203", "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe"):  # 10.1.2.3, 127.0.0.1, 169.254.169.254
        with pytest.raises(BlockedURLError):
            validate_url("https://evil.example/", resolver=lambda h, b=bad: [b], allow_private=False)


def test_validate_url_blocks_dns_to_private():
    with pytest.raises(BlockedURLError, match="non-public"):
        validate_url("https://evil.example/", resolver=lambda h: ["10.1.2.3"], allow_private=False)


def test_validate_url_allows_public():
    assert validate_url("https://example.com/path", resolver=public, allow_private=False)


def _http(handler, **kw):
    return SafeHttp(httpx.Client(transport=httpx.MockTransport(handler)), resolver=kw.pop("resolver", public), rate_limit_per_minute=0, **kw)


def test_redirect_to_private_is_blocked():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://internal.example/secret"})

    def resolver(host):
        return ["10.0.0.1"] if host == "internal.example" else ["93.184.216.34"]

    with pytest.raises(BlockedURLError):
        _http(handler, resolver=resolver).get("https://example.com/start")


def test_response_size_limit():
    big = b"x" * 5000

    def handler(req):
        return httpx.Response(200, content=big) if req.url.path != "/robots.txt" else httpx.Response(404)

    with pytest.raises(FetchError, match="exceeded|too large"):
        _http(handler, max_bytes=1000).get("https://example.com/big")


def test_robots_disallow_respected():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(200, text="ok")

    h = _http(handler)
    assert h.get("https://example.com/public").status_code == 200
    with pytest.raises(RobotsDisallowedError):
        h.get("https://example.com/private/page")


def test_loopback_only_without_token(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/sources").status_code == 200  # TestClient counts as local


def test_non_loopback_rejected_without_token(client, monkeypatch):
    import app.api.deps as deps

    monkeypatch.setattr(deps, "_is_loopback", lambda host: False)
    assert client.get("/api/sources").status_code == 403
    assert client.get("/api/health").status_code == 200  # health stays public


def test_token_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "api_token", "s3cret-token")
    assert client.get("/api/sources").status_code == 401
    assert client.get("/api/sources", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/sources", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_direct_local_browser_needs_no_token(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(get_settings(), "api_token", "s3cret-token")
    with TestClient(app, client=("127.0.0.1", 50000)) as local:
        assert local.get("/api/sources").status_code == 200  # laptop's own browser
        assert local.get("/api/sources", headers={"Authorization": "Bearer wrong"}).status_code == 401
        for h in ("X-Forwarded-For", "Cf-Connecting-Ip", "Forwarded"):  # tunnels / proxies are never local
            assert local.get("/api/sources", headers={h: "203.0.113.9"}).status_code == 401
        monkeypatch.setattr(get_settings(), "local_access_without_token", False)
        assert local.get("/api/sources").status_code == 401
    with TestClient(app, client=("192.168.1.20", 50000)) as lan:
        assert lan.get("/api/sources").status_code == 401  # other devices on Wi-Fi need the token


def test_refuses_public_bind_without_token(monkeypatch):
    from app import main

    monkeypatch.setattr(get_settings(), "host", "0.0.0.0")
    monkeypatch.setattr(get_settings(), "api_token", None)
    with pytest.raises(SystemExit, match="Refusing"):
        main.main()


def test_url_import_blocks_ssrf(client, monkeypatch):
    import app.http_client as hc

    monkeypatch.setattr(hc, "default_resolver", lambda host: ["127.0.0.1"])
    r = client.post("/api/imports/url", json={"url": "http://intranet.example/admin"})
    assert r.status_code == 400 and "non-public" in r.json()["detail"]


def test_proxied_request_needs_token(client, monkeypatch):
    # Behind Caddy/Nginx/Tailscale Serve the client address is loopback — must not count as local.
    assert client.get("/api/sources", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 403
    monkeypatch.setattr(get_settings(), "api_token", "tok")
    assert client.get("/api/sources", headers={"X-Forwarded-For": "203.0.113.9", "Authorization": "Bearer tok"}).status_code == 200


def test_slow_drip_response_is_cut_off(web, monkeypatch):
    """A server that trickles bytes forever must not hang a job."""
    import httpx

    from app.http_client import FetchError, SafeHttp

    class Drip(httpx.SyncByteStream):
        def __iter__(self):
            while True:
                yield b"x"

    web.routes["http://slow.example/"] = lambda req: httpx.Response(200, stream=Drip(), headers={"content-type": "text/html"})
    http = SafeHttp()
    http.max_seconds = 0.2
    try:
        http.get("http://slow.example/")
        raise AssertionError("should have been cut off")
    except FetchError as exc:
        assert "longer than" in str(exc) or "exceeded" in str(exc)
