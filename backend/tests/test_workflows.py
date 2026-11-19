"""Documents, research, relationships provenance, outreach approval, AI fallback, migrations, E2E."""

import io
import json

import httpx
import pytest
from sqlalchemy import create_engine, inspect, select

from app.models import (
    Contact,
    EligibilityRequirement,
    FollowUpTask,
    Opportunity,
    Organisation,
    OrganisationRelationship,
    OutreachApproval,
    ResearchTask,
)
from tests.conftest import alembic_config, install_hn

# --- documents --------------------------------------------------------------------------------


def make_pdf(pages: list[str]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_font("Helvetica", size=10)
    for text in pages:
        pdf.add_page()
        if text:
            pdf.multi_cell(0, 5, text)
    return bytes(pdf.output())


TENDER_P1 = (
    "Name of Work: Development of Inventory Management Software with API integration\n"
    "Organisation: Tamil Nadu Industrial Development Board, Chennai\n"
    "Published Date: 01-11-2026\n"
    "Bid Submission End Date: 30-12-2026\n"
    "Scope of Work: Design and develop a web application with REST API integration and workflow automation.\n"
    "Estimated Cost: Rs 12,00,000\n"
)
TENDER_P2 = (
    "Eligibility Criteria.\n"
    "The bidder shall have an average annual turnover of Rs 50 lakhs in the last three financial years.\n"
    "The bidder must have a valid GST registration.\n"
    "EMD: Rs 24,000. MSEs registered under Udyam are exempted from EMD.\n"
    "Consortium bids are not permitted.\n"
    "Sub-contracting is not permitted.\n"
)


def test_tender_pdf_import_extracts_fields_with_page_refs(client, db):
    pdf = make_pdf([TENDER_P1, TENDER_P2])
    r = client.post("/api/imports/document", files={"file": ("tender.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    doc = body["document"]
    assert not doc["needs_manual_review"] and doc["pages"] == 2
    assert doc["fields"]["tender_title"]["page_reference"] == "p.1"
    assert "Inventory Management" in doc["fields"]["tender_title"]["value"]
    assert doc["fields"]["emd"]["value"].startswith("Rs 24,000")
    assert doc["fields"]["insurance"] if "insurance" in doc["fields"] else True
    assert doc["fields"]["contact_information"] is None  # missing clauses are not fabricated

    opp = db.get(Opportunity, body["opportunity_id"])
    assert opp.category == "government_tender" and opp.deadline is not None and opp.deadline.year == 2026
    reqs = {r.requirement_key: r for r in db.scalars(select(EligibilityRequirement).where(EligibilityRequirement.opportunity_id == opp.id))}
    assert reqs["min_turnover"].page_reference == "p.2" and reqs["min_turnover"].parameters["amount_inr"] == 5_000_000
    assert reqs["gst"].page_reference == "p.2"
    # GST + turnover fail; subcontracting and consortium prohibited → no partner route.
    assert opp.eligibility_outcome == "not_eligible"
    elig = client.get(f"/api/opportunities/{opp.id}/eligibility").json()["project"]
    assert {f["key"] for f in elig["mandatory_failures"]} >= {"gst", "min_turnover"}
    assert elig["next_action"] and elig["clarifications"]
    scores = client.get(f"/api/opportunities/{opp.id}/scores").json()
    assert all(s["disqualified"] and s["effective_total"] == 0 for s in scores)


def test_scanned_pdf_flagged_for_manual_review(client, db):
    pdf = make_pdf(["", ""])
    r = client.post("/api/imports/document", files={"file": ("scan.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["document"]["needs_manual_review"] is True
    opp = db.get(Opportunity, r.json()["opportunity_id"])
    assert opp.needs_manual_review and opp.status == "needs_manual_review"


def test_docx_import(client):
    import docx

    d = docx.Document()
    for line in (TENDER_P1 + TENDER_P2).splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    r = client.post("/api/imports/document", files={"file": ("rfp.docx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    assert r.json()["document"]["fields"]["tender_title"]["page_reference"].startswith("para.")


def test_unsupported_file_rejected(client):
    r = client.post("/api/imports/document", files={"file": ("x.exe", b"MZ....", "application/octet-stream")})
    assert r.status_code == 400


# --- research & contacts ----------------------------------------------------------------------

HOME = """<html><head><title>Acme Logistics — Warehousing</title><meta name="description" content="Acme Logistics runs warehouses in Chennai."></head>
<body><main><h1>Acme Logistics</h1><p>We are an official Zoho partner. Clients include Big Retail.</p>
<a href="/contact-us">Contact</a> <a href="/suppliers">Become a supplier</a> <a href="https://elsewhere.example/contact">Other</a></main></body></html>"""
CONTACT = """<html><body><main>Email: sales@acmelogistics.example, careers@gmail.com. Phone: +91 44 2345 6789.
<a href="mailto:ops@acmelogistics.example">Ops</a></main></body></html>"""
SUPPLIERS = "<html><body><main>Register as a vendor: apply to become a supplier via our vendor portal.</main></body></html>"


def _seed_acme(db, web, client):
    install_hn(web)
    r = client.post("/api/discovery/jobs?wait=true", json={"source_keys": ["hackernews"], "query_terms": []})
    assert r.status_code == 202 and r.json()["status"] == "success", r.json()
    db.rollback()  # end any open read transaction so API commits are visible (SQLite WAL snapshot)
    return db.scalar(select(Opportunity).where(Opportunity.title.like("%Acme Logistics%")))


def test_research_records_only_published_contacts(client, db, web):
    opp = _seed_acme(db, web, client)
    web.text("https://acmelogistics.example", HOME)
    web.text("https://acmelogistics.example/contact-us", CONTACT)
    web.text("https://acmelogistics.example/suppliers", SUPPLIERS)
    r = client.post(f"/api/opportunities/{opp.id}/research")
    assert r.status_code == 200 and r.json()["status"] == "done", r.json()
    task = r.json()
    assert task["requests_used"] <= task["request_budget"]
    db.rollback()
    org = db.get(Organisation, opp.organisation_id)
    assert org.domain_verified and org.accepts_external_vendors is True
    contacts = db.scalars(select(Contact).where(Contact.organisation_id == org.id, Contact.verified.is_(True))).all()
    values = {c.value for c in contacts}
    assert "sales@acmelogistics.example" in values and "ops@acmelogistics.example" in values
    assert "careers@gmail.com" not in values  # personal webmail not stored
    assert not any(v.startswith(("info@", "contact@")) for v in values)  # nothing guessed
    assert all(c.source_url.startswith("https://acmelogistics.example") and c.verification_date for c in contacts)
    assert any(c.contact_type == "vendor_onboarding_page" for c in contacts)
    rels = db.scalars(select(OrganisationRelationship).where(OrganisationRelationship.source_org_id == org.id)).all()
    assert rels and all(r.verification_status == "hypothesis" and r.evidence_url and r.evidence_excerpt for r in rels)
    # Unchanged inputs → research is not repeated.
    calls = len(web.calls)
    r2 = client.post(f"/api/opportunities/{opp.id}/research")
    assert r2.json()["id"] == task["id"] and len(web.calls) == calls


def test_research_budget_limits_requests(client, db, web):
    opp = _seed_acme(db, web, client)
    web.text("https://acmelogistics.example", HOME)
    from app.research import research_opportunity

    t = research_opportunity(db, db.get(Opportunity, opp.id), request_budget=2, force=True)
    assert t.requests_used <= 2
    assert any("budget" in s for s in t.findings["steps"])


def test_research_batch_shortlists(client, db, web):
    _seed_acme(db, web, client)
    r = client.post("/api/research/batch?wait=true")
    assert r.status_code == 200
    body = r.json()
    assert body["shortlisted"] >= 1
    db.rollback()
    assert db.scalar(select(ResearchTask).limit(1)) is not None


# --- relationships provenance -----------------------------------------------------------------


def test_relationship_requires_evidence(client, db):
    org = Organisation(name="Acme", normalized_name="acme")
    db.add(org)
    db.commit()
    base = {"source_org_id": org.id, "target_label": "Zoho", "relationship_type": "partner_programme", "confidence": 0.9}
    assert client.post("/api/relationships/organisations", json=base).status_code == 422  # no evidence
    assert client.post("/api/relationships/organisations", json={**base, "evidence_url": "not-a-url", "evidence_excerpt": "Acme is a Zoho partner"}).status_code == 422
    ok = client.post("/api/relationships/organisations", json={**base, "evidence_url": "https://acme.example/partners", "evidence_excerpt": "Acme is an official Zoho partner."})
    assert ok.status_code == 201 and ok.json()["verification_status"] == "hypothesis"
    rid = ok.json()["id"]
    assert client.patch(f"/api/relationships/organisations/{rid}", json={"verification_status": "confirmed"}).json()["verified_at"]
    graph = client.get("/api/chains").json()
    assert graph["edges"][0]["evidence_url"] == "https://acme.example/partners"
    assert "guaranteed" in graph["note"]


def test_confirmed_relationship_raises_chain_score(client, db, web):
    opp = _seed_acme(db, web, client)
    before = {s["score_type"]: s for s in client.get(f"/api/opportunities/{opp.id}/scores").json()}["chain_potential"]["raw_total"]
    rel = client.post("/api/relationships/organisations", json={
        "source_org_id": opp.organisation_id, "target_label": "Zoho", "relationship_type": "partner_programme",
        "evidence_url": "https://acmelogistics.example/partners", "evidence_excerpt": "We are an official Zoho partner.", "confidence": 0.8}).json()
    mid = {s["score_type"]: s for s in client.get(f"/api/opportunities/{opp.id}/scores").json()}["chain_potential"]["raw_total"]
    assert mid == before  # hypothesis does not score
    client.patch(f"/api/relationships/organisations/{rel['id']}", json={"verification_status": "confirmed"})
    after = {s["score_type"]: s for s in client.get(f"/api/opportunities/{opp.id}/scores").json()}["chain_potential"]["raw_total"]
    assert after == before + 30


# --- outreach approval ------------------------------------------------------------------------


def test_outreach_requires_human_approval(client, db, web):
    opp = _seed_acme(db, web, client)
    d = client.post(f"/api/opportunities/{opp.id}/outreach-drafts").json()
    assert d["status"] == "draft" and d["generated_by"] == "template"
    assert "Udyam" in d["email_body"] and "years of experience" not in d["email_body"]
    did = d["id"]
    # Cannot send, call or approve straight from draft.
    assert client.post(f"/api/outreach/drafts/{did}/mark-sent").status_code == 409
    assert client.post("/api/call-tasks", json={"opportunity_id": opp.id}).status_code == 409
    assert client.post(f"/api/outreach/drafts/{did}/decision", json={"decision": "approved", "decided_by": "owner"}).status_code == 409
    assert client.post(f"/api/outreach/drafts/{did}/submit").json()["status"] == "pending_approval"
    assert client.post(f"/api/outreach/drafts/{did}/decision", json={"decision": "approved", "decided_by": ""}).status_code == 422
    assert client.post(f"/api/outreach/drafts/{did}/decision", json={"decision": "approved", "decided_by": "Owner"}).status_code == 200
    # Editing an approved draft invalidates approval.
    assert client.patch(f"/api/outreach/drafts/{did}", json={"email_subject": "Changed"}).json()["status"] == "draft"
    assert client.post(f"/api/outreach/drafts/{did}/mark-sent").status_code == 409
    client.post(f"/api/outreach/drafts/{did}/submit")
    client.post(f"/api/outreach/drafts/{did}/decision", json={"decision": "approved", "decided_by": "Owner", "note": "ok"})
    db.rollback()
    assert db.scalar(select(OutreachApproval).where(OutreachApproval.draft_id == did, OutreachApproval.decided_by == "Owner")) is not None
    assert client.post(f"/api/outreach/drafts/{did}/mark-sent").json()["status"] == "sent_manually"
    # Call task now allowed; outcomes create follow-ups.
    call = client.post("/api/call-tasks", json={"opportunity_id": opp.id}).json()
    fu = client.post(f"/api/call-tasks/{call['id']}/outcome", json={"outcome": "wants_proposal", "notes": "Send by Friday"}).json()
    assert "proposal" in fu["action"].lower()
    db.rollback()
    assert client.post(f"/api/call-tasks/{call['id']}/outcome", json={"outcome": "bogus"}).status_code == 422
    assert db.scalar(select(FollowUpTask).where(FollowUpTask.opportunity_id == opp.id)) is not None


@pytest.mark.parametrize("outcome", ["interested", "not_interested", "call_back", "wrong_contact", "existing_vendor",
                                     "wants_company_profile", "wants_proposal", "shared_vendor_details", "no_answer"])
def test_every_call_outcome_supported(outcome):
    from app.outreach import FOLLOW_UP_RULES

    assert outcome in FOLLOW_UP_RULES


def test_not_eligible_blocks_drafting(client, db, web):
    _seed_acme(db, web, client)
    us = db.scalar(select(Opportunity).where(Opportunity.title.like("%Stateside%")))
    assert client.post(f"/api/opportunities/{us.id}/outreach-drafts").status_code == 409


# --- optional AI ------------------------------------------------------------------------------


def test_ai_disabled_by_default(db):
    from app.ai.openrouter import get_ai

    assert get_ai(db) is None


def _ai_client(content: str, status: int = 200):
    def handler(req):
        assert req.headers["Authorization"] == "Bearer test-key"
        body = json.loads(req.content)
        assert "<data>" in body["messages"][1]["content"]
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ai_structured_output_validated_and_fallback(db, monkeypatch):
    from app.ai.openrouter import AISummary, AIUnavailable, OpenRouterClient
    from app.config import get_settings
    from app.models import AIUsageLog

    s = get_settings()
    monkeypatch.setattr(s, "openrouter_api_key", "test-key")
    monkeypatch.setattr(s, "openrouter_model", "some/model")
    monkeypatch.setattr(s, "openrouter_max_retries", 0)
    ok = OpenRouterClient(db, _ai_client('{"summary": "A tender.", "key_points": ["x"]}')).complete_json("t", "i", "data", AISummary)
    assert ok.summary == "A tender."
    with pytest.raises(AIUnavailable):
        OpenRouterClient(db, _ai_client("not json at all")).complete_json("t", "i", "data", AISummary)
    with pytest.raises(AIUnavailable):
        OpenRouterClient(db, _ai_client("{}", status=401)).complete_json("t", "i", "data", AISummary)
    logs = db.scalars(select(AIUsageLog)).all()
    assert [log.success for log in logs] == [True, False, False] and logs[0].prompt_tokens == 10


# --- migrations -------------------------------------------------------------------------------


def test_migrations_upgrade_downgrade_and_match_models(tmp_path):
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import Base

    url = f"sqlite:///{tmp_path}/m.db"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    tables = set(inspect(eng).get_table_names())
    assert {"opportunities", "organisations", "sources", "evidence", "outreach_approvals", "organisation_relationships"} <= tables
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []
    command.downgrade(cfg, "base")
    assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    eng.dispose()


# --- end-to-end -------------------------------------------------------------------------------


def test_end_to_end_public_source_to_human_review(client, db, web):
    """Public source → ingestion → database → classification → eligibility → scoring → dashboard → human review."""
    install_hn(web)
    job = client.post("/api/discovery/jobs?wait=true", json={"source_keys": ["hackernews"], "query_terms": []}).json()
    assert job["status"] == "success" and job["stats"]["new"] == 3

    page = client.get("/api/opportunities?sort=priority").json()
    assert page["total"] == 3
    top = page["items"][0]
    assert top["eligibility_outcome"] != "not_eligible" and top["priority"] > 0
    assert {s["score_type"] for s in top["scores"]} == {"direct_client", "vendor_subcontracting", "chain_potential"}
    for s in top["scores"]:
        assert s["explanation"] and all({"name", "max", "value", "known", "explanation"} <= c.keys() for c in s["components"])

    detail_ev = client.get(f"/api/opportunities/{top['id']}/evidence").json()
    assert detail_ev and detail_ev[0]["url"].startswith("https://news.ycombinator.com/item?id=")

    assert client.get("/api/opportunities?country=India").json()["total"] == 1
    assert client.get("/api/opportunities?country=unknown").json()["total"] >= 1
    assert client.get("/api/opportunities?eligibility=not_eligible").json()["total"] == 1
    assert client.get("/api/opportunities?pipeline=A_direct").json()["total"] >= 1

    dash = client.get("/api/dashboard/summary").json()
    assert dash["totals"]["opportunities"] == 3 and dash["totals"]["demo_opportunities"] == 0
    assert dash["recent_runs"][0]["status"] == "success"

    # Human review: shortlist then reject one.
    assert client.patch(f"/api/opportunities/{top['id']}", json={"status": "qualified"}).json()["status"] == "qualified"
    acts = client.get("/api/activity?entity_type=opportunity").json()
    assert any(a["action"] == "updated" for a in acts["items"])
    assert client.get("/openapi.json").status_code == 200


# --- settings ---------------------------------------------------------------------------------


def test_settings_validation_and_profile_override(client, db):
    assert client.put("/api/settings", json={"profile_overrides": {"gst_registered": "maybe"}}).status_code == 422
    assert client.put("/api/settings", json={"profile_overrides": {"revenue_claim": 1}}).status_code == 422
    assert client.put("/api/settings", json={"research_budget": {"shortlist_target": "lots"}}).status_code == 422
    assert client.put("/api/settings", json={"country_priorities": [{"match": "India"}]}).status_code == 422
    # Services cannot be changed through overrides.
    r = client.put("/api/settings", json={"profile_overrides": {"gst_registered": True, "services": ["Blockchain"]}})
    assert r.status_code == 200 and r.json()["profile_overrides"] == {"gst_registered": True}
    prof = client.get("/api/profile").json()["profile"]
    assert prof["gst_registered"] is True and "Blockchain" not in prof["services"]


# --- owner action checklist ---------------------------------------------------------------------


def test_action_checklist(client):
    items = client.get("/api/actions").json()
    assert any("GST" in a["title"] for a in items) and all(a["status"] == "open" for a in items)
    first = items[0]["id"]
    assert client.patch(f"/api/actions/{first}", json={"status": "done"}).json()["completed_at"]
    assert first not in {a["id"] for a in client.get("/api/actions").json()}
    assert first in {a["id"] for a in client.get("/api/actions?status=done").json()}
    new = client.post("/api/actions", json={"title": "Call Kaveri Textiles", "url": "/opportunities/1"})
    assert new.status_code == 201
    assert client.post("/api/actions", json={"title": "bad", "url": "javascript:alert(1)"}).status_code == 422
    assert client.delete(f"/api/actions/{new.json()['id']}").status_code == 204
    # Seeding happens once: restarting must not recreate completed items.
    from app.actions import seed_default_actions
    from app.db import SessionLocal

    with SessionLocal() as db:
        assert seed_default_actions(db) == 0


def test_spa_fallback_does_not_shadow_api(client):
    assert client.get("/api/does-not-exist").status_code == 404
    page = client.get("/opportunities")
    from pathlib import Path

    if (Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html").is_file():
        assert page.status_code == 200 and "<div id=\"root\">" in page.text
