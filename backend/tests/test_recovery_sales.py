"""Website Recovery → Outreach → Pipeline: owner approval, factual draft, contact filtering, lost reasons,
per-source comparison, safe export. Synthetic businesses only; nothing touches the network.
"""

from __future__ import annotations

import csv
import io

from app.db import SessionLocal
from app.ioi3 import recovery_intel as intel
from app.ioi3.models import Company

from tests.test_recovery_intel import _call, _check, _company


def _r1(db, **kw):
    c = _company(db, **kw)
    _check(db, c.id, status="unhealthy_suspected", observed="domain_expired_or_unresolved", hours_ago=30)
    _check(db, c.id, status="unhealthy_confirmed", observed="domain_expired_or_unresolved")
    _call(db, c.id)
    return c


def test_r2_lead_cannot_be_approved(client):
    with SessionLocal() as db:
        c = _company(db)
        _check(db, c.id)
        cid = c.id
    r = client.post(f"/api/v3/recovery/companies/{cid}/approve")
    assert r.status_code == 422 and "Business currently operating" in r.json()["detail"]
    assert all(it["id"] != cid for it in client.get("/api/v3/outreach").json())


def test_approved_r1_lead_appears_in_outreach_with_a_factual_draft(client):
    with SessionLocal() as db:
        cid = _r1(db).id
    r = client.post(f"/api/v3/recovery/companies/{cid}/approve")
    assert r.status_code == 200, r.text
    msg = r.json()["message"]
    assert "dead.example" in msg and "domain may have lapsed" in msg and "again on" in msg
    assert "reply 'no'" in msg
    # never presents the outage as their need, never promises a result
    assert "you need" not in msg.lower() and "guarantee" not in msg.lower()

    item = next(it for it in client.get("/api/v3/outreach").json() if it["id"] == cid)
    assert item["lead_source"] == "website_recovery"
    assert item["outreach"]["message"] == msg
    assert any("domain and hosting" in q for q in item["outreach"]["questions"])


def test_outreach_hides_unapproved_personal_looking_contacts_for_recovery_leads(client):
    with SessionLocal() as db:
        c = _r1(db, contacts=(("phone", "+91 44 2491 0236", True), ("email", "owner@gmail.com", False)))
        cid = c.id
    assert client.post(f"/api/v3/recovery/companies/{cid}/approve").status_code == 200
    item = next(it for it in client.get("/api/v3/outreach").json() if it["id"] == cid)
    assert [x["value"] for x in item["contacts"]] == ["+91 44 2491 0236"]


def test_rejected_contact_never_reaches_outreach(client):
    with SessionLocal() as db:
        c = _r1(db, contacts=(("phone", "+91 44 2491 0236", True), ("phone", "+91 44 2491 0999", True)))
        cid, bad = c.id, c.contacts[1].id
    assert client.post(f"/api/v3/recovery/companies/{cid}/approve").status_code == 200
    assert client.post(f"/api/v3/recovery/contacts/{bad}/review", json={"decision": "rejected"}).status_code == 200
    item = next(it for it in client.get("/api/v3/outreach").json() if it["id"] == cid)
    assert [x["value"] for x in item["contacts"]] == ["+91 44 2491 0236"]


def test_owner_edited_message_is_kept(client):
    with SessionLocal() as db:
        cid = _r1(db).id
    r = client.post(f"/api/v3/recovery/companies/{cid}/approve", json={"message": "Hello, my own words about your website."})
    assert r.json()["message"] == "Hello, my own words about your website."


def test_lost_reason_is_recorded_and_screened(client):
    with SessionLocal() as db:
        cid = _r1(db).id
    client.post(f"/api/v3/recovery/companies/{cid}/approve")
    assert client.post(f"/api/v3/companies/{cid}/contacted", json={"channel": "phone"}).status_code == 200
    deal = client.post(f"/api/v3/companies/{cid}/to-pipeline").json()
    bad = client.post(f"/api/v3/deals/{deal['id']}/stage", json={"outcome": "lost", "outcome_reason": "call 98400 12345"})
    assert bad.status_code == 422
    ok = client.post(f"/api/v3/deals/{deal['id']}/stage", json={"outcome": "lost", "outcome_reason": "Nephew maintains the site"})
    assert ok.json()["outcome_reason"] == "Nephew maintains the site" and ok.json()["lead_source"] == "website_recovery"
    reopened = client.post(f"/api/v3/deals/{deal['id']}/stage", json={"outcome": None})
    assert reopened.json()["outcome"] is None and reopened.json()["outcome_reason"] is None


def test_compare_counts_recorded_activity_per_source(client):
    with SessionLocal() as db:
        cid = _r1(db).id
    client.post(f"/api/v3/recovery/companies/{cid}/approve")
    client.post(f"/api/v3/companies/{cid}/contacted", json={"channel": "phone"})
    client.post(f"/api/v3/companies/{cid}/reply", json={"summary": "Asked for a quote", "interested": True})
    src = next(s for s in client.get("/api/v3/recovery/compare").json()["sources"] if s["source"] == "website_recovery")
    assert src["approved"] >= 1 and src["contacted"] >= 1 and src["replied"] >= 1
    assert src["reply_rate"] is None  # too few contacted to call it a rate


def test_export_has_r1_leads_only_with_usable_contacts_and_no_formulas(client):
    with SessionLocal() as db:
        lead = _r1(db, name="=HYPERLINK(\"x\")", contacts=(("phone", "+91 44 2491 0236", True), ("email", "me@gmail.com", False)))
        r2 = _company(db, name="Not Ready Yet")
        _check(db, r2.id)
        lead_id = lead.id
    r = client.get("/api/v3/recovery/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == intel.EXPORT_HEADER
    names = {row[1] for row in rows[1:]}
    assert "Not Ready Yet" not in names
    row = next(row for row in rows[1:] if row[0] == str(lead_id))
    assert row[1].startswith("'=")                       # CSV-injection guard
    assert "gmail" not in row[11] and "2491 0236" in row[11]
    with SessionLocal() as db:
        assert db.get(Company, lead_id).outreach_approved_at is None  # exporting approves nothing
