"""Chennai-only refocus: location filtering, industry classification, A–D categorisation,
sales difficulty, pipeline (collect / website check / news), scope enforcement and reset safety.

No live network: websites and feeds go through the `web` MockTransport fixture.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app import chennai, lead_rules, leads
from app.db import engine, utcnow
from app.lead_rules import EQUIPMENT, WHOLESALE, LeadFacts, Signal
from app.models import ActivityLog, ChennaiLead, LeadSignal, Opportunity, Prospect, Source

NOW = datetime(2026, 11, 23, 12, 0)


# ================================================================================================
# Location filtering
# ================================================================================================
@pytest.mark.parametrize("address,expected", [
    ("No 12, Usman Road, T Nagar, Chennai 600017", chennai.CHENNAI_CITY),
    ("45 SIDCO Estate, Ambattur Industrial Estate, Chennai 600058", chennai.CHENNAI_CITY),
    ("Plot 8, Mount Road, Chennai 600002", chennai.CHENNAI_CITY),  # no locality name, but core-city PIN
    ("GST Road, Tambaram, Chennai 600045", chennai.GCMA_OUTSIDE),  # "Chennai" in the text does not override
    ("Avadi, Chennai 600054", chennai.GCMA_OUTSIDE),
    ("Old Mahabalipuram Road, Navalur, Chennai 600130", chennai.GCMA_OUTSIDE),
    ("80 Feet Road, Koramangala, Bengaluru 560034", chennai.OUTSIDE),
    ("Avinashi Road, Coimbatore 641018", chennai.OUTSIDE),
    ("Chennai", chennai.UNKNOWN),  # city name alone is not a verified city address
    ("Porur, Chennai 600116", chennai.UNKNOWN),  # straddles the limit: human check
    ("Phone: 044-2434 5678", chennai.UNKNOWN),  # a Chennai phone code never decides location
    ("", chennai.UNKNOWN),
])
def test_classify_location(address, expected):
    assert chennai.classify_location(address).status == expected


def test_owner_approved_gcma_locality_is_accepted():
    assert chennai.classify_location("Tambaram, Chennai").status == chennai.GCMA_OUTSIDE
    assert chennai.classify_location("Tambaram, Chennai", approved=["tambaram"]).status == chennai.CHENNAI_CITY


def test_find_chennai_address_prefers_city_branch():
    page = ("Head office: 5 MG Road, Bengaluru 560001. Branches. "
            "Chennai branch: 22 Anna Salai, Teynampet, Chennai 600018. Call us.")
    verdict, excerpt = chennai.find_chennai_address(page)
    assert verdict.status == chennai.CHENNAI_CITY
    assert "Teynampet" in excerpt
    assert chennai.find_chennai_address("We serve all of India.") is None


def test_city_bbox():
    assert chennai.in_city_bbox(13.04, 80.23)  # T Nagar
    assert not chennai.in_city_bbox(12.92, 80.10)  # Tambaram (west of box)
    assert not chennai.in_city_bbox(None, None)


# ================================================================================================
# Industry classification
# ================================================================================================
def test_wholesale_candidate_then_strong_with_operations():
    v = lead_rules.classify_industry("Sakthi Pharma Distributors", "pharmaceutical_products_wholesaler")
    assert (v.industry, v.strength) == (WHOLESALE, "candidate")
    v = lead_rules.classify_industry("Sakthi Pharma Distributors", "pharmaceutical_products_wholesaler",
                                     indicators=["dealer_network", "warehouse"])
    assert (v.industry, v.strength) == (WHOLESALE, "strong")


def test_equipment_needs_service_operations_to_be_strong():
    v = lead_rules.classify_industry("Vel Biomedical Equipments", "b2b_hospital_equipment_and_supplies")
    assert (v.industry, v.strength, v.subtype) == (EQUIPMENT, "candidate", "medical")
    v = lead_rules.classify_industry("Vel Biomedical Equipments", "b2b_hospital_equipment_and_supplies",
                                     indicators=["service_ops", "amc_warranty"])
    assert (v.industry, v.strength) == (EQUIPMENT, "strong")


@pytest.mark.parametrize("name,cat", [
    ("Sri Murugan Traders", "grocery_store"),
    ("Kumar Computers", "it_service_and_computer_repair"),
    ("City Mobile Care", "mobile_phone_repair"),
    ("Metro Cash Store", "warehouse_club_store"),
    ("Precision Testing Labs", "laboratory_testing"),
    ("Lakshmi Medicals", "medical_supply_store"),  # retail medical shop, not an equipment business
    ("Ganesh Silks", "clothing_store"),
])
def test_other_industries_are_rejected(name, cat):
    assert lead_rules.classify_industry(name, cat).industry is None


def test_operations_detection():
    text = ("We offer annual maintenance contracts (AMC) and installation and commissioning by our 25 service engineers. "
            "Our dealer network covers 300 retailers.")
    keys = {o["key"] for o in lead_rules.detect_operations(text)}
    assert {"amc_warranty", "installation", "technicians", "dealer_network"} <= keys


# ================================================================================================
# Signals
# ================================================================================================
def test_signal_detection_and_dates():
    text = "On 12 November 2026 the company said it is looking for an inventory management system for its three warehouses."
    found = {s["signal_type"] for s in lead_rules.detect_signals(text)}
    assert "explicit_software_request" in found
    assert lead_rules.find_date_near(text, 0, 30) == datetime(2026, 11, 12)
    assert {s["signal_type"] for s in lead_rules.detect_signals("XYZ inaugurated a new service centre in Guindy")} == {"new_facility"}
    assert lead_rules.detect_signals("We sell quality products.") == []


# ================================================================================================
# Categorisation A–D
# ================================================================================================
def facts(**kw) -> LeadFacts:
    base = dict(name="Vel Biomedical Systems", industry=EQUIPMENT, industry_strength="strong", location_status="chennai_city",
                location_verified=True, activity_status="active", has_contact_route=True, contact_from_official_site=True,
                signals=[Signal("explicit_software_request", "https://news.example/a", NOW - timedelta(days=10), "confirmed")],
                operations=["service_ops", "amc_warranty"])
    base.update(kw)
    return LeadFacts(**base)


def test_category_a_requires_everything():
    cat, reasons = lead_rules.categorise(facts(), NOW)
    assert cat == "A"
    assert any("https://news.example/a" in r for r in reasons)


@pytest.mark.parametrize("change,expected", [
    # Rule-detected (unconfirmed) signal: never A, even if strong.
    (dict(signals=[Signal("explicit_software_request", "https://n.example", NOW - timedelta(days=5), "hypothesis")]), "B"),
    # Expansion / new facility is not software demand.
    (dict(signals=[Signal("new_facility", "https://n.example", NOW - timedelta(days=5), "confirmed")]), "B"),
    # Too old for A.
    (dict(signals=[Signal("operational_problem", "https://n.example", NOW - timedelta(days=120), "confirmed")]), "B"),
    # Unknown date can never be "recent".
    (dict(signals=[Signal("explicit_software_request", "https://n.example", None, "confirmed")]), "B"),
    (dict(location_verified=False), "C"),
    (dict(has_contact_route=False, contact_from_official_site=False), "C"),
    (dict(industry_strength="candidate", operations=[], signals=[]), "C"),
    (dict(location_status="gcma_outside"), "D"),
    (dict(location_status="outside"), "D"),
    (dict(industry=None), "D"),
    (dict(is_duplicate=True), "D"),
    (dict(activity_status="closed"), "D"),
    (dict(eligibility_blocker="Requires ISO 27001 certified vendor"), "D"),
])
def test_category_rules(change, expected):
    assert lead_rules.categorise(facts(**change), NOW)[0] == expected


def test_rejected_signal_is_ignored():
    f = facts(signals=[Signal("explicit_software_request", "https://n.example", NOW - timedelta(days=5), "rejected")], operations=[])
    assert lead_rules.categorise(f, NOW)[0] == "C"


def test_sales_difficulty():
    easier, _ = lead_rules.sales_difficulty(facts(legal_form="small_firm"), NOW, ["Internal business applications"])
    assert easier == "easier"
    hard, reasons = lead_rules.sales_difficulty(facts(legal_form="limited", signals=[], contact_from_official_site=False), NOW, [])
    assert hard == "difficult"
    assert any("public limited" in r for r in reasons)
    unknown, _ = lead_rules.sales_difficulty(facts(signals=[], has_contact_route=False, contact_from_official_site=False), NOW, [])
    assert unknown == "unknown"
    assert lead_rules.legal_form("Vel Systems Private Limited") == "private_limited"
    assert lead_rules.legal_form("Sri Ram Agencies") == "small_firm"


# ================================================================================================
# Pipeline: collect, website check, news
# ================================================================================================
def row(i, name, cat, address, *, phone="+91 98400 00000", website=None, lat=13.04, lon=80.23, brand=None):
    return {"id": f"ov{i}", "name": name, "category": cat, "basic_category": None, "phones": [phone], "websites": [website] if website else [],
            "emails": [], "socials": [], "confidence": 0.9, "operating_status": "open", "address": address, "locality": "Chennai",
            "postcode": None, "country": "IN", "brand": brand, "lat": lat, "lon": lon}


ROWS = [
    row(1, "Vel Biomedical Equipments", "b2b_hospital_equipment_and_supplies", "12 Usman Road, T Nagar", website="https://velbio.example"),
    row(2, "Vel Biomedical Equipments", "b2b_hospital_equipment_and_supplies", "12 Usman Road, T Nagar"),  # duplicate (same phone)
    row(3, "Sakthi Pharma Distributors", "pharmaceutical_products_wholesaler", "Sowcarpet, Chennai 600079", phone="+91 94440 11111"),
    row(4, "Tambaram Elevators", "elevator_service", "GST Road, Tambaram", phone="+91 90000 22222"),  # outside city
    row(5, "Anna Nagar Bakery", "bakery", "Anna Nagar", phone="+91 90000 33333"),  # wrong industry
    row(6, "Big Brand Store", "electronic_equipment_supplier", "Guindy", phone="+91 90000 44444", brand="BigBrand"),  # chain outlet
]


def test_collect_filters_dedupes_and_is_idempotent(db):
    stats = leads.collect(db, "unused", rows=ROWS)
    assert stats["new"] == 2
    assert stats["duplicates"] == 1 and stats["location"] == 1 and stats["industry"] == 1 and stats["other"] == 1
    names = {x.name for x in db.scalars(select(ChennaiLead))}
    assert names == {"Vel Biomedical Equipments", "Sakthi Pharma Distributors"}
    for lead in db.scalars(select(ChennaiLead)):
        assert lead.location_verified is False  # directory text is never verification
        assert lead.category in ("C",)
        assert all(p["source_url"] for p in lead.phones)
    again = leads.collect(db, "unused", rows=ROWS)
    assert again["new"] == 0
    assert db.scalar(select(text("count(*)")).select_from(ChennaiLead)) == 2


HOME = """<html><body><h1>Vel Biomedical Equipments</h1>
<a href="/contact-us">Contact</a> <a href="/services">Services</a> <a href="https://facebook.com/x">FB</a>
<p>Supply, installation and commissioning of hospital equipment. © 2026 Vel Biomedical</p></body></html>"""
CONTACT = """<html><body><h2>Contact</h2><p>Vel Biomedical Equipments, 12 Usman Road, T Nagar, Chennai 600017.</p>
<p>Email: <a href="mailto:service@velbio.example">service@velbio.example</a> Phone: 044 2434 5678</p></body></html>"""
SERVICES = """<html><body><p>Annual maintenance contracts (AMC) and breakdown service by our 18 service engineers.
Raise a complaint online with our service request form.</p></body></html>"""


def _seed_vel(db) -> ChennaiLead:
    leads.collect(db, "unused", rows=ROWS[:1])
    return db.scalar(select(ChennaiLead))


def test_verify_website_confirms_city_address_operations_and_contacts(db, web):
    web.text("https://velbio.example/", HOME)
    web.text("https://velbio.example/contact-us", CONTACT)
    web.text("https://velbio.example/services", SERVICES)
    lead = _seed_vel(db)
    leads.verify_website(db, lead)
    assert lead.location_verified and lead.location_status == "chennai_city"
    assert lead.location_evidence_url == "https://velbio.example/contact-us"
    assert lead.industry_strength == "strong"
    assert {"amc_warranty", "technicians", "service_request"} <= {o["key"] for o in lead.operations}
    official = [e for e in lead.emails if e["official"]]
    assert official and official[0]["value"] == "service@velbio.example" and official[0]["source_url"].endswith("/contact-us")
    assert lead.activity_status == "active"
    assert lead.category == "B"  # verified + relevant operations, but no confirmed need
    assert "facebook.com" not in " ".join(web.calls)  # off-site links are never followed


def test_verify_website_rejects_gcma_address(db, web):
    web.text("https://velbio.example/", HOME.replace("/contact-us", "/contact"))
    web.text("https://velbio.example/contact", "<p>Office: 4 GST Road, Tambaram, Chennai 600045</p>")
    lead = _seed_vel(db)
    leads.verify_website(db, lead)
    assert lead.location_status == "gcma_outside" and not lead.location_verified
    assert lead.category == "D"


def test_verify_website_failure_keeps_unknowns(db, web):
    web.error("https://velbio.example/", 500)
    lead = _seed_vel(db)
    leads.verify_website(db, lead)
    assert lead.website_check_error and lead.activity_status == "unknown" and not lead.location_verified


FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Vel Biomedical Equipments opens new service centre in Chennai</title>
<description>The Chennai firm inaugurated a new service centre in Guindy to support hospital equipment.</description>
<link>https://news.example/vel</link><pubDate>{d}</pubDate></item>
<item><title>Chennai distributor looking for an order management software partner</title>
<description>A Chennai FMCG distributor is seeking an order management system for its 400 dealers.</description>
<link>https://news.example/anon</link><pubDate>{d}</pubDate></item>
<item><title>Cricket in Chennai</title><description>Match report.</description><link>https://news.example/c</link><pubDate>{d}</pubDate></item>
</channel></rss>"""


def test_news_scan_matches_leads_and_keeps_hypotheses(db, web):
    d = (utcnow() - timedelta(days=3)).strftime("%a, %d %b %Y 10:00:00 +0000")
    web.text("https://feed.example/rss", FEED.format(d=d), content_type="application/rss+xml")
    lead = _seed_vel(db)
    stats = leads.scan_news(db, feeds={"Test": "https://feed.example/rss"})
    assert stats["relevant"] == 2 and stats["matched"] == 1
    db.refresh(lead)
    sig = [s for s in lead.signals if s.signal_type == "new_facility"][0]
    assert sig.review_status == "hypothesis" and sig.published_at is not None and sig.url == "https://news.example/vel"
    market = db.scalars(select(LeadSignal).where(LeadSignal.lead_id.is_(None))).all()
    assert {s.url for s in market} == {"https://news.example/anon"}
    again = leads.scan_news(db, feeds={"Test": "https://feed.example/rss"})
    assert again["new_signals"] == 0


# ================================================================================================
# API: dashboard, A only via confirmed evidence, human approval
# ================================================================================================
def test_api_lead_to_category_a_and_approval(client, db, web):
    web.text("https://velbio.example/", HOME)
    web.text("https://velbio.example/contact-us", CONTACT)
    web.text("https://velbio.example/services", SERVICES)
    lead = _seed_vel(db)
    lid = lead.id
    r = client.post(f"/api/leads/{lid}/verify-website")
    assert r.status_code == 200 and r.json()["category"] == "B"
    assert client.post(f"/api/leads/{lid}/approve-outreach").json()["status"] == "approved"  # B can be approved

    bad = client.post(f"/api/leads/{lid}/signals", json={"signal_type": "explicit_software_request", "url": "not-a-url",
                                                         "excerpt": "They need a field service app now."})
    assert bad.status_code == 422
    r = client.post(f"/api/leads/{lid}/signals", json={
        "signal_type": "explicit_software_request", "url": "https://linkedin.example/post/1",
        "excerpt": "We are looking for a field service management app for our engineers.",
        "published_at": (utcnow() - timedelta(days=4)).isoformat()})
    assert r.status_code == 201 and r.json()["review_status"] == "confirmed"
    detail = client.get(f"/api/leads/{lid}").json()
    assert detail["category"] == "A"
    assert any("linkedin.example/post/1" in x for x in detail["category_reasons"])

    brief = client.get(f"/api/leads/{lid}/brief").json()
    assert brief["qualification_questions"] and "Nothing is sent" in brief["notice"]
    assert all(f["source"] for f in brief["research_brief"] if f["fact"].startswith("Location"))

    # Editing the draft invalidates the approval.
    r = client.patch(f"/api/leads/{lid}", json={"outreach_draft": "Hello, edited."})
    assert r.json()["outreach_approved_by"] is None and r.json()["status"] == "reviewing"
    assert client.post(f"/api/leads/{lid}/mark-contacted").status_code == 422
    client.post(f"/api/leads/{lid}/approve-outreach")
    assert client.post(f"/api/leads/{lid}/mark-contacted").json()["status"] == "contacted"

    s = client.get("/api/leads/summary").json()
    assert s["by_category"]["A"] == 1 and s["verified_location"] == 1

    # Filters
    assert client.get("/api/leads", params={"category": "A"}).json()["total"] == 1
    assert client.get("/api/leads", params={"industry": "wholesale_distribution"}).json()["total"] == 0
    assert client.get("/api/leads", params={"signal_days": 30}).json()["total"] == 1
    assert client.get("/api/leads", params={"official_contact": True}).json()["total"] == 1


def test_api_rejects_c_and_d_approval_and_unsourced_manual_leads(client):
    r = client.post("/api/leads", json={"name": "Sri Ram Distributors", "address": "Sowcarpet, Chennai 600079"})
    assert r.status_code == 422  # no source URL
    r = client.post("/api/leads", json={"name": "Sri Ram Distributors", "address": "Sowcarpet, Chennai 600079",
                                        "source_url": "https://expo.example/exhibitors"})
    assert r.status_code == 201
    body = r.json()
    assert body["category"] == "C" and body["location_verified"] is False
    assert client.post(f"/api/leads/{body['id']}/approve-outreach").status_code == 422
    dup = client.post("/api/leads", json={"name": "Sri Ram Distributors Pvt Ltd", "source_url": "https://expo.example/exhibitors",
                                          "address": "Sowcarpet, Chennai 600079"})
    assert dup.status_code == 422 and "duplicate" in dup.json()["detail"]
    out = client.post("/api/leads", json={"name": "Hosur Elevators", "address": "SIPCOT, Hosur 635126",
                                          "source_url": "https://x.example", "industry": "equipment_sales_service"})
    assert out.json()["category"] == "D"


# ================================================================================================
# Scope: nationwide discovery disabled
# ================================================================================================
@pytest.mark.parametrize("path,body", [
    ("/api/prospects/find", {"areas": ["Mumbai"]}),
    ("/api/prospects/scan-overture", {}),
    ("/api/prospects/scan-map-file", {}),
    ("/api/prospects/check-websites", {}),
    ("/api/multi-branch/find", {}),
    ("/api/big-projects/find", None),
    ("/api/discovery/jobs", {"source_keys": ["hackernews"]}),
])
def test_nationwide_endpoints_refused_in_chennai_scope(chennai_scope, client, path, body):
    r = client.post(path, json=body) if body is not None else client.post(path)
    assert r.status_code == 409
    assert "Chennai-only" in r.json()["detail"]


def test_scheduler_drops_nationwide_jobs_in_chennai_scope(chennai_scope):
    from apscheduler.schedulers.background import BackgroundScheduler

    from app import jobs

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(lambda: None, "interval", minutes=60, id="source:hackernews")
    old = jobs._scheduler
    jobs._scheduler = sched
    try:
        assert jobs.sync_schedule() == []
        assert [j.id for j in sched.get_jobs()] == []
    finally:
        jobs._scheduler = old


def test_lead_endpoints_work_in_chennai_scope(chennai_scope, client):
    s = client.get("/api/leads/summary").json()
    assert s["chennai_only"] is True and s["scope"] == "Chennai city only"


# ================================================================================================
# Reset safety
# ================================================================================================
def _seed_old_data(db):
    hn = db.scalar(select(Source).where(Source.key == "hackernews"))
    pp = db.scalar(select(Source).where(Source.key == "partner_programmes"))
    db.add_all([
        Prospect(name="Mumbai Cafe", segment="small_business", business_type="cafe", type_label="Cafe", source="overture",
                 source_ref="overture:1", source_url="https://explore.overturemaps.org/"),
        Prospect(name="Pune Salon", segment="small_business", business_type="salon", type_label="Salon", source="overture",
                 source_ref="overture:2", source_url="https://explore.overturemaps.org/"),
        Opportunity(title="HN job", pipeline="A_direct", category="direct_software_project", dedupe_key="hn:1", source_id=hn.id),
        Opportunity(title="Partner programme", pipeline="B_vendor", category="implementation_partnership", dedupe_key="pp:1", source_id=pp.id),
        ChennaiLead(name="Keep Me Distributors", normalized_name="keep me distributors", source="manual", source_ref="manual:keep",
                    source_url="https://x.example"),
        ActivityLog(entity_type="x", action="y", actor="owner", detail={}),
    ])
    db.commit()


def test_reset_preview_execute_and_guards(db, tmp_path):
    from app import reset

    _seed_old_data(db)
    with engine.connect() as conn:
        p = reset.preview(conn)
    by_table = {(d["group"], d["table"]): d["rows"] for d in p.delete}
    assert by_table[("nationwide_directory", "prospects")] == 2
    assert by_table[("opportunity_pipeline", "opportunities")] == 1  # partner programme kept
    assert p.kept_opportunities == 1
    assert p.confirm_phrase == f"DELETE {p.total} RECORDS"
    assert db.scalar(select(text("count(*)")).select_from(Prospect)) == 2  # preview deleted nothing

    tables_before = _tables()
    # Guard 1: missing backup.
    with engine.begin() as conn, pytest.raises(reset.ResetRefused, match="Backup not found"):
        reset.execute(conn, backup_path=tmp_path / "nope.db", confirm=p.confirm_phrase)
    manifest = reset.backup(out_dir=tmp_path, export_csv=True)
    assert manifest["integrity"] == "ok" and Path(manifest["csv_exports"]["prospects"]).is_file()
    # Guard 2: wrong confirmation phrase.
    with engine.begin() as conn, pytest.raises(reset.ResetRefused, match="Confirmation does not match"):
        reset.execute(conn, backup_path=Path(manifest["backup"]), confirm="yes")
    # Guard 3: backup older than the data.
    db.rollback()  # end this session's read snapshot before writing (WAL)
    db.add(Prospect(name="New", segment="s", business_type="b", type_label="t", source="o", source_ref="overture:3", source_url="u"))
    db.commit()
    with engine.connect() as conn:
        p2 = reset.preview(conn)
    with engine.begin() as conn, pytest.raises(reset.ResetRefused, match="older than the current data"):
        reset.execute(conn, backup_path=Path(manifest["backup"]), confirm=p2.confirm_phrase)
    assert db.scalar(select(text("count(*)")).select_from(Prospect)) == 3  # nothing deleted by refused runs

    manifest = reset.backup(out_dir=tmp_path / "b2", export_csv=False)
    with engine.begin() as conn:
        out = reset.execute(conn, backup_path=Path(manifest["backup"]), confirm=p2.confirm_phrase)
    assert out["total"] == p2.total
    db.rollback()  # fresh snapshot after the reset committed on another connection
    assert db.scalar(select(text("count(*)")).select_from(Prospect)) == 0
    assert [o.title for o in db.scalars(select(Opportunity))] == ["Partner programme"]
    assert db.scalar(select(ChennaiLead)) is not None  # new Chennai data kept
    assert db.scalar(select(text("count(*)")).select_from(Source)) > 0  # source definitions kept
    assert db.scalar(select(ActivityLog).where(ActivityLog.action == "data_reset")) is not None  # audited
    assert _tables() == tables_before  # no table dropped
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM alembic_version")).scalar() == 1  # migration history intact


def _tables() -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}


def test_reset_preview_api_is_read_only(client, db):
    _seed_old_data(db)
    r = client.get("/api/reset/preview")
    assert r.status_code == 200 and r.json()["total_rows_to_delete"] >= 3
    assert db.scalar(select(text("count(*)")).select_from(Prospect)) == 2


@pytest.mark.parametrize("name,cat,expected", [
    ("Acme Hydraulics", "hydraulic_equipment_supplier", EQUIPMENT),  # equipment dealer, not a wholesaler
    ("Cool Air Services", "hvac_service", EQUIPMENT),
    ("Sri Balaji Metals", "metal_supplier", None),  # raw-material trader
    ("Tamil Chemicals", "chemical_plant", None),  # manufacturing plant
    ("Sound Systems Events", "party_and_event_planning", None),
    ("Kavarai FMCG Distributors", "fmcg_wholesaler", WHOLESALE),
])
def test_directory_category_edge_cases(name, cat, expected):
    assert lead_rules.classify_industry(name, cat).industry == expected
