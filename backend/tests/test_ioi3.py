"""IOI 3.0: ingestion rules, dedupe, evidence states, qualification, scoring, engine jobs, outreach, payments, data safety.

No live network (`web` fixture). Synthetic records are flagged is_test=True where stored.
"""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app import lead_rules
from app.db import utcnow
from app.http_client import SafeHttp
from app.ioi3 import collect, core, engine, qualify, research, sales
from app.ioi3.models import Campaign, Company, Deal, Job, Fact, RawItem
from app.lead_rules import EQUIPMENT, WHOLESALE

NOW = datetime(2026, 11, 23, 12, 0)


def cand(i, name, cat, address, *, phone="+91 98400 00000", website=None, lat=13.04, lon=80.23, brand=None):
    return collect.Candidate(source_key="overture_places", external_id=f"t{i}", source_url=f"https://explore.overturemaps.org/#{i}",
                             name=name, category=cat, address=address, locality="Chennai", phones=[phone] if phone else [],
                             websites=[website] if website else [], lat=lat, lon=lon, brand=brand)


CANDS = [
    cand(1, "Vel Biomedical Equipments", "b2b_hospital_equipment_and_supplies", "12 Usman Road, T Nagar", website="https://velbio.example"),
    cand(2, "Vel Biomedical Equipments", "b2b_hospital_equipment_and_supplies", "12 Usman Road, T Nagar"),  # same phone → duplicate
    cand(3, "Vel Biomedical Equipments", "b2b_hospital_equipment_and_supplies", "Anna Nagar", phone="+91 90000 77777", lat=13.09, lon=80.21),  # same name, elsewhere
    cand(4, "Sakthi Pharma Distributors", "pharmaceutical_products_wholesaler", "Sowcarpet, Chennai 600079", phone="+91 94440 11111"),
    cand(5, "Tambaram Elevators", "elevator_service", "GST Road, Tambaram", phone="+91 90000 22222"),
    cand(6, "Anna Nagar Bakery", "bakery", "Anna Nagar", phone="+91 90000 33333"),
    cand(7, "Big Brand Store", "electronic_equipment_supplier", "Guindy", phone="+91 90000 44444", brand="BigBrand"),
    cand(8, "Hosur Hydraulics", "hydraulic_equipment_supplier", "SIPCOT, Hosur 635126", phone="+91 90000 55555"),
]


@pytest.fixture
def camp(db) -> Campaign:
    core.seed_sources(db)
    return core.active_campaign(db)


# ================================================================================================
# Ingestion: industry, Chennai, duplicates
# ================================================================================================
def test_ingest_rules(db, camp):
    out = {c.external_id: collect.ingest(db, camp, c).outcome for c in CANDS}
    db.commit()
    assert out == {"t1": "accepted", "t2": "duplicate", "t3": "accepted", "t4": "accepted", "t5": "outside_chennai",
                   "t6": "wrong_industry", "t7": "chain_outlet", "t8": "outside_chennai"}
    names = [c.name for c in db.scalars(select(Company).order_by(Company.id))]
    assert names.count("Vel Biomedical Equipments") == 2  # same name in a different place is NOT merged
    # Out-of-scope businesses never become companies, but their provenance is kept.
    assert {r.outcome for r in db.scalars(select(RawItem))} >= {"outside_chennai", "chain_outlet", "duplicate", "accepted"}
    vel = db.scalar(select(Company).where(Company.source_ref == "overture_places:t1"))
    assert vel.location_confidence == "partial"  # directory text is never "verified"
    assert vel.qualification == "P2" and all(c.source_url for c in vel.contacts)
    unknown = [f for f in vel.facts if f.state == "unknown"]
    assert unknown and "software" in unknown[0].statement
    # Re-ingesting is idempotent.
    assert collect.ingest(db, camp, CANDS[0]).outcome == "already_seen"


def test_rank_respects_industry_mix(camp):
    many = [cand(100 + i, f"Equip Co {i} Equipments", "industrial_equipment_manufacturer", "Guindy", phone=f"+91 9{i:09d}") for i in range(20)]
    many += [cand(200 + i, f"Whole Co {i} Distributors", "wholesaler", "Sowcarpet", phone=f"+91 8{i:09d}") for i in range(20)]
    picked = collect.rank_candidates(many, camp, 10)
    kinds = [lead_rules.classify_industry(c.name, c.category).industry for c in picked]
    assert kinds.count(EQUIPMENT) == 7 and kinds.count(WHOLESALE) == 3


def test_csv_import_and_manual(db, camp):
    csv_text = ("name,address,website,phone,source_url,industry\n"
                "Ravi Surgicals,\"Egmore, Chennai 600008\",https://ravi.example,+91 98400 12345,https://expo.example/list,equipment\n"
                "Coimbatore Pumps Distributors,\"Avinashi Road, Coimbatore 641018\",,,https://expo.example/list,\n"
                ",no name,,,https://expo.example/list,\n")
    st = collect.import_csv(db, camp, csv_text)
    assert st["accepted"] == 1 and st["outside_chennai"] == 1 and st["no_name"] == 1
    with pytest.raises(ValueError):
        collect.add_manual(db, camp, {"name": "X Distributors", "source_url": "not a link"})
    r = collect.add_manual(db, camp, {"name": "Karthik Elevator Services", "industry": EQUIPMENT, "address": "Adyar, Chennai 600020",
                                      "source_url": "https://post.example/1", "location_evidence_url": "https://karthik.example/contact"})
    assert r.outcome == "accepted" and r.company.location_confidence == "verified"


# ================================================================================================
# Qualification
# ================================================================================================
def snap(**kw) -> qualify.Snapshot:
    base = dict(name="Vel Biomedical Systems", industry=EQUIPMENT, industry_strength="strong", location_confidence="verified",
                activity="active", official_contacts=2, workflow_keys={"service_ops", "amc_warranty", "technicians"},
                research_level="website", legal_form="small_firm")
    base.update(kw)
    return qualify.Snapshot(**base)


def cat(s):
    return qualify.categorise(s, qualify.gates(s), NOW)[0]


def test_gates_and_categories():
    assert cat(snap()) == "P2"  # gates pass, no trigger, no confirmed need
    trig = qualify.SignalView("new_facility", "hypothesis", NOW - timedelta(days=10), "https://n.example/a")
    assert cat(snap(signals=[trig])) == "P1"
    explicit_unconfirmed = qualify.SignalView("explicit_software_request", "hypothesis", NOW - timedelta(days=3), "https://n.example/b")
    assert cat(snap(signals=[explicit_unconfirmed])) == "P1"  # never P0 without human confirmation
    explicit = qualify.SignalView("explicit_software_request", "confirmed", NOW - timedelta(days=3), "https://n.example/b")
    assert cat(snap(signals=[explicit])) == "P0"
    assert cat(snap(buyer_confirmed_problems=["Service requests tracked in a notebook"])) == "P0"
    old = qualify.SignalView("new_facility", "confirmed", NOW - timedelta(days=400), "https://n.example/c")
    assert cat(snap(signals=[old])) == "P2"
    assert cat(snap(location_confidence="partial", signals=[explicit])) == "P2"  # unverified location blocks P0
    assert cat(snap(location_confidence="outside")) == "P3"
    assert cat(snap(industry=None)) == "P3"
    assert cat(snap(activity="inactive")) == "P3"
    assert cat(snap(disqualifier="Needs GST invoice")) == "P3"
    assert cat(snap(review_status="duplicate")) == "P3"
    g = {x["key"]: x["passed"] for x in qualify.gates(snap(official_contacts=0, directory_contacts=0, activity="unknown"))}
    assert g["contact"] is None and g["active"] is None  # unknown is not a pass


def test_score_is_bounded_and_explained():
    s = snap(signals=[qualify.SignalView("explicit_software_request", "confirmed", NOW - timedelta(days=5), "https://n.example")])
    total, parts = qualify.score(s, 5, NOW)
    assert total == sum(p["points"] for p in parts) and total <= 100
    assert {p["key"]: p["max"] for p in parts} == {"intent": 30, "workflow": 20, "contact": 15, "recency": 10, "feasibility": 10,
                                                   "simplicity": 10, "evidence": 5}
    assert all(p["why"] for p in parts)
    low, _ = qualify.score(snap(official_contacts=0, workflow_keys=set(), industry_strength="candidate", research_level="directory",
                                location_confidence="partial", legal_form=None), None, NOW)
    assert low < total


def test_friction_and_solution():
    assert qualify.friction(snap())[0] == "low"
    assert qualify.friction(snap(legal_form="limited", official_contacts=0, tools={"sap"}))[0] == "high"
    assert qualify.friction(snap(official_contacts=0, directory_contacts=0, legal_form=None))[0] == "unknown"
    assert qualify.recommend(snap())["offer"] == "ServiceFlow Setup"
    assert qualify.recommend(snap(industry=WHOLESALE, workflow_keys={"warehouse"}))["offer"] == "OrderFlow Setup"
    assert qualify.recommend(snap(tools={"tally"}))["offer"] == "Integration Fix"
    one = qualify.recommend(snap(buyer_confirmed_problems=["AMC renewals are missed"]))
    assert one["offer"] == "Small Automation" and one["level"] == 3
    for r in (qualify.recommend(snap()), one):
        assert r["known_workflow"] and r["why"] and r["confirm_with_buyer"]


# ================================================================================================
# Research with evidence states (mock web)
# ================================================================================================
HOME = """<html><body><h1>Vel Biomedical Equipments</h1><a href="/contact-us">Contact</a> <a href="/services">Services</a>
<p>Supply, installation and commissioning of hospital equipment. We use Tally for billing. © 2026</p></body></html>"""
CONTACT = """<html><body><p>Vel Biomedical Equipments, 12 Usman Road, T Nagar, Chennai 600017.</p>
<p>Email: <a href="mailto:service@velbio.example">service@velbio.example</a> Phone: 044 2434 5678</p>
<form action="/send"><input name="q"></form></body></html>"""
SERVICES = """<html><body><p>Annual maintenance contracts (AMC) and breakdown service by our 18 service engineers.
On 2 November 2026 we inaugurated a new service centre in Guindy.</p></body></html>"""


def _mock_site(web):
    web.text("https://velbio.example/", HOME)
    web.text("https://velbio.example/contact-us", CONTACT)
    web.text("https://velbio.example/services", SERVICES)


def test_research_labels_facts(db, camp, web):
    _mock_site(web)
    collect.ingest(db, camp, CANDS[0])
    db.commit()
    c = db.scalar(select(Company))
    research.research_company(db, c, SafeHttp())
    db.commit()
    assert c.location_confidence == "verified" and c.industry_strength == "strong" and c.activity == "active"
    states = {(f.kind, f.state) for f in c.facts}
    assert ("workflow", "source_verified") in states and ("problem", "inferred") in states and ("tools", "unknown") in states
    wf = [f for f in c.facts if f.kind == "workflow"]
    assert all(f.source_url and f.excerpt for f in wf)
    sig = [f for f in c.facts if f.kind == "signal"][0]
    assert sig.review_status == "hypothesis" and sig.published_at == datetime(2026, 11, 2)
    assert any(x.official and x.kind == "email" for x in c.contacts)
    assert any(x.kind == "contact_form" for x in c.contacts)
    assert any(f.kind == "tools" and f.key == "tally" for f in c.facts)
    assert c.solution["offer"] == "Integration Fix"  # works with what they already use
    assert qualify.sales_ready(c.gates)


# ================================================================================================
# Engine: real job lifecycle with mocked sources
# ================================================================================================
@pytest.fixture
def overture(monkeypatch, tmp_path):
    f = tmp_path / "overture-india-test.parquet"
    f.write_bytes(b"x")
    monkeypatch.setattr(collect, "overture_file", lambda: f)
    monkeypatch.setattr(collect, "overture_candidates", lambda path: list(CANDS))
    monkeypatch.setattr(research, "CHENNAI_FEEDS", {})
    return f


def _run(db):
    engine.run_next(lambda: SafeHttp())
    db.expire_all()


def test_job_runs_all_stages_and_shortlists(db, camp, web, overture, monkeypatch):
    _mock_site(web)
    monkeypatch.setattr("app.ioi3.research.CHENNAI_FEEDS", {})
    job = engine.start_job(db, camp, mode="balanced")
    with pytest.raises(engine.JobConflict):
        engine.start_job(db, camp)  # no duplicate simultaneous jobs
    _run(db)
    db.rollback()
    job = db.get(Job, job.id)
    assert job.status == "completed", job.log
    assert job.stage == "shortlist" and job.stage_index == 6
    assert job.counters["accepted"] == 3 and job.counters["processed"] == 4  # out-of-scope listings filtered before ingesting
    assert job.counters["rejected_outside_total"] == 2 and job.counters["chain_outlets_total"] == 1
    assert job.sources["overture_places"]["status"] == "done" and job.sources["official_websites"]["status"] == "done"
    vel = db.scalar(select(Company).where(Company.source_ref == "overture_places:t1"))
    assert vel.review_status == "shortlisted"  # passed every gate
    assert core.source(db, "overture_places").health == "working"
    # A second run finds nothing new from the same file (idempotent) and completes.
    engine.start_job(db, camp, mode="quick")
    _run(db)
    db.rollback()
    assert db.scalar(select(Job).order_by(Job.id.desc())).counters.get("accepted", 0) == 0
    assert db.scalar(select(text("count(*)")).select_from(Company)) == 3


def test_job_cancel_recover_retry(db, camp, overture):
    job = engine.start_job(db, camp, mode="quick")
    engine.request_stop(db, job)
    assert job.status == "stopped"  # stopped before it started; never auto-restarted
    assert engine.run_next() is False
    j2 = engine.start_job(db, camp, mode="quick")
    j2.status = "running"
    db.commit()
    assert engine.recover(db) == 1
    db.refresh(j2)
    assert j2.status == "interrupted" and "Retry" in j2.error
    assert engine.active_job(db, camp.id) is None


def test_missing_source_is_reported_not_faked(db, camp, monkeypatch):
    monkeypatch.setattr(collect, "overture_file", lambda: None)
    camp.settings = {**core.campaign_settings(camp), "sources": {"overture_places": True, "official_websites": False, "news_rss": False}}
    db.commit()
    with pytest.raises(engine.ConfigError):
        engine.start_job(db, camp)


# ================================================================================================
# Outreach, pipeline, payments
# ================================================================================================
def _ready_company(db, camp, web) -> Company:
    _mock_site(web)
    collect.ingest(db, camp, CANDS[0])
    db.commit()
    c = db.scalar(select(Company).where(Company.source_ref == "overture_places:t1"))
    research.research_company(db, c, SafeHttp())
    db.commit()
    return c


def test_approval_guard_and_sales_flow(db, camp, web):
    collect.ingest(db, camp, CANDS[3])  # directory-only distributor: gates not passed
    db.commit()
    weak = db.scalar(select(Company))
    with pytest.raises(sales.SalesError, match="still needs"):
        sales.approve(db, weak, "owner")
    with pytest.raises(sales.SalesError):
        sales.mark_contacted(db, weak, "owner", "phone", None)

    c = _ready_company(db, camp, web)
    sales.approve(db, c, "owner")
    assert c.review_status == "approved" and "Udyam" in c.outreach_draft and "reply 'no'" in c.outreach_draft
    sales.edit_draft(db, c, "Hello, edited message here.", "owner")
    assert c.review_status == "shortlisted" and c.outreach_approved_by is None  # edit resets approval
    sales.approve(db, c, "owner")
    sales.mark_contacted(db, c, "owner", "phone", "Spoke to reception")
    sales.record_reply(db, c, "owner", "Service manager called back", True, buyer_problem="Technician visits are tracked on paper")
    db.commit()
    assert c.qualification == "P0" and c.buying_intent == "buyer_confirmed"
    d = db.scalar(select(Deal))
    assert d.stage == "replied"
    with pytest.raises(sales.SalesError, match="quoted amount"):
        sales.move(db, d, "advance_received", "owner")
    sales.add_proposal(db, d, title="ServiceFlow Setup", scope="Pilot", amount=40000, sent=True, actor="owner")
    assert d.stage == "proposal_sent" and d.quoted_amount == 40000
    with pytest.raises(sales.SalesError):
        sales.add_payment(db, d, amount=1000, kind="advance", received_on=date.today() + timedelta(days=2), reference=None, note=None, actor="o")
    sales.add_payment(db, d, amount=15000, kind="advance", received_on=date.today(), reference="UPI 123", note=None, actor="owner")
    db.commit()
    assert d.stage == "advance_received"
    with pytest.raises(sales.SalesError, match="outstanding"):
        sales.move(db, d, "payment_collected", "owner")
    rev = sales.revenue(db, camp.id)
    assert rev == {"potential": 0, "quoted": 40000, "contracted": 40000, "advances_received": 15000, "outstanding": 25000,
                   "collected_total": 15000, "collected_this_month": 15000}
    sales.add_payment(db, d, amount=25000, kind="final", received_on=date.today(), reference=None, note=None, actor="owner")
    sales.move(db, d, "payment_collected", "owner")
    db.commit()
    assert sales.revenue(db, camp.id)["outstanding"] == 0 and sales.revenue(db, camp.id)["collected_this_month"] == 40000


def test_potential_is_never_revenue(db, camp, web):
    c = _ready_company(db, camp, web)
    sales.approve(db, c, "owner")
    d = sales.ensure_deal(db, c)
    d.potential_amount = 90000
    db.commit()
    r = sales.revenue(db, camp.id)
    assert r["potential"] == 90000 and r["collected_this_month"] == 0 and r["quoted"] == 0


# ================================================================================================
# API (end-to-end through HTTP)
# ================================================================================================
def test_api_end_to_end(client, db, web, overture):
    _mock_site(web)
    st = client.get("/api/v3/status").json()
    assert st["onboarding_done"] is False and st["preflight"]["can_start"]
    assert client.post("/api/v3/onboarding/complete").json()["ok"]
    assert client.get("/api/v3/home").json()["stats"] == {"qualified": 0, "new_signals": 0, "follow_ups_due": 0, "collected_this_month": 0}

    r = client.post("/api/v3/jobs", json={"mode": "balanced", "max_candidates": 20})
    assert r.status_code == 202
    assert client.post("/api/v3/jobs", json={}).status_code == 409
    engine.run_next(lambda: SafeHttp())
    j = client.get(f"/api/v3/jobs/{r.json()['id']}").json()
    assert j["status"] == "completed" and [s["label"] for s in j["stages"]][0] == "Finding businesses"

    ready = client.get("/api/v3/companies", params={"tab": "ready"}).json()
    assert ready["total"] == 1
    cid = ready["items"][0]["id"]
    d = client.get(f"/api/v3/companies/{cid}").json()
    assert {f["state"] for f in d["facts"]} >= {"source_verified", "inferred", "unknown"}
    assert d["solution"]["offer"] and d["outreach"]["questions"]
    sig = [f for f in d["facts"] if f["kind"] == "signal"][0]
    assert client.post(f"/api/v3/facts/{sig['id']}/review", json={"decision": "confirmed"}).status_code == 200

    assert client.post(f"/api/v3/companies/{cid}/approve", json={}).json()["review_status"] == "approved"
    out = client.get("/api/v3/outreach").json()
    assert out[0]["id"] == cid and out[0]["outreach"]["message"]
    assert client.post(f"/api/v3/companies/{cid}/contacted", json={"channel": "phone", "follow_up_days": 2}).status_code == 200
    assert client.post(f"/api/v3/companies/{cid}/reply", json={"summary": "Interested, call Monday", "interested": True}).status_code == 200
    deal = client.get("/api/v3/pipeline").json()["deals"][0]
    assert deal["stage"] == "replied"
    r = client.post(f"/api/v3/deals/{deal['id']}/proposals", json={"title": "ServiceFlow pilot", "amount": 30000})
    assert r.json()["stage"] == "proposal_sent"
    r = client.post(f"/api/v3/deals/{deal['id']}/payments", json={"amount": 30000, "kind": "advance", "received_on": str(date.today())})
    assert r.status_code == 201 and r.json()["collected"] == 30000
    home = client.get("/api/v3/home").json()
    assert home["stats"]["collected_this_month"] == 30000 and home["revenue"]["outstanding"] == 0

    bad = client.post(f"/api/v3/deals/{deal['id']}/stage", json={"stage": "nonsense"})
    assert bad.status_code == 422
    # Exports and archive
    assert "Vel Biomedical" in client.get("/api/v3/export/companies.csv").text
    assert "prospects" in client.get("/api/v3/legacy").json()["tables"]


def test_api_settings_validation_and_campaign_reset(client):
    assert client.put("/api/v3/settings", json={"discovery": {"depth": "extreme"}}).status_code == 422
    assert client.put("/api/v3/settings", json={"discovery": {"max_candidates": 0}}).status_code == 422
    r = client.put("/api/v3/settings", json={"discovery": {"max_candidates": 30, "approved_localities": [" Tambaram "]},
                                             "business": {"revenue_goal_monthly": 30000, "sender_name": "Kartheek"}})
    assert r.json()["discovery"]["max_candidates"] == 30 and r.json()["discovery"]["approved_localities"] == ["tambaram"]
    assert set(r.json()["ai"]) == {"configured", "provider", "model", "how_to_configure"}  # no secret values returned
    client.post("/api/v3/companies", json={"name": "Karthik Elevator Services", "industry": EQUIPMENT, "address": "Adyar, Chennai 600020",
                                           "source_url": "https://post.example/1"})
    assert client.post("/api/v3/campaign/reset", json={"confirm": "yes"}).status_code == 422
    assert client.post("/api/v3/campaign/reset", json={"confirm": "START NEW CAMPAIGN"}).json()["ok"]
    assert client.get("/api/v3/companies", params={"tab": "all"}).json()["total"] == 0
    from app.db import SessionLocal

    with SessionLocal() as s:  # archived, not deleted
        assert s.scalar(select(text("count(*)")).select_from(Company).where(Company.archived.is_(True))) == 1


def test_api_manual_add_rejections(client):
    r = client.post("/api/v3/companies", json={"name": "Bengaluru Pumps Distributors", "address": "Peenya, Bengaluru 560058",
                                               "source_url": "https://x.example"})
    assert r.status_code == 422 and "Bengaluru" in r.json()["detail"]
    r = client.post("/api/v3/companies", json={"name": "Ganesh Bakery", "address": "Adyar, Chennai", "source_url": "https://x.example"})
    assert r.status_code == 422 and "not an equipment" in r.json()["detail"]


def test_legacy_discovery_is_off(chennai_scope, client):
    assert client.post("/api/leads/collect", json={}).status_code == 409
    assert client.post("/api/prospects/find", json={"areas": ["Mumbai"]}).status_code == 409


@pytest.mark.parametrize("name,cat", [
    ("Dr.BalaMurugan, Laparoscopic Cancer Surgeon", "oncology"),
    ("Dr Rengan's Gastro and Onco Surgical Centre", "surgery_center"),
    ("Sunrise Children's Clinic", None),
])
def test_medical_practices_are_not_equipment_businesses(name, cat):
    assert lead_rules.classify_industry(name, cat).industry is None


def test_dated_content_counts_as_activity_and_owner_can_confirm(db, camp, web, client):
    web.text("https://velbio.example/", HOME.replace("© 2026", "").replace("<a href=\"/services\">Services</a>",
             "<a href=\"/news\">News</a>"))
    web.text("https://velbio.example/contact-us", CONTACT)
    web.text("https://velbio.example/news", "<p>Posted 2 September 2026: our AMC team now covers Guindy.</p>")
    collect.ingest(db, camp, CANDS[0])
    db.commit()
    c = db.scalar(select(Company).where(Company.source_ref == "overture_places:t1"))
    research.research_company(db, c, SafeHttp())
    db.commit()
    assert c.activity == "active" and any(f.key == "dated_content" for f in c.facts)
    # Owner confirmation path
    c.activity = "likely_active"
    db.commit()
    r = client.patch(f"/api/v3/companies/{c.id}", json={"activity_evidence": "Called on 23 Nov, they answered"})
    assert r.json()["activity"] == "active"
    assert any(f["key"] == "owner_confirmed" and f["detected_by"] == "owner" for f in r.json()["facts"])


def test_research_effort_follows_industry_mix(db, camp, overture, monkeypatch):
    many = [cand(300 + i, f"Equip Co {i} Equipments", "industrial_equipment_manufacturer", "Guindy", phone=f"+91 97{i:08d}",
                 website=f"https://eq{i}.example") for i in range(10)]
    many += [cand(400 + i, f"Whole Co {i} Distributors", "wholesaler", "Sowcarpet", phone=f"+91 96{i:08d}",
                  website=f"https://wh{i}.example") for i in range(10)]
    monkeypatch.setattr(collect, "overture_candidates", lambda path: many)
    seen: list[str] = []
    monkeypatch.setattr(research, "research_company", lambda db, c, http, deep=False, ai_calls_left=0: seen.append(c.industry) or 0)
    engine.start_job(db, camp, mode="balanced", overrides={"max_candidates": 20, "max_deep": 10})
    engine.run_next(lambda: SafeHttp())
    assert seen.count(EQUIPMENT) == 7 and seen.count(WHOLESALE) == 3


def test_failed_websites_are_not_retried_automatically(db, camp, web, overture):
    web.error("https://velbio.example/", 403)
    engine.start_job(db, camp, mode="balanced")
    engine.run_next(lambda: SafeHttp())
    calls_after_first = len([u for u in web.calls if "velbio.example/" in u and "robots" not in u])
    assert calls_after_first == 1
    db.rollback()
    engine.start_job(db, camp, mode="balanced")
    engine.run_next(lambda: SafeHttp())
    assert len([u for u in web.calls if "velbio.example/" in u and "robots" not in u]) == calls_after_first
