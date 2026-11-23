"""Regressions found by running the module against real Chennai sellers' public websites.

Each test here exists because real validation (2026-11-23) exposed the behaviour it pins down.
"""

from __future__ import annotations

import httpx
import pytest

from app.http_client import SafeHttp
from app.ioi3.social import collect, core, research

HOME_HTML = """<html><body><h1>Asha Cakes</h1>
<p>Custom cakes baked to order in Adyar, Chennai 600020. Order 3 days in advance.</p>
<a href="/members">Members area</a>
</body></html>"""

# Google Sites, Notion and similar hosts redirect an anonymous visitor to a sign-in page and still
# return a 200 HTML body. That page belongs to the login provider, not to the seller.
GOOGLE_SIGNIN = """<html><body><h1>Sign in</h1>
<p>Use your Google Account to continue to Sites</p>
<p>Enter your email</p><p>Forgot email?</p><p>Create account</p>
<a href="mailto:noreply@google.example">help</a>
</body></html>"""


@pytest.fixture
def camp(db):
    core.seed_sources(db)
    return core.active_campaign(db)


def test_login_wall_detection_rules():
    assert research.login_wall("https://accounts.google.com/v3/signin/identifier", "Sign in") is not None
    assert research.login_wall("https://shop.example/login",
                               "Enter your password. Forgot password?") is not None
    # A normal seller page is not a login wall, even when it links to a members area.
    assert research.login_wall("https://ashacakes.example/", HOME_HTML) is None


def test_a_sign_in_wall_is_not_read_as_the_sellers_own_page(db, camp, web):
    """Real case: a Chennai home bakery's Google Sites link redirected to accounts.google.com.

    Before this fix IOI stored the sign-in page as the page it had read, and took a contact address
    off the login provider's markup as if the business had published it.
    """
    site = "https://sites.google.example/view/abakery/home"
    signin = "https://accounts.google.com/v3/signin/identifier"
    web.routes[site] = lambda req: httpx.Response(302, headers={"location": signin,
                                                                "content-type": "text/html"})
    web.text(signin, GOOGLE_SIGNIN)
    r = collect.add_profile(db, camp, {"link": "@abakery", "name": "A Bakery", "website": site,
                                       "description": "Custom cakes"})
    c = r.company
    http = SafeHttp(rate_limit_per_minute=20)
    try:
        research.research_seller(db, c, http)
    finally:
        http.close()
    db.commit()
    assert c.social.research_error is not None
    assert "behind a sign-in screen" in c.social.research_error
    assert c.social.research_error_kind == "permanent"
    assert c.social.research_retry_after is None  # retrying would never help
    # Nothing from the login provider was recorded as the seller's own.
    assert not any("google" in (x.value or "").lower() for x in c.contacts)
    assert c.social.pages_checked == []


def test_a_real_page_is_still_read_normally(db, camp, web):
    """The login-wall guard must not block an ordinary seller page."""
    site = "https://ashacakes.example/"
    web.text(site, HOME_HTML)
    r = collect.add_profile(db, camp, {"link": "@asha", "name": "Asha Cakes", "website": site})
    c = r.company
    http = SafeHttp(rate_limit_per_minute=20)
    try:
        research.research_seller(db, c, http)
    finally:
        http.close()
    db.commit()
    assert c.social.research_error is None
    assert c.social.pages_checked
    assert "custom_orders" in (c.social.complexity_keys or [])


def test_undated_signals_are_reported_by_kind(db, camp, web):
    """Real case: the activity gate said "2 activity signal(s)" when both were demand indicators."""
    from datetime import datetime

    from app.ioi3.social import categories as cat
    from app.ioi3.social import geo, qualify

    s = qualify.Snapshot(
        name="X", category=cat.BAKERY, geo_confidence=geo.VERIFIED,
        activity=[qualify.ActivityView("sold_out", "demand_indicator", None, "https://x/1", "hypothesis"),
                  qualify.ActivityView("order_announcement", "demand_indicator", None, "https://x/2", "hypothesis")],
        complexity_keys={"custom_orders"}, official_contacts=1, research_level="public")
    gate = next(g for g in qualify.gates(s, datetime(2026, 11, 23)) if g["key"] == "activity")
    assert gate["passed"] is None
    assert "2 demand indicator(s)" in gate["detail"]
    assert "activity signal" not in gate["detail"]


def test_the_sales_pipeline_is_shared_between_channels(client, db, camp, web):
    """Found by the browser acceptance test: /pipeline was scoped to the B2B campaign, so an approved
    social seller's deal never appeared on the shared board."""
    from app.ioi3 import sales

    site = "https://ashacakes.example/"
    web.text(site, HOME_HTML + "<p>Email hello@ashacakes.example</p>")
    r = collect.add_profile(db, camp, {"link": "@asha2", "name": "Asha Cakes 2", "website": site,
                                       "description": "Custom cakes, 50% advance, order 3 days in advance"})
    c = r.company
    http = SafeHttp(rate_limit_per_minute=20)
    try:
        research.research_seller(db, c, http)
    finally:
        http.close()
    db.commit()
    sales.ensure_deal(db, c)
    db.commit()

    body = client.get("/api/v3/pipeline").json()
    ids = {d["company_id"] for d in body["deals"]}
    assert c.id in ids, "an approved social seller must appear on the shared pipeline"
    deal = next(d for d in body["deals"] if d["company_id"] == c.id)
    assert deal["channel"] == "social_commerce"

    # And it can still be narrowed to one channel.
    only_b2b = client.get("/api/v3/pipeline", params={"channel": "b2b"}).json()
    assert c.id not in {d["company_id"] for d in only_b2b["deals"]}
    only_social = client.get("/api/v3/pipeline", params={"channel": "social_commerce"}).json()
    assert c.id in {d["company_id"] for d in only_social["deals"]}


def test_outreach_is_shared_between_channels(client, db, camp, web):
    from datetime import timedelta

    from app.db import utcnow
    from app.ioi3 import sales

    site = "https://ashacakes.example/"
    # A dated post is what makes the "current activity" gate pass, so the seller can be approved.
    recent = (utcnow() - timedelta(days=5)).strftime("%d %B %Y")
    web.text(site, HOME_HTML + f"<p>Email hello@ashacakes.example</p>"
                               f"<p>New collection just launched. Posted on {recent}.</p>")
    r = collect.add_profile(db, camp, {"link": "@asha3", "name": "Asha Cakes 3", "website": site,
                                       "description": "Custom cakes, 50% advance, order 3 days in advance"})
    c = r.company
    http = SafeHttp(rate_limit_per_minute=20)
    try:
        research.research_seller(db, c, http)
    finally:
        http.close()
    db.commit()
    sales.approve(db, c, "owner")
    db.commit()
    rows = client.get("/api/v3/outreach").json()
    mine = next((x for x in rows if x["id"] == c.id), None)
    assert mine is not None, "an approved social seller must appear in shared Outreach"
    assert mine["channel"] == "social_commerce"
    # It carries the social draft, not the B2B wording.
    assert "reply 'no'" in mine["outreach"]["message"]
