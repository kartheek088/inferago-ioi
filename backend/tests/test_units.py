"""Unit tests: normalisation, classification, eligibility hard gates, score arithmetic."""

from datetime import datetime, timedelta

import pytest

from app.classification import classify, detect_geography
from app.eligibility import assess, extract_requirements, parse_inr_amount
from app.enums import Category, EligibilityOutcome as O, EligibilityScope, Pipeline
from app.normalize import canonical_url, normalize_org_name, org_names_match
from app.profile import DEFAULT_PROFILE, load_profile
from app.scoring import ScoringInput, compute_priority, score_all, score_chain, score_direct, score_vendor

# --- normalisation ----------------------------------------------------------------------------


def test_canonical_url_strips_tracking_and_normalises():
    assert canonical_url("http://WWW.Example.com/path/?utm_source=x&b=2&a=1#frag") == "https://example.com/path?a=1&b=2"
    assert canonical_url("ftp://example.com/x") is None
    assert canonical_url(None) is None


def test_org_name_normalisation_and_conservative_matching():
    assert normalize_org_name("Acme Systems Pvt. Ltd.") == "acme systems"
    assert normalize_org_name("The ACME Systems Private Limited") == "acme systems"
    assert org_names_match("Acme Systems Pvt Ltd", "ACME SYSTEMS LIMITED")
    assert not org_names_match("Acme Systems", "Acme Solutions")  # similar ≠ same
    assert not org_names_match("", "")


# --- classification ---------------------------------------------------------------------------


def test_direct_project_classification():
    r = classify("Looking for a developer", "We need someone to build a REST API integration with our ERP and automate invoices. Budget $5,000.")
    assert r.category == Category.DIRECT_SOFTWARE_PROJECT
    assert r.pipeline == Pipeline.DIRECT
    assert {"api", "integration", "automation"} <= set(r.services)
    assert r.budget_text and "5,000" in r.budget_text
    assert r.evidence and r.confidence >= 0.6


def test_self_promotion_is_irrelevant():
    r = classify("SEEKING WORK | Python dev", "SEEKING WORK | Python developer, available for hire")
    assert r.category == Category.IRRELEVANT


def test_out_of_scope_request_is_irrelevant():
    r = classify("Need a freelancer", "Looking for a freelance designer to make a logo and do SEO")
    assert r.category == Category.IRRELEVANT


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Vendor registration open for IT services suppliers", Category.VENDOR_ONBOARDING),
        ("We are seeking a white-label delivery partner for overflow projects", Category.SUBCONTRACTING),
        ("Join our Odoo implementation partner program", Category.IMPLEMENTATION_PARTNERSHIP),
        ("Notice inviting tender for software. EMD Rs 10,000. Bid submission online via e-procurement", Category.GOVERNMENT_TENDER),
        ("We're hiring a full-time engineer", Category.WEAK_BUYING_SIGNAL),
        ("Hello world", Category.UNKNOWN),
    ],
)
def test_category_rules(text, expected):
    assert classify("", text).category == expected


def test_geography_explicit_only():
    assert detect_geography("Our office is in Chennai") == ("India", "Tamil Nadu", "Text mentions 'Chennai'")
    assert detect_geography("Based in Bengaluru")[0] == "India"
    # Platform domain / unstated location never implies a country.
    assert detect_geography("Posted on news.ycombinator.com — remote role") == (None, None, None)
    assert classify("x", "need api developer").country is None


def test_hard_country_restriction_detected():
    r = classify("Acme | Dev | Remote (US only) | Contract", "Looking for a developer for API work")
    assert r.country_restrictions and r.country_restrictions[0][0] == "United States" and r.country_restrictions[0][2] is True


# --- eligibility ------------------------------------------------------------------------------


def req(key, text="x", mandatory=True, scope="project", **params):
    return {"key": key, "text": text, "mandatory": mandatory, "parameters": params, "scope": scope}


P = DEFAULT_PROFILE


def test_no_requirements_is_unknown_not_eligible():
    res = assess([], P, EligibilityScope.PROJECT)
    assert res.outcome == O.UNKNOWN
    assert "not treated as satisfied" in res.reason


def test_gst_mandatory_failure_gives_partner_route_or_not_eligible():
    res = assess([req("gst", "Bidder must have GST registration")], P, EligibilityScope.PROJECT)
    assert res.outcome == O.PARTNER_ROUTE
    assert res.mandatory_failures and res.mandatory_failures[0]["key"] == "gst"
    # Subcontracting explicitly prohibited → no partner route.
    res2 = assess([req("gst"), req("subcontracting_permission", allowed=False)], P, EligibilityScope.PROJECT)
    assert res2.outcome == O.NOT_ELIGIBLE


def test_country_restriction_is_absolute():
    res = assess([req("country_restriction", allowed_countries=["United States"])], P, EligibilityScope.PROJECT)
    assert res.outcome == O.NOT_ELIGIBLE
    assert "United States" in res.mandatory_failures[0]["reason"]
    ok = assess([req("country_restriction", allowed_countries=["India"])], P, EligibilityScope.PROJECT)
    assert ok.outcome == O.ELIGIBLE


def test_non_mandatory_restriction_is_soft():
    res = assess([req("country_restriction", mandatory=False, allowed_countries=["European Union"])], P, EligibilityScope.PROJECT)
    assert res.outcome in (O.UNCLEAR, O.POTENTIALLY_ELIGIBLE)
    assert not res.mandatory_failures


def test_proprietorship_excluded_is_failure():
    reqs = extract_requirements([("p.2", "Proprietorship firms are not eligible to participate in this tender.")])
    assert reqs[0].key.value == "proprietorship_acceptance" and reqs[0].parameters["accepted"] is False
    res = assess([{"key": r.key.value, "text": r.text, "mandatory": r.mandatory, "parameters": r.parameters, "scope": "project"} for r in reqs], P, EligibilityScope.PROJECT)
    assert res.mandatory_failures


def test_turnover_unknown_profile_never_satisfied_and_msme_exemption_clarifies():
    res = assess([req("min_turnover", "Average annual turnover of Rs 50 lakhs", amount_inr=5_000_000)], P, EligibilityScope.PROJECT)
    assert res.outcome == O.PARTNER_ROUTE and not res.satisfied
    res2 = assess([req("min_turnover", "turnover ... MSEs exempted", amount_inr=5_000_000, msme_exemption_mentioned=True)], P, EligibilityScope.PROJECT)
    assert res2.outcome == O.UNCLEAR and res2.clarifications
    rich = load_profile({"annual_turnover_inr": 10_000_000})
    assert assess([req("min_turnover", amount_inr=5_000_000)], rich, EligibilityScope.PROJECT).outcome == O.ELIGIBLE


def test_satisfied_profile_facts():
    res = assess([req("udyam_msme"), req("pan")], P, EligibilityScope.PROJECT)
    assert res.outcome == O.ELIGIBLE and len(res.satisfied) == 2


def test_vendor_registration_scope_is_separate():
    reqs = [req("gst"), req("vendor_registration", scope="vendor_registration")]
    proj = assess(reqs, P, EligibilityScope.PROJECT)
    vend = assess(reqs, P, EligibilityScope.VENDOR_REGISTRATION)
    assert proj.outcome == O.PARTNER_ROUTE
    assert vend.outcome == O.UNCLEAR  # registration needed; nothing confirmed satisfied
    assert all(e["key"] != "gst" for e in vend.missing + vend.mandatory_failures)


def test_extraction_preserves_page_refs_and_ignores_work_mentions():
    pages = [("p.3", "The bidder shall have a valid GST registration. EMD of Rs 25,000 is payable; MSEs are exempted from EMD."),
             ("p.4", "The vendor will help us achieve SOC2 compliance.")]
    reqs = extract_requirements(pages)
    keys = {r.key.value: r for r in reqs}
    assert keys["gst"].page_reference == "p.3"
    assert keys["emd"].parameters.get("msme_exemption_mentioned")
    assert "security_certifications" not in keys  # SOC2 here is work, not a requirement


def test_parse_inr_amount():
    assert parse_inr_amount("Rs 1.5 crore") == 15_000_000
    assert parse_inr_amount("INR 50 lakhs") == 5_000_000
    assert parse_inr_amount("₹2,00,000") == 200_000


def test_disclaimer_present():
    assert "not legal or tax advice" in assess([req("gst")], P, EligibilityScope.PROJECT).reason


# --- scoring ----------------------------------------------------------------------------------


def full_input(**kw) -> ScoringInput:
    now = datetime(2026, 11, 20)
    base = dict(
        category="direct_software_project", services=["backend", "api", "automation"],
        signals=[("looking_for_developer", "strong"), ("rfp", "strong")], description_length=500,
        budget_text="$10k", scope_detail_terms=2, contacts_verified=1, vendor_positive=["freelanc", "remote"],
        evidence_count=2, published_at=now - timedelta(days=3), classification_confidence=0.9,
        eligibility_outcome="eligible", accepts_external_vendors=True, country="India", remote_ok=True,
        vendor_portal_found=True, confirmed_relationships={"partner_programme": 1, "customer_of": 3, "referral_route": 1},
        org_opportunity_count=3, confirmed_repeat_links=1, now=now,
    )
    base.update(kw)
    return ScoringInput(**base)


def test_component_maxima_sum_to_100():
    for r in score_all(full_input()):
        assert sum(c.max for c in r.components) == 100


def test_perfect_inputs_score_100_each():
    for r in score_all(full_input()):
        assert r.raw_total == 100, (r.score_type, r.components_dict())
        assert r.effective_total == 100
        assert r.unknown_components == 0


def test_total_equals_sum_of_components():
    inp = full_input(services=["api"], signals=[("rfq", "moderate")], budget_text=None, contacts_verified=0, contacts_unverified=1)
    for r in score_all(inp):
        assert r.raw_total == round(sum(c.value for c in r.components), 1)
        assert 0 <= r.raw_total <= 100


def test_direct_component_values():
    r = score_direct(full_input(services=["api"], signals=[("rfq", "moderate")], budget_text=None, description_length=10,
                                scope_detail_terms=0, contacts_verified=0, contacts_unverified=0, research_done=False,
                                vendor_positive=[], evidence_count=1, published_at=None, classification_confidence=0.5))
    vals = {c.name: (c.value, c.known) for c in r.components}
    assert vals["service_fit"] == (15.0, True)
    assert vals["buying_signal"] == (15.0, True)
    assert vals["business_scope"] == (0.0, True)
    assert vals["verified_contact_route"] == (0.0, False)  # unknown, not negative
    assert vals["external_vendor_likelihood"] == (0.0, False)
    assert vals["evidence_confidence"] == (4.0, True)
    assert r.raw_total == 34


def test_unknown_vs_negative_contact():
    unknown = score_direct(full_input(contacts_verified=0, research_done=False))
    negative = score_direct(full_input(contacts_verified=0, research_done=True))
    cu = next(c for c in unknown.components if c.name == "verified_contact_route")
    cn = next(c for c in negative.components if c.name == "verified_contact_route")
    assert cu.value == cn.value == 0
    assert cu.known is False and cn.known is True


def test_mandatory_failure_overrides_all_scores():
    results = score_all(full_input(eligibility_outcome="not_eligible"))
    for r in results:
        assert r.disqualified and r.effective_total == 0 and r.raw_total > 0
        assert "DISQUALIFIED" in r.explanation
    # Chain potential cannot rescue a disqualified opportunity.
    assert compute_priority("C_chain", "general_organisation", results, "India", "Tamil Nadu", [{"match": "Tamil Nadu", "level": "region", "bonus": 15}]) == 0


def test_vendor_eligibility_points():
    def elig_points(outcome):
        return next(c for c in score_vendor(full_input(eligibility_outcome=outcome)).components if c.name == "eligibility")

    assert elig_points("eligible").value == 25
    assert elig_points("potentially_eligible").value == 15
    assert elig_points("partner_route").value == 10
    assert elig_points("unknown").known is False


def test_chain_hypotheses_not_scored():
    r = score_chain(full_input(confirmed_relationships={}, hypothesis_relationships=4, org_opportunity_count=1, confirmed_repeat_links=0))
    vp = next(c for c in r.components if c.name == "verified_partner_programme")
    assert vp.value == 0 and vp.known is False and "hypothes" in vp.explanation


def test_priority_bonus_only_for_explicit_geography():
    results = score_all(full_input())
    pr = [{"match": "Tamil Nadu", "level": "region", "bonus": 15}, {"match": "India", "level": "country", "bonus": 8}]
    assert compute_priority("A_direct", "direct_software_project", results, "India", "Tamil Nadu", pr) == 115
    assert compute_priority("A_direct", "direct_software_project", results, "India", None, pr) == 108
    assert compute_priority("A_direct", "direct_software_project", results, None, None, pr) == 100


@pytest.mark.parametrize(
    "title,expected",
    [
        ("[For hire] Fix or finish a Make scenario", Category.IRRELEVANT),
        ("I can help you track overdue quotes with Make", Category.IRRELEVANT),
        ("[Hiring] Commission-based BD consultants + unpaid portfolio work", Category.IRRELEVANT),
        ("[HIRING] Freelancer for Airtable Workflow | Remote", Category.DIRECT_SOFTWARE_PROJECT),
        ("Airtable Automation Developer Needed", Category.DIRECT_SOFTWARE_PROJECT),
    ],
)
def test_forum_buyer_vs_seller_posts(title, expected):
    body = "We build software for clinics and need workflow automation and API integration."
    assert classify(title, body).category == expected
