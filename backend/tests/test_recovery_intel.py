"""Website Recovery intelligence: activity, contacts, scope, R0-R3 gates, evidence API, newer-site discovery.

All businesses are synthetic. No test touches the live internet (the `web` fixture mocks HTTP and DNS).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import lead_rules
from app.db import SessionLocal, utcnow
from app.http_client import SafeHttp
from app.ioi3 import core, recovery_intel as intel, website_recovery as wr
from app.ioi3.models import CompanyContact, WebsiteCheck

TODAY = date(2026, 11, 26)
REAL_HTML = "<html><body>" + ("<p>Pumps and motors supplied and serviced across Chennai, call the office.</p>" * 8) + "</body></html>"


def ev(kind="official_social", signal="active", days_ago: int | None = 10, url="https://facebook.example/biz", method="manual",
       observed_days_ago: int = 0):
    pub = TODAY - timedelta(days=days_ago) if days_ago is not None else None
    return intel.Ev(kind, signal, method, pub, TODAY - timedelta(days=observed_days_ago), url)


# --- activity ----------------------------------------------------------------------------------

def test_two_independent_recent_sources_verify_activity():
    s, _ = intel.classify_activity([ev(url="https://facebook.example/biz"),
                                    ev("marketplace_listing", url="https://indiamart.example/biz")], TODAY)
    assert s == "active_verified"


def test_two_posts_on_the_same_page_are_one_source():
    s, _ = intel.classify_activity([ev(days_ago=3), ev(days_ago=20)], TODAY)
    assert s == "active_probable"


def test_a_call_with_the_business_verifies_activity():
    s, why = intel.classify_activity([ev("phone_call", days_ago=None, url=None, observed_days_ago=2)], TODAY)
    assert s == "active_verified" and "reached" in why[0]


def test_stale_social_evidence_is_not_current_activity():
    s, _ = intel.classify_activity([ev(days_ago=200)], TODAY)
    assert s == "inactive_suspected"


def test_undated_directory_listing_is_not_proof():
    s, why = intel.classify_activity([ev("marketplace_listing", days_ago=None)], TODAY)
    assert s == "activity_unclear" and "undated" in why[0]


def test_no_evidence_is_unclear():
    assert intel.classify_activity([], TODAY)[0] == "activity_unclear"


def test_window_is_configurable():
    e = [ev(days_ago=100)]
    assert intel.classify_activity(e, TODAY, 180)[0] == "active_probable"
    assert intel.classify_activity(e, TODAY, 90)[0] == "inactive_suspected"


def test_closed_recorded_by_owner_wins_over_older_activity():
    s, _ = intel.classify_activity([ev(days_ago=40), ev("phone_call", "closed", None, None, observed_days_ago=1)], TODAY)
    assert s == "closed_verified"


def test_newer_activity_wins_over_an_older_closed_report():
    s, _ = intel.classify_activity([ev("other", "closed", 60, observed_days_ago=60),
                                    ev("phone_call", days_ago=None, url=None, observed_days_ago=1)], TODAY)
    assert s == "active_verified"


def test_an_automatic_closed_report_is_only_suspected():
    s, _ = intel.classify_activity([ev("news", "closed", 5, method="automatic", observed_days_ago=5)], TODAY)
    assert s == "inactive_suspected"


def test_future_dates_never_count_as_recent():
    assert intel.classify_activity([ev(days_ago=-5)], TODAY)[0] == "inactive_suspected"


# --- contacts ----------------------------------------------------------------------------------

def _contact(kind, value, official):
    return CompanyContact(id=1, company_id=1, kind=kind, value=value, source_url="https://example.test/", official=official)


@pytest.mark.parametrize("kind, value, official, usable, label", [
    ("phone", "+91 98400 12345", False, False, "mobile"),  # directory mobile: may be a person's own number
    ("phone", "+91 98400 12345", True, True, "mobile"),  # published on the business's own site
    ("phone", "+91 44 2491 0236", False, True, "office landline"),
    ("phone", "044-24910236", False, True, "office landline"),
    ("phone", "1800 425 1234", False, True, "toll-free business line"),
    ("phone", "12345", False, False, "office landline"),
    ("email", "sharmaeng123@gmail.com", False, False, "free email address"),
    ("email", "sales@sharma-engineering.example", False, True, "business email"),
    ("contact_form", "https://sharma.example/contact", True, True, "contact form"),
])
def test_contact_screening(kind, value, official, usable, label):
    v = intel.contact_view(_contact(kind, value, official))
    assert v["usable"] is usable
    assert v["kind_label"] == label


@pytest.mark.parametrize("text, bad", [
    ("Posted a new pump catalogue on 20 Nov", False),
    ("Spoke to them, call back on 98400 12345", True),
    ("Owner email is someone@gmail.com", True),
    ("Shop open 9 to 6, Mon-Sat", False),
])
def test_notes_are_screened_for_contact_details(text, bad):
    assert intel.has_contact_details(text) is bad


# --- qualification (DB) ------------------------------------------------------------------------

def _company(db, name="Sharma Engineering", website="https://dead.example/", *, category="industrial_equipment_manufacturer",
             industry=lead_rules.EQUIPMENT, location="verified", contacts=(("phone", "+91 44 2491 0236", True),)):
    camp = core.active_campaign(db)
    c = core.new_company(camp.id, name=name, source_key="test", source_ref=name, source_url="https://example.test/")
    c.website, c.industry, c.directory_category, c.location_confidence = website, industry, category, location
    for kind, value, official in contacts:
        c.contacts.append(CompanyContact(kind=kind, value=value, source_url="https://example.test/", official=official))
    db.add(c)
    db.commit()
    return c


def _check(db, cid, status="unhealthy_confirmed", observed="not_found", hours_ago=0.0):
    db.add(WebsiteCheck(company_id=cid, website_url="https://dead.example/", checked_at=utcnow() - timedelta(hours=hours_ago),
                        dns_result="ok", http_status=404, status=status, observed_class=observed, confidence="high", reasons=[]))
    db.commit()


def _call(db, cid, **kw):
    return intel.add_evidence(db, cid, kind=kw.pop("kind", "phone_call"), signal=kw.pop("signal", "active"),
                              statement=kw.pop("statement", "Business answered and said they are trading"),
                              source_url=kw.pop("source_url", None), published_on=kw.pop("published_on", None),
                              observed_on=kw.pop("observed_on", None), confirms_chennai=kw.pop("confirms_chennai", False),
                              actor="owner")


def _row(db, cid):
    return next(r for r in intel.board(db) if r["company_id"] == cid)


def test_r1_needs_every_gate():
    with SessionLocal() as db:
        c = _company(db)
        _check(db, c.id)
        assert _row(db, c.id)["qualification"] == "R2"  # operating not verified yet
        _call(db, c.id)
        r = _row(db, c.id)
    assert r["qualification"] == "R1" and r["bucket"] == "high_priority"


def test_directory_only_location_blocks_r1_until_confirmed_on_a_call():
    with SessionLocal() as db:
        c = _company(db, location="partial")
        _check(db, c.id)
        _call(db, c.id)
        assert _row(db, c.id)["qualification"] == "R2"
        _call(db, c.id, confirms_chennai=True)
        assert _row(db, c.id)["qualification"] == "R1"


def test_a_suspected_failure_is_not_r1():
    with SessionLocal() as db:
        c = _company(db)
        _check(db, c.id, status="unhealthy_suspected")
        _call(db, c.id)
        assert _row(db, c.id)["qualification"] == "R2"


def test_only_review_needed_contacts_block_r1():
    with SessionLocal() as db:
        c = _company(db, contacts=(("phone", "+91 98400 12345", False), ("email", "x123@gmail.com", False)))
        _check(db, c.id)
        _call(db, c.id)
        d = intel.dossier(db, c.id)
    gate = next(g for g in d["qualification"]["gates"] if g["key"] == "contact")
    assert d["qualification"]["category"] == "R2" and not gate["passed"]


def test_out_of_scope_business_type_is_excluded():
    with SessionLocal() as db:
        c = _company(db, category="gym")
        _check(db, c.id)
        _call(db, c.id)
        from app.settings_store import set_setting

        set_setting(db, intel.SCOPE_KEY, {"categories": ["industrial_equipment_manufacturer"], "window_days": 90})
        db.commit()
        r = _row(db, c.id)
    assert r["qualification"] == "R3" and r["bucket"] == "excluded"


def test_outside_campaign_industry_is_excluded():
    with SessionLocal() as db:
        c = _company(db, industry=None)
        _check(db, c.id)
        assert _row(db, c.id)["bucket"] == "excluded"


def test_confirmed_need_is_r0_and_closed_is_excluded():
    with SessionLocal() as db:
        a = _company(db, name="Asha Pumps", location="partial")
        _check(db, a.id, status="unhealthy_suspected")
        _call(db, a.id, kind="confirmed_need", statement="They asked us to look at the site")
        b = _company(db, name="Old Traders")
        _check(db, b.id)
        _call(db, b.id, signal="closed", statement="Number answered by new tenant; business shut")
        assert _row(db, a.id)["qualification"] == "R0"
        assert _row(db, b.id)["qualification"] == "R3"


def test_healthy_site_is_excluded():
    with SessionLocal() as db:
        c = _company(db)
        _check(db, c.id, status="healthy", observed=None)
        assert _row(db, c.id)["bucket"] == "excluded"


# --- evidence validation and API ---------------------------------------------------------------

@pytest.mark.parametrize("kw, msg", [
    ({"observed_on": TODAY + timedelta(days=400)}, "future"),
    ({"statement": "Call 98400 12345 after 5"}, "phone numbers"),
    ({"kind": "official_social", "source_url": None}, "link"),
    ({"kind": "official_social", "source_url": "javascript:alert(1)"}, "http"),
    ({"kind": "official_social", "source_url": "https://facebook.example/x", "confirms_chennai": True}, "call"),
    ({"kind": "confirmed_need", "signal": "closed"}, "active"),
])
def test_evidence_validation(kw, msg):
    with SessionLocal() as db:
        c = _company(db)
        with pytest.raises(intel.EvidenceError, match=msg):
            _call(db, c.id, **kw)


def test_evidence_api_add_list_delete(client):
    with SessionLocal() as db:
        c = _company(db)
        _check(db, c.id)
        cid = c.id
    r = client.post(f"/api/v3/recovery/companies/{cid}/evidence", json={
        "kind": "official_social", "statement": "New pump range posted", "source_url": "https://facebook.example/sharma",
        "published_on": "2026-11-20"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    d = client.get(f"/api/v3/recovery/companies/{cid}").json()
    assert [e["id"] for e in d["activity"]["manual"]] == [eid]
    assert d["activity"]["automatic"] == []
    assert d["activity"]["status"] == "active_probable"
    bad = client.post(f"/api/v3/recovery/companies/{cid}/evidence", json={"kind": "phone_call", "statement": "mail x@y.com"})
    assert bad.status_code == 422
    assert client.delete(f"/api/v3/recovery/evidence/{eid}").status_code == 204
    assert client.get(f"/api/v3/recovery/companies/{cid}").json()["activity"]["manual"] == []


def test_scope_api(client):
    with SessionLocal() as db:
        _company(db)
    s = client.get("/api/v3/recovery/scope").json()
    assert s["categories"] is None and s["window_days"] == 90
    assert {"industry": lead_rules.EQUIPMENT, "category": "industrial_equipment_manufacturer", "count": 1} in s["available"]
    assert client.put("/api/v3/recovery/scope", json={"categories": ["not_a_type"]}).status_code == 422
    assert client.put("/api/v3/recovery/scope", json={"categories": [], "window_days": 45}).status_code == 422
    ok = client.put("/api/v3/recovery/scope", json={"categories": ["industrial_equipment_manufacturer"], "window_days": 60})
    assert ok.status_code == 200 and ok.json()["window_days"] == 60


def test_dossier_search_links_are_never_fetched(client, web):
    with SessionLocal() as db:
        c = _company(db)
        _check(db, c.id)
        cid = c.id
    d = client.get(f"/api/v3/recovery/companies/{cid}").json()
    assert web.calls == []  # building the dossier made no outbound request
    assert all(x["url"].startswith("https://www.google.com/search?q=") for x in d["check_yourself"])


# --- newer-website discovery and recheck order -------------------------------------------------

def _http(web) -> SafeHttp:
    return SafeHttp(client=web.client(), resolver=lambda h: ["93.184.216.34"], rate_limit_per_minute=600, respect_robots=False)


def test_failing_site_with_a_working_email_domain_site_is_migrated(web, monkeypatch):
    web.error("https://dead.example/", 404)
    web.text("https://sharma-new.example/", REAL_HTML)
    with SessionLocal() as db:
        c = _company(db, contacts=(("email", "sales@sharma-new.example", True), ("email", "owner123@gmail.com", False)))
        cid = c.id
    monkeypatch.setattr(wr, "SafeHttp", lambda **kw: _http(web))
    with SessionLocal() as db:
        s = wr.run_checks(db, limit=5)
    assert s["alternatives_checked"] == 1 and s["alternatives_working"] == 1  # gmail.com is never a candidate
    assert not any("gmail.com" in u for u in web.calls)
    with SessionLocal() as db:
        r = _row(db, cid)
    assert r["bucket"] == "migrated" and r["alternative_found"]


def test_suspected_failures_due_a_recheck_go_first():
    with SessionLocal() as db:
        fresh = _company(db, name="Never Checked", website="https://fresh.example/")
        due = _company(db, name="Due Recheck", website="https://due.example/")
        _check(db, due.id, status="unhealthy_suspected", hours_ago=30)
        todo, skipped = wr.candidates(db, company_ids=None, limit=1, force=False, recheck_hours=24, now=utcnow())
    assert todo[0][0] == due.id and skipped == 0
    assert fresh.id != due.id


# --- owner review of contacts that may be personal ---------------------------------------------

def test_approving_a_directory_mobile_unlocks_the_contact_gate(client):
    with SessionLocal() as db:
        c = _company(db, contacts=(("phone", "+91 98400 12345", False),))
        _check(db, c.id)
        _call(db, c.id)
        cid, contact_id = c.id, c.contacts[0].id
        assert _row(db, cid)["qualification"] == "R2"
    r = client.post(f"/api/v3/recovery/contacts/{contact_id}/review",
                    json={"decision": "approved", "note": "Business answered on this number"})
    assert r.status_code == 200 and r.json()["usable"] is True and r.json()["review"] == "approved"
    with SessionLocal() as db:
        assert _row(db, cid)["qualification"] == "R1"


def test_rejecting_a_contact_blocks_it_even_if_official(client):
    with SessionLocal() as db:
        c = _company(db)  # official landline
        _check(db, c.id)
        _call(db, c.id)
        cid, contact_id = c.id, c.contacts[0].id
        assert _row(db, cid)["qualification"] == "R1"
    assert client.post(f"/api/v3/recovery/contacts/{contact_id}/review", json={"decision": "rejected"}).status_code == 200
    with SessionLocal() as db:
        assert _row(db, cid)["qualification"] == "R2"


def test_contact_review_validation(client):
    with SessionLocal() as db:
        c = _company(db, contacts=(("phone", "+91 98400 12345", False),))
        contact_id = c.contacts[0].id
    assert client.post("/api/v3/recovery/contacts/999999/review", json={"decision": "approved"}).status_code == 404
    assert client.post(f"/api/v3/recovery/contacts/{contact_id}/review", json={"decision": "maybe"}).status_code == 422
    bad = client.post(f"/api/v3/recovery/contacts/{contact_id}/review", json={"decision": "approved", "note": "use 98400 99999"})
    assert bad.status_code == 422


def test_todays_local_date_is_never_future(monkeypatch):
    """Regression: the UTC date lags IST until 05:30, which made today's call look like a future date."""
    local = date(2026, 11, 26)
    monkeypatch.setattr(intel, "local_today", lambda: local)
    with SessionLocal() as db:
        c = _company(db)
        e = _call(db, c.id, observed_on=local)
    assert e.observed_on == local
