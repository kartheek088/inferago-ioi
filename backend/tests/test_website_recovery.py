"""Website Recovery: classification, false-positive guards, confirmation, DB runs, privacy and API.

No test touches the live internet: HTTP and DNS go through the `web` fixture.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.db import SessionLocal, utcnow
from app.http_client import SafeHttp
from app.ioi3 import core, website_recovery as wr
from app.ioi3.models import Company, WebsiteCheck

SITE = "https://sharma-engineering.example"
REAL_HTML = "<html><head><title>Sharma Engineering</title></head><body><h1>Sharma Engineering</h1>" + \
    ("<p>We supply and service pumps and motors across Chennai and Tamil Nadu. Call the office for quotes.</p>" * 6) + \
    "</body></html>"


def _http(web, **kw) -> SafeHttp:
    return SafeHttp(client=web.client(), resolver=lambda h: ["93.184.216.34"], rate_limit_per_minute=600,
                    respect_robots=kw.pop("respect_robots", False), **kw)


def _obs(**kw) -> wr.Observation:
    o = wr.Observation(url=kw.pop("url", SITE + "/"))
    for k, v in kw.items():
        setattr(o, k, v)
    if "body" not in kw and "html" in kw:
        o.body = wr._visible(kw["html"])
    return o


# --- pure classification -----------------------------------------------------------------------

@pytest.mark.parametrize("obs, status, observed", [
    (_obs(http_status=200, html=REAL_HTML.lower(), body=wr._visible(REAL_HTML)), "healthy", None),
    (_obs(http_status=404, html="not found"), "unhealthy_suspected", "not_found"),
    (_obs(http_status=410, html="gone"), "unhealthy_suspected", "not_found"),
    (_obs(http_status=500, html="error"), "unhealthy_suspected", "server_error"),
    (_obs(http_status=503, html="x"), "unhealthy_suspected", "server_error"),
    (_obs(http_status=403, html="forbidden"), "access_restricted", None),
    (_obs(http_status=429, html="slow down"), "access_restricted", None),
    (_obs(http_status=200, html="<title>just a moment...</title> cf-chl"), "access_restricted", None),
    (_obs(http_status=200, html="<h1>this domain is for sale</h1>"), "unhealthy_suspected", "placeholder_or_parked"),
    (_obs(http_status=200, html="<h1>welcome to nginx!</h1>"), "unhealthy_suspected", "placeholder_or_parked"),
    (_obs(http_status=200, html="<p>account suspended</p>"), "unhealthy_suspected", "placeholder_or_parked"),
    (_obs(http_status=200, html="<p>site under construction</p>"), "unhealthy_suspected", "placeholder_or_parked"),
    (_obs(http_status=200, html="<p>under maintenance, back soon</p>"), "unknown", None),
    (_obs(http_status=200, html="<p>page not found</p>"), "unhealthy_suspected", "not_found"),
    (_obs(http_status=200, html="<html></html>"), "unknown", None),
    (_obs(dns="unresolved"), "unhealthy_suspected", "domain_expired_or_unresolved"),
    (_obs(dns="policy_blocked", error_text="private"), "unknown", None),
    (_obs(error_kind="timeout"), "network_failure", None),
    (_obs(error_kind="tls"), "unhealthy_suspected", "tls_problem"),
    (_obs(error_kind="refused"), "unhealthy_suspected", "server_error"),
    (_obs(error_kind="robots"), "access_restricted", None),
    (_obs(error_kind="other", error_text="too large"), "unknown", None),
])
def test_classify(obs, status, observed):
    v = wr.classify(obs)
    assert v.status == status
    assert v.observed_class == observed


def test_redirect_to_marketplace_and_new_domain_are_not_outages():
    store = _obs(http_status=200, url=SITE + "/", final_url="https://shop.myshopify.com/", html=REAL_HTML.lower(),
                 body=wr._visible(REAL_HTML))
    moved = _obs(http_status=200, url=SITE + "/", final_url="https://sharmaeng.in/", html=REAL_HTML.lower(),
                 body=wr._visible(REAL_HTML))
    assert wr.classify(store).status == "migrated_to_storefront"
    assert wr.classify(moved).status == "redirected_to_active_site"
    assert wr.classify(store).observed_class is None


def test_a_parked_page_behind_a_redirect_is_still_a_failure():
    parked = _obs(http_status=200, url=SITE + "/", final_url="https://parking.example/", html="<p>this domain is for sale</p>")
    assert wr.classify(parked).observed_class == "placeholder_or_parked"


def test_the_site_is_checked_not_directories_or_social_pages():
    assert wr.is_own_site("https://sharma-engineering.example/")
    assert not wr.is_own_site("https://www.instagram.com/sharma")
    assert not wr.is_own_site("https://www.indiamart.com/sharma-engineering/")


# --- confirmation -------------------------------------------------------------------------------

def test_one_observation_never_confirms_an_outage():
    v = wr.confirm(wr.classify(_obs(http_status=404, html="x")), None, utcnow(), 24)
    assert v.status == "unhealthy_suspected"


def test_a_repeat_is_confirmed_only_after_the_interval():
    now = utcnow()
    too_soon = wr.confirm(wr.classify(_obs(http_status=404, html="x")), now - timedelta(hours=2), now, 24)
    later = wr.confirm(wr.classify(_obs(http_status=404, html="x")), now - timedelta(hours=30), now, 24)
    assert too_soon.status == "unhealthy_suspected"
    assert later.status == "unhealthy_confirmed"


# --- real HTTP path through SafeHttp, mocked ---------------------------------------------------

def test_probe_healthy_and_real_errors(web):
    web.text(SITE + "/", REAL_HTML)
    assert wr.classify(wr.probe(SITE + "/", _http(web))).status == "healthy"

    web.error(SITE + "/gone", 404)
    obs = wr.probe(SITE + "/gone", _http(web))
    assert obs.http_status == 404
    assert wr.classify(obs).observed_class == "not_found"


def test_probe_bot_block_is_not_an_outage(web):
    web.error(SITE + "/", 403)
    assert wr.classify(wr.probe(SITE + "/", _http(web))).status == "access_restricted"


def test_probe_timeout_is_a_network_problem_not_a_website_failure(web):
    web.raise_timeout(SITE + "/")
    obs = wr.probe(SITE + "/", _http(web))
    assert obs.error_kind == "timeout"
    assert wr.classify(obs).status == "network_failure"


def test_probe_tls_and_refused(web):
    def tls(req):
        raise httpx.ConnectError("certificate verify failed: certificate has expired", request=req)

    def refused(req):
        raise httpx.ConnectError("[Errno 111] Connection refused", request=req)

    web.routes[SITE + "/tls"] = tls
    web.routes[SITE + "/down"] = refused
    assert wr.classify(wr.probe(SITE + "/tls", _http(web))).observed_class == "tls_problem"
    assert wr.classify(wr.probe(SITE + "/down", _http(web))).observed_class == "server_error"


def test_probe_redirect_to_marketplace(web):
    web.routes[SITE + "/"] = lambda req: httpx.Response(301, headers={"location": "https://sharma.indiamart.com/"})
    web.text("https://sharma.indiamart.com/", REAL_HTML)
    obs = wr.probe(SITE + "/", _http(web))
    assert wr.classify(obs).status == "migrated_to_storefront"


def test_dns_failure_and_private_address_are_different(web):
    def nxdomain(host):
        raise OSError("nxdomain")

    obs_dns = wr.probe("https://gone.example/", SafeHttp(client=web.client(), resolver=nxdomain, respect_robots=False))
    assert obs_dns.dns == "unresolved"
    assert wr.classify(obs_dns).observed_class == "domain_expired_or_unresolved"

    obs_priv = wr.probe("https://lan.example/", SafeHttp(client=web.client(), resolver=lambda h: ["10.0.0.5"], respect_robots=False))
    assert obs_priv.dns == "policy_blocked"
    assert wr.classify(obs_priv).status == "unknown"


def test_robots_disallow_is_respected(web):
    web.text(SITE + "/robots.txt", "User-agent: *\nDisallow: /", content_type="text/plain")
    obs = wr.probe(SITE + "/", _http(web, respect_robots=True))
    assert obs.error_kind == "robots"
    assert wr.classify(obs).status == "access_restricted"


# --- DB runs ------------------------------------------------------------------------------------

def _company(db, name: str, website: str, locality: str = "Adyar") -> Company:
    camp = core.active_campaign(db)
    c = core.new_company(camp.id, name=name, source_key="test", source_ref=name, source_url="https://example.test/")
    c.website, c.locality = website, locality
    db.add(c)
    db.commit()
    return c


def test_run_checks_suspect_then_confirm_and_skip_recent(web, monkeypatch):
    web.text(SITE + "/", REAL_HTML)  # Sharma: healthy
    web.error("https://dead.example/", 404)
    with SessionLocal() as db:
        ok = _company(db, "Sharma Engineering", SITE + "/")
        dead = _company(db, "Dead Traders", "https://dead.example/")
        ok_id, dead_id = ok.id, dead.id

    monkeypatch.setattr(wr, "SafeHttp", lambda **kw: _http(web))
    with SessionLocal() as db:
        first = wr.run_checks(db, limit=10)
    assert first["checked"] == 2
    assert first["failures_detected"] == 1 and first["confirmed"] == 0

    with SessionLocal() as db:
        again = wr.run_checks(db, limit=10)  # within 24h, not forced: skipped
    assert again["checked"] == 0 and again["skipped_recent"] == 2

    with SessionLocal() as db:
        repeat = wr.run_checks(db, company_ids=[dead_id], limit=10, force=True, min_confirm_hours=0)
    assert repeat["confirmed"] == 1

    with SessionLocal() as db:
        d = wr.dossier(db, dead_id)
        o = wr.dossier(db, ok_id)
    assert [c["status"] for c in d["checks"]] == ["unhealthy_confirmed", "unhealthy_suspected"]  # history kept
    assert o["checks"][0]["status"] == "healthy"


def test_checks_store_classification_not_page_html(web, monkeypatch):
    web.text(SITE + "/", REAL_HTML)
    with SessionLocal() as db:
        _company(db, "Sharma Engineering", SITE + "/")
    monkeypatch.setattr(wr, "SafeHttp", lambda **kw: _http(web))
    with SessionLocal() as db:
        wr.run_checks(db, limit=5)
    with SessionLocal() as db:
        row = db.execute(select(WebsiteCheck)).scalar_one()
        columns = {c.name for c in WebsiteCheck.__table__.columns}
    assert "html" not in columns and "body" not in columns
    assert "Sharma Engineering" not in (row.error_text or "")
    assert row.status == "healthy"


def test_only_b2b_own_sites_are_candidates(web, monkeypatch):
    with SessionLocal() as db:
        _company(db, "Social Only", "https://www.instagram.com/socialonly")
        _company(db, "No Site", "")
    monkeypatch.setattr(wr, "SafeHttp", lambda **kw: _http(web))
    with SessionLocal() as db:
        summary = wr.run_checks(db, limit=10)
    assert summary["checked"] == 0


def test_limit_is_capped(web, monkeypatch):
    with SessionLocal() as db:
        todo, _ = wr.candidates(db, company_ids=None, limit=10_000, force=True, recheck_hours=24, now=utcnow())
    assert len(todo) <= wr.MAX_PER_RUN


def test_overview_counts_come_from_latest_checks(web, monkeypatch):
    web.text(SITE + "/", REAL_HTML)
    web.error("https://dead.example/", 404)
    with SessionLocal() as db:
        _company(db, "Sharma Engineering", SITE + "/")
        _company(db, "Dead Traders", "https://dead.example/")
    monkeypatch.setattr(wr, "SafeHttp", lambda **kw: _http(web))
    with SessionLocal() as db:
        wr.run_checks(db, limit=10)
    with SessionLocal() as db:
        ov = wr.overview(db)
    assert ov["businesses_discovered"] == 2
    assert ov["websites_checked"] == 2
    # A first failure is suspected, so it belongs in Needs Verification, not High Priority.
    assert ov["excluded"] == 1 and ov["needs_verification"] == 1 and ov["high_priority"] == 0
    assert ov["by_status"]["unhealthy_suspected"] == 1


# --- API ----------------------------------------------------------------------------------------

def test_api_overview_tabs_and_dossier(client, web):
    r = client.get("/api/v3/recovery/overview")
    assert r.status_code == 200 and r.json()["businesses_discovered"] == 0
    assert client.get("/api/v3/recovery/companies", params={"tab": "bogus"}).status_code == 400
    assert client.get("/api/v3/recovery/companies", params={"tab": "high_priority"}).json()["items"] == []
    assert client.get("/api/v3/recovery/companies/99999").status_code == 404


def test_api_check_runs_and_is_bounded(client, web, monkeypatch):
    web.text(SITE + "/", REAL_HTML)
    with SessionLocal() as db:
        c = _company(db, "Sharma Engineering", SITE + "/")
        cid = c.id
    monkeypatch.setattr(wr, "SafeHttp", lambda **kw: _http(web))
    assert client.post("/api/v3/recovery/check", json={"limit": 999}).status_code == 422
    r = client.post("/api/v3/recovery/check", json={"company_ids": [cid], "limit": 5})
    assert r.status_code == 200
    assert r.json()["checked"] == 1
    d = client.get(f"/api/v3/recovery/companies/{cid}").json()
    assert d["checks"][0]["status"] == "healthy"
    assert "html" not in d["checks"][0]


def test_api_requires_the_token_like_every_other_router(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "api_token", "s3cret-token")
    assert client.get("/api/v3/recovery/overview").status_code == 401
    assert client.post("/api/v3/recovery/check", json={"limit": 1}).status_code == 401
    ok = client.get("/api/v3/recovery/overview", headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200


def test_api_caps_the_company_id_list(client):
    assert client.post("/api/v3/recovery/check", json={"company_ids": list(range(201))}).status_code == 422


# --- regressions from the real-source validation run (2026-11-26) ------------------------------

LONG = "<p>" + ("Pumps, motors and spares supplied and serviced across Chennai. " * 20) + "</p>"


def test_a_contact_form_captcha_on_a_working_site_is_not_a_bot_block():
    # Shapes seen live: a CSS class and a WordPress Contact Form 7 captcha plugin on normal pages.
    css = _obs(http_status=200, html=("<style>.labels.captcha_lab{color:red}</style>" + LONG).lower())
    plugin = _obs(http_status=200, html=("<link href='/wp-content/plugins/contact-form-7-image-captcha/css/x.css'>" + LONG).lower())
    faq = _obs(http_status=200, html=("<p>access denied errors on the old portal are fixed.</p>" + LONG).lower())
    assert wr.classify(css).status == "healthy"
    assert wr.classify(plugin).status == "healthy"
    assert wr.classify(faq).status == "healthy"


def test_a_real_challenge_page_is_still_access_restricted():
    # Shape seen live: a ~2 KB LiteSpeed reCAPTCHA page that auto-submits a form.
    ls = _obs(http_status=200, html="<form id='lsrecaptcha-form'></form><script>document.getElementById('lsrecaptcha-form').submit();</script>")
    short = _obs(http_status=200, html="<h1>access denied</h1>")
    assert wr.classify(ls).status == "access_restricted"
    assert wr.classify(short).status == "access_restricted"


def _fail_only(target: str):
    def resolver(host):
        if host == target:
            raise OSError("nxdomain")
        return ["93.184.216.34"]
    return resolver


def test_independent_resolvers_confirm_nxdomain(web):
    web.json("https://cloudflare-dns.com/dns-query", {"Status": 3})
    web.json("https://dns.google/resolve", {"Status": 3})
    http = SafeHttp(client=web.client(), resolver=_fail_only("gone.example"), respect_robots=False)
    obs = wr.probe("https://gone.example/", http)
    assert obs.independent_dns == {"cloudflare": "nxdomain", "google": "nxdomain"}
    v = wr.classify(obs)
    assert v.observed_class == "domain_expired_or_unresolved" and v.confidence == "medium"
    assert v.status == "unhealthy_suspected"  # still needs the timed recheck to be confirmed


def test_local_dns_failure_that_resolves_elsewhere_is_our_network(web):
    web.json("https://cloudflare-dns.com/dns-query", {"Status": 0, "Answer": [{"data": "93.184.216.34"}]})
    web.json("https://dns.google/resolve", {"Status": 0, "Answer": [{"data": "93.184.216.34"}]})
    http = SafeHttp(client=web.client(), resolver=_fail_only("flaky.example"), respect_robots=False)
    v = wr.classify(wr.probe("https://flaky.example/", http))
    assert v.status == "network_failure"
    assert v.observed_class is None


def test_unreachable_resolvers_are_no_evidence(web):
    web.error("https://cloudflare-dns.com/dns-query", 503)
    web.error("https://dns.google/resolve", 503)
    http = SafeHttp(client=web.client(), resolver=_fail_only("gone.example"), respect_robots=False)
    v = wr.classify(wr.probe("https://gone.example/", http))
    assert v.observed_class == "domain_expired_or_unresolved" and v.confidence == "low"
