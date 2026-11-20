"""GeM public bid connector (mocked) and AI extraction verification (fake AI client)."""

import json
from urllib.parse import parse_qs

import httpx
from sqlalchemy import func, select

from app import documents
from app.ai.extraction import (
    AIBudget,
    AIClassificationRefinement,
    AIDocumentFields,
    AIRequirementClauses,
    ai_document_fields,
    ai_refine_classification,
    ai_requirement_clauses,
    should_refine,
)
from app.classification import classify
from app.connectors.gem import DATA_URL, LIST_URL, clean_gem_page, is_relevant, parse_gem_fields
from app.enums import Category, RunStatus
from app.models import Contact, EligibilityRequirement, Opportunity, Source
from app.pipeline import run_source

LIST_HTML = "<html><script>var x = {'csrf_bd_gem_nk': 'abc123def'};</script></html>"


def _doc(b_id, number, cat, bid_type=1):
    return {
        "id": str(b_id), "b_id": [b_id], "b_bid_number": [number], "b_category_name": [cat], "bd_category_name": [cat],
        "b_bid_type": [bid_type], "final_start_date_sort": ["2026-11-20T10:00:00Z"], "final_end_date_sort": ["2026-12-11T13:00:00Z"],
        "ba_official_details_minName": ["Ministry Of Education"], "ba_official_details_deptName": ["Department Of Higher Education"],
    }


SEARCH_DOCS = [
    _doc(501, "GEM/2026/B/1000501", "Custom Software Development Service - Web Portal"),
    _doc(502, "GEM/2026/R/1000502", "Website Design and Development Service", bid_type=2),  # reverse auction
    _doc(503, "GEM/2026/B/1000503", "Operating System Software (V3)"),  # licence purchase
]

# Bilingual page text as pypdf returns it (Hindi lines duplicated, English labels prefixed with '/').
PDF_PAGE_1 = """बड ववरण
/Bid End Date/Time
11-12-2026 13:00:00
/Ministry/State Name
Ministry Of Education
वभाग
/Department Name
Department Of Higher Education
/Organisation Name
Indian Institute Of Technology (iit)
/Office Name
North Zone Roorkee
Buyer Email id: buyer501@gembuyer.in
/Item Category
Custom Software Development Service - Web Portal
GeMARPTS
/Minimum Average Annual Turnover of the bidder (For 3 Years)
10 Lakh (s)
/Years of Past Experience Required for same/similar service
3 Year (s)
MSE Relaxation for
Years Of Experience
and
Turnover
Yes
"""
PDF_PAGE_2 = """/EMD Detail
/Required
No
/Type of Bid
Two Packet Bid
If the bidder is a Micro or Small Enterprise the bidder shall be relaxed from the eligibility criteria of "Bidder Turnover".
"""


def install_gem(web, monkeypatch, docs=SEARCH_DOCS):
    posted = []
    web.text(LIST_URL, LIST_HTML)

    def search(req: httpx.Request):
        form = parse_qs(req.content.decode())
        posted.append(form)
        payload = json.loads(form["payload"][0])
        page_docs = docs if payload.get("page", 1) == 1 else []
        return httpx.Response(200, json={"code": 200, "response": {"response": {"numFound": len(page_docs), "start": 0, "docs": page_docs}}})

    web.routes[DATA_URL] = search
    for d in docs:
        b = d["b_id"][0]
        web.routes[f"https://bidplus.gem.gov.in/showbidDocument/{b}"] = lambda req: httpx.Response(200, content=b"%PDF-1.4 fake", headers={"content-type": "application/pdf"})
    monkeypatch.setattr(documents, "extract_pdf", lambda data: [("p.1", PDF_PAGE_1), ("p.2", PDF_PAGE_2)])
    return posted


def gem_source(db):
    s = db.scalar(select(Source).where(Source.key == "gem"))
    s.enabled = True
    s.config = {**s.config, "search_terms": ["software development"], "pages_per_term": 1}
    db.commit()
    return s


def test_gem_source_seeded_live_with_connector(db):
    s = db.scalar(select(Source).where(Source.key == "gem"))
    assert s.connector == "gem" and s.connector_status == "live" and s.enabled is False


def test_gem_relevance_filter():
    assert is_relevant("Custom Software Development Service")
    assert is_relevant("Hiring Of Agency For It Projects- Milestone Basis")
    assert not is_relevant("Operating System Software (V3)")
    assert not is_relevant("Processor CPU,Barebone 1 SKU,Memory,Storage OS")


def test_gem_page_cleaning_and_fields():
    pages = [("p.1", clean_gem_page(PDF_PAGE_1)), ("p.2", clean_gem_page(PDF_PAGE_2))]
    assert "बड" not in pages[0][1]
    f = parse_gem_fields(pages)
    assert f["bid_end"] == ("11-12-2026 13:00:00", "p.1")
    assert f["organisation"][0] == "Indian Institute Of Technology (iit)"
    assert "10 Lakh" in f["turnover"][0] and "3 Year" in f["experience"][0]
    assert f["mse_relaxation"][0] == "Yes" and f["emd_required"][0] == "No"
    assert f["buyer_email"][0] == "buyer501@gembuyer.in"


def test_gem_run_collects_relevant_service_bids(db, web, monkeypatch):
    posted = install_gem(web, monkeypatch)
    run = run_source(db, gem_source(db))
    assert run.status == RunStatus.SUCCESS.value, run.error_message
    assert posted[0]["csrf_bd_gem_nk"] == ["abc123def"]
    assert run.items_fetched == 1 and run.items_new == 1  # RA and licence purchase skipped
    opp = db.scalar(select(Opportunity))
    assert opp.category == Category.GOVERNMENT_TENDER.value
    assert opp.deadline.strftime("%Y-%m-%d %H:%M") == "2026-12-11 13:00"
    assert opp.country == "India"
    reqs = {r.requirement_key: r for r in db.scalars(select(EligibilityRequirement).where(EligibilityRequirement.opportunity_id == opp.id))}
    assert set(reqs) == {"vendor_registration", "min_turnover", "prior_experience"}  # boilerplate not mined; EMD not required
    assert reqs["min_turnover"].parameters["amount_inr"] == 1_000_000
    assert reqs["min_turnover"].parameters["msme_exemption_mentioned"] is True
    assert reqs["min_turnover"].page_reference == "p.1"
    email = db.scalar(select(Contact).where(Contact.contact_type == "official_email"))
    assert email.value == "buyer501@gembuyer.in" and email.source_url.endswith("/showbidDocument/501")


def test_gem_rerun_skips_seen_bids_without_downloading(db, web, monkeypatch):
    install_gem(web, monkeypatch)
    source = gem_source(db)
    run_source(db, source)
    web.calls.clear()
    run2 = run_source(db, source)
    assert run2.items_new == 0
    assert not any("showbidDocument" in c for c in web.calls)
    assert db.scalar(select(func.count()).select_from(Opportunity)) == 1


def test_gem_csrf_missing_fails_cleanly(db, web, monkeypatch):
    install_gem(web, monkeypatch)
    web.text(LIST_URL, "<html>changed</html>")
    run = run_source(db, gem_source(db))
    assert run.status == RunStatus.FAILED.value and "CSRF" in run.error_message


# --- AI extraction: verification against the source text ---------------------------------------


class FakeAI:
    """Stands in for OpenRouterClient: returns a canned schema instance per task."""

    model_name = "fake/model"

    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def complete_json(self, task, instruction, data, schema, max_tokens=800):
        self.calls += 1
        return schema.model_validate(self.responses[task])


PAGES = [("p.1", "Name of the project: Citizen grievance portal.\nThe bidder must have a valid GST registration."),
         ("p.2", "Last date for receipt of bids is 15 December 2026.\nSole proprietorship firms are not eligible to bid.")]


def test_ai_fields_keep_only_verbatim_quotes():
    ai = FakeAI({"document_fields": AIDocumentFields.model_validate({"fields": [
        {"name": "submission_deadline", "value": "15 December 2026", "page_reference": "p.1", "quote": "Last date for receipt of bids is 15 December 2026."},
        {"name": "budget", "value": "INR 50 lakhs", "page_reference": "p.1", "quote": "Estimated cost is INR 50 lakhs."},  # not in text
        {"name": "buyer", "value": "Ministry of Magic", "page_reference": "p.1", "quote": "Name of the project: Citizen grievance portal."},  # value not in quote
    ]}).model_dump()})
    out = ai_document_fields(ai, PAGES, ["submission_deadline", "budget", "buyer"])
    assert set(out) == {"submission_deadline"}
    assert out["submission_deadline"][1] == "p.2"  # page corrected to where the quote actually is


def test_ai_located_clauses_are_classified_by_rules():
    from app.eligibility import extract_requirements

    ai = FakeAI({"requirement_clauses": AIRequirementClauses.model_validate({"clauses": [
        {"quote": "Sole proprietorship firms are not eligible to bid.", "page_reference": "p.2"},
        {"quote": "Bidders must hold ISO 27001 certification.", "page_reference": "p.1"},  # invented
    ]}).model_dump()})
    clauses = ai_requirement_clauses(ai, PAGES)
    assert clauses == [("p.2", "Sole proprietorship firms are not eligible to bid.")]
    reqs = extract_requirements(clauses)
    assert [(r.key.value, r.parameters.get("accepted")) for r in reqs] == [("proprietorship_acceptance", False)]


def test_ai_refinement_constraints():
    text = "We want someone to put together our order tracking system, paid project."
    cls = classify("Order tracking", text)
    assert should_refine(cls)
    ai = FakeAI({"classification_refine": AIClassificationRefinement.model_validate({
        "category": "direct_software_project", "confidence": 0.95, "services": ["internal_apps", "blockchain"],
        "evidence_quote": "put together our order tracking system, paid project", "rationale": "Paid build request"}).model_dump()})
    assert ai_refine_classification(ai, "Order tracking", text, cls)
    assert cls.category == Category.DIRECT_SOFTWARE_PROJECT and cls.method == "ai"
    assert cls.confidence == 0.65 and "blockchain" not in cls.services and "internal_apps" in cls.services

    cls2 = classify("Order tracking", text)
    bad = FakeAI({"classification_refine": {"category": "direct_software_project", "confidence": 0.9, "services": [],
                                            "evidence_quote": "We urgently need a Django developer", "rationale": "x"}})
    assert not ai_refine_classification(bad, "Order tracking", text, cls2)  # quote not in text
    assert cls2.method == "rules"


def test_ai_budget_caps_calls():
    b = AIBudget(FakeAI({}), 2)
    assert b.take() and b.take() and b.take() is None
    assert AIBudget(None, 5).take() is None
