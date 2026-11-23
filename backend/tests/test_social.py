"""Social Commerce Intelligence: channel isolation, platform links, Chennai rules, qualification.

Every seller used here is synthetic and flagged `is_test` where it is stored. No test touches the
live internet: HTTP goes through the `web` fixture (httpx.MockTransport).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app import lead_rules
from app.ioi3 import core as b2b_core
from app.ioi3.models import B2B, SOCIAL, Company
from app.ioi3.social import categories as cat
from app.ioi3.social import collect, core, geo, platforms, qualify, solutions


@pytest.fixture
def camp(db):
    core.seed_sources(db)
    return core.active_campaign(db)


def add(db, camp, **kw):
    data = {"link": "https://www.instagram.com/asha_cakes_chennai/", "name": "Asha Cakes",
            "description": "Custom cakes and brownies. 50% advance to confirm. Order 3 days in advance. "
                           "Delivery across Chennai. DM to order.",
            "address": "No 12, 2nd Street, Adyar, Chennai 600020", "phone": "9876543210"}
    data.update(kw)
    return collect.add_profile(db, camp, data)


# ------------------------------------------------------------------------------------------------
# Platform links (§8E)
# ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,platform,handle", [
    ("https://www.instagram.com/chennai_boutique/", "instagram", "chennai_boutique"),
    ("@cakesbyasha", "instagram", "cakesbyasha"),
    ("https://facebook.com/MyGiftShopChennai", "facebook", "mygiftshopchennai"),
    ("https://www.facebook.com/profile.php?id=123456", "facebook", "123456"),
    ("https://wa.me/919876543210", "whatsapp", "9876543210"),
    ("+91 98765 43210", "whatsapp", "9876543210"),
    ("https://mystore.in/shop/cakes", "other", "mystore.in/shop/cakes"),
])
def test_profile_links_recognised(raw, platform, handle):
    ref = platforms.parse(raw)
    assert (ref.platform, ref.handle) == (platform, handle)


@pytest.mark.parametrize("raw,because", [
    ("https://www.instagram.com/p/Cabc123/", "post, not a profile"),
    ("https://chat.whatsapp.com/XYZ", "group invite"),
    ("https://linkedin.com/in/someone", "not read automatically"),
    ("1234567890", "not a valid Indian mobile"),
    ("", "paste a public profile"),
])
def test_unusable_links_refused(raw, because):
    with pytest.raises(platforms.NotAProfile):
        platforms.parse(raw)


def test_whatsapp_group_and_follower_lists_are_never_touched():
    """A group invite is refused outright; there is no code path that reads members or followers."""
    with pytest.raises(platforms.NotAProfile, match="never joins groups"):
        platforms.parse("https://chat.whatsapp.com/ABCDEF")
    assert platforms.FETCHABLE[platforms.INSTAGRAM] is False
    assert platforms.FETCHABLE[platforms.FACEBOOK] is False


# ------------------------------------------------------------------------------------------------
# Chennai geography for sellers with no storefront (§7)
# ------------------------------------------------------------------------------------------------
def test_weak_evidence_never_establishes_location():
    v = geo.classify([geo.GeoEvidence("hashtag", "#chennai"), geo.GeoEvidence("caption_language", "Tamil captions"),
                      geo.GeoEvidence("follower", "a Chennai follower"),
                      geo.GeoEvidence("customer_comment", "I am in Adyar")])
    assert v.confidence == geo.UNCLEAR
    assert v.weak_ignored and "hashtag" in " ".join(v.weak_ignored)


def test_profile_address_verifies_location():
    v = geo.classify([geo.GeoEvidence("profile_location", "Boutique in Adyar, Chennai 600020")])
    assert v.confidence == geo.VERIFIED
    assert v.locality == "adyar"


def test_one_medium_source_is_only_probable():
    v = geo.classify([geo.GeoEvidence("delivery_area", "We deliver across Velachery, Chennai")])
    assert v.confidence == geo.PROBABLE


def test_two_independent_medium_sources_corroborate():
    v = geo.classify([geo.GeoEvidence("delivery_area", "Delivery in Velachery, Chennai"),
                      geo.GeoEvidence("event_listing", "Stall at a Chennai pop-up, Nungambakkam")])
    assert v.confidence == geo.VERIFIED


def test_two_of_the_same_basis_do_not_corroborate():
    v = geo.classify([geo.GeoEvidence("delivery_area", "Delivery in Velachery, Chennai"),
                      geo.GeoEvidence("delivery_area", "Also Adyar, Chennai")])
    assert v.confidence == geo.PROBABLE


def test_outside_city_is_excluded():
    assert geo.classify([geo.GeoEvidence("profile_location", "Shop in Coimbatore")]).confidence == geo.OUTSIDE
    # Metro area but outside the corporation limit.
    assert geo.classify([geo.GeoEvidence("official_site", "No 5, Tambaram, Chennai 600045")]).confidence == geo.OUTSIDE


def test_only_verified_enters_high_priority_queue():
    assert geo.high_priority_ready(geo.VERIFIED) is True
    assert geo.high_priority_ready(geo.PROBABLE) is False


# ------------------------------------------------------------------------------------------------
# Product categories and complexity (§6, §10)
# ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Custom cakes & brownies, pre-order 2 days in advance", cat.BAKERY),
    ("Ethnic wear boutique, all sizes, DM to order", cat.FASHION),
    ("Personalised gift hampers and engraved frames", cat.GIFTS),
    ("Daily tiffin service, monthly plans, pause anytime", cat.MEALS),
    ("Handmade crochet earrings", cat.OTHER),
])
def test_product_categories(text, expected):
    assert cat.classify_category(text).category == expected


def test_non_social_business_is_not_categorised():
    assert cat.classify_category("We supply industrial pumps and spare parts").category is None


def test_complexity_indicators_detected():
    text = ("Custom cakes made to order. 50% advance to confirm. Order 3 days in advance. "
            "Delivery across Chennai. DM to order or WhatsApp.")
    keys = {f.key for f in cat.detect_complexity(text)}
    assert {"custom_orders", "advance_payment", "deadlines", "delivery"} <= keys
    assert cat.complexity_level(keys) == "high"
    assert cat.complexity_level(set()) == "unknown"
    assert cat.complexity_level({"delivery"}) == "low"


def test_activity_and_demand_indicators_are_separated():
    launch = cat.detect_signals("New collection just launched for Diwali!")
    assert {f.indicator_class for f in launch} == {"activity"}
    sold = cat.detect_signals("Sold out! All slots full")
    assert {f.indicator_class for f in sold} == {"demand_indicator"}
    need = cat.detect_signals("I cannot keep track of all the orders coming in DMs")
    assert any(f.key == "explicit_software_need" for f in need)


def test_website_does_not_disqualify_and_checkout_is_recognised():
    s = cat.classify_setup(platforms={"instagram"}, website_text="Add to cart and checkout with Razorpay",
                           website="shop.example.in", catalogue_url=None, bio_text="")
    assert s.setup == cat.SOCIAL_FULL_ECOM
    assert "razorpay" in s.tools


# ------------------------------------------------------------------------------------------------
# Ingestion and channel isolation (§3, §19)
# ------------------------------------------------------------------------------------------------
def test_social_seller_is_ingested_and_qualified(db, camp):
    r = add(db, camp)
    assert r.outcome == "accepted"
    c = r.company
    assert c.channel == SOCIAL
    assert c.social.product_category == cat.BAKERY
    assert c.social.geo_confidence == geo.VERIFIED
    assert {"custom_orders", "advance_payment", "deadlines"} <= set(c.social.complexity_keys)
    assert c.social.sales_setup in (cat.SOCIAL_ONLY, cat.SOCIAL_WHATSAPP)
    assert c.qualification in (qualify.S1, qualify.S2)
    assert (c.solution or {}).get("offer") == "Pre-Order and Delivery Tracker"
    assert any(a.platform == "instagram" and a.handle == "asha_cakes_chennai" for a in c.social_accounts)


def test_seller_with_no_website_or_entity_is_not_disqualified(db, camp):
    r = add(db, camp, website=None)
    c = r.company
    assert r.outcome == "accepted"
    assert c.website is None
    assert not any(g["passed"] is False for g in c.gates), c.gates


def test_identical_input_is_recognised_as_already_seen(db, camp):
    add(db, camp)
    assert add(db, camp, link="@asha_cakes_chennai").outcome == "already_seen"


def test_same_handle_from_another_source_is_a_duplicate(db, camp):
    """The platform handle identifies the seller, whichever source found them."""
    first = add(db, camp)
    again = collect.Candidate(source_key="market_listings", external_id="instagram:asha_cakes_chennai",
                              source_url="https://example.org/market", name="Asha Cakes (pop-up)",
                              links=["https://www.instagram.com/asha_cakes_chennai/"],
                              description="Custom cakes", phones=["9000000001"])
    r = collect.ingest(db, camp, again)
    assert r.outcome == "duplicate"
    assert r.company.id == first.company.id
    # The second sighting still enriches the seller we already had.
    assert any(x.value.endswith("9000000001") for x in r.company.contacts)


def test_outside_chennai_is_refused(db, camp):
    r = add(db, camp, link="https://www.instagram.com/cbe_cakes/", name="CBE Cakes",
            address="Gandhipuram, Coimbatore 641012")
    assert r.outcome == "outside_chennai"
    assert db.query(Company).filter(Company.name == "CBE Cakes").count() == 0


def test_automated_sources_require_a_category_but_manual_does_not(db, camp):
    hardware = collect.Candidate(source_key="market_listings", external_id="instagram:pumps_co",
                                 source_url="https://example.org/market", name="Pumps Co",
                                 links=["https://www.instagram.com/pumps_co/"],
                                 description="We supply industrial pumps")
    assert collect.ingest(db, camp, hardware, require_category=True).outcome == "not_social_category"
    assert collect.ingest(db, camp, hardware, require_category=False).outcome == "accepted"


def test_b2b_pipeline_is_untouched_by_the_social_campaign(db, camp):
    """The B2B campaign must stay a different row, and B2B companies keep the P0-P3 engine."""
    b2b = b2b_core.active_campaign(db)
    assert b2b.id != camp.id
    assert b2b.channel == B2B and camp.channel == SOCIAL
    add(db, camp)
    # A B2B company still evaluates with B2B rules through the shared choke point.
    bc = b2b_core.new_company(b2b.id, name="Chennai Pumps & Equipments", source_key="manual",
                              source_ref="manual:1", source_url="https://example.org/x")
    bc.industry = lead_rules.EQUIPMENT
    db.add(bc)
    db.flush()
    b2b_core.evaluate(bc)
    assert bc.qualification.startswith("P")
    assert bc.channel == B2B
    # And the social seller keeps the S engine.
    sc = db.query(Company).filter(Company.channel == SOCIAL).one()
    b2b_core.evaluate(sc)
    assert sc.qualification.startswith("S")


def test_cross_channel_appearance_is_noted_not_merged(db, camp):
    b2b = b2b_core.active_campaign(db)
    bc = b2b_core.new_company(b2b.id, name="Asha Cakes", source_key="manual", source_ref="manual:9",
                              source_url="https://example.org/x")
    db.add(bc)
    db.flush()
    b2b_core.add_contact(bc, kind="phone", value="9876543210", source_url="https://example.org/x", official=False)
    db.commit()
    r = add(db, camp)
    assert r.outcome == "accepted"
    assert r.company.id != bc.id  # separate records, by design
    assert any(f.key == "cross_channel" for f in r.company.facts)


def test_csv_import(db, camp):
    text = ("name,link,category,description,address,phone\n"
            "Asha Cakes,https://www.instagram.com/asha_cakes/,home_bakery,Custom cakes made to order,"
            "\"Adyar, Chennai 600020\",9876543210\n"
            "No Link Co,,,,,\n")
    stats = collect.import_csv(db, camp, text)
    assert stats["accepted"] == 1
    assert stats["no_profile"] == 1


def test_market_page_sellers_are_extracted():
    html = ('<p>Our Chennai pop-up sellers in Nungambakkam:</p>'
            '<a href="https://www.instagram.com/asha_cakes/">Asha Cakes</a>'
            '<a href="https://www.instagram.com/p/Cxyz/">a post</a>'
            '<p>Also @giftsbymeera will be there</p>')
    from app.normalize import html_to_text

    cands = collect.sellers_from_market_page("https://example.org/market", html, html_to_text(html))
    handles = {c.external_id for c in cands}
    assert "instagram:asha_cakes" in handles
    assert "instagram:giftsbymeera" in handles
    assert not any("Cxyz" in h for h in handles)  # a post link is never a seller
    assert all(any(b == "event_listing" for b, _ in c.geo_evidence) for c in cands)


# ------------------------------------------------------------------------------------------------
# Qualification engine (§13)
# ------------------------------------------------------------------------------------------------
NOW = datetime(2026, 11, 23)


def snap(**kw) -> qualify.Snapshot:
    d = dict(name="Test", category=cat.BAKERY, geo_confidence=geo.VERIFIED, platforms={"instagram"},
             activity=[qualify.ActivityView("product_launch", "activity", NOW - timedelta(days=10),
                                            "https://x/1", "hypothesis")],
             complexity_keys={"custom_orders", "deadlines", "advance_payment"}, official_contacts=1,
             sales_setup=cat.SOCIAL_WHATSAPP, order_channels=["dm", "whatsapp"], research_level="deep")
    d.update(kw)
    return qualify.Snapshot(**d)


def cat_of(s: qualify.Snapshot) -> str:
    return qualify.categorise(s, qualify.gates(s, NOW), NOW)[0]


def test_s1_needs_every_gate_and_a_recent_trigger():
    s = snap()
    assert qualify.ready(qualify.gates(s, NOW)) is True
    assert cat_of(s) == qualify.S1


def test_s0_requires_human_confirmation_not_a_keyword():
    hypothesis = snap(activity=[qualify.ActivityView("explicit_software_need", "demand_indicator",
                                                     NOW - timedelta(days=5), "https://x/2", "hypothesis")])
    assert cat_of(hypothesis) == qualify.S1  # looks like a request, but nobody has checked it
    confirmed = snap(activity=[qualify.ActivityView("explicit_software_need", "demand_indicator",
                                                    NOW - timedelta(days=5), "https://x/2", "confirmed")])
    assert cat_of(confirmed) == qualify.S0
    assert cat_of(snap(confirmed_problems=["I keep losing cake orders in DMs"])) == qualify.S0


def test_probable_location_cannot_reach_s1():
    assert cat_of(snap(geo_confidence=geo.PROBABLE)) == qualify.S2


def test_excluded_cases():
    assert cat_of(snap(geo_confidence=geo.OUTSIDE)) == qualify.S3
    assert cat_of(snap(category=None)) == qualify.S3
    assert cat_of(snap(activity=[qualify.ActivityView("product_launch", "activity", NOW - timedelta(days=400),
                                                      "https://x/3", "hypothesis")])) == qualify.S3
    assert cat_of(snap(review_status="duplicate")) == qualify.S3


def test_unknown_is_never_a_pass():
    s = snap(official_contacts=0, other_contacts=0)
    g = {x["key"]: x["passed"] for x in qualify.gates(s, NOW)}
    assert g["contact"] is None
    assert cat_of(s) == qualify.S2


def test_score_components_total_one_hundred():
    total, parts = qualify.score(snap(), NOW, 3)
    assert sum(p["max"] for p in parts) == 100
    assert 0 <= total <= 100
    assert [p["key"] for p in parts] == ["need", "complexity", "activity", "contact", "simplicity", "source"]


def test_score_never_bypasses_a_gate():
    """A high score with a failed gate is still excluded."""
    s = snap(geo_confidence=geo.OUTSIDE, confirmed_problems=["They asked us to build it"])
    total, _ = qualify.score(s, NOW, 3)
    assert total >= 60
    assert cat_of(s) == qualify.S3


def test_followers_are_recorded_but_never_scored():
    """There is no follower field in the snapshot the score is computed from."""
    assert not any("follower" in f for f in qualify.Snapshot.__dataclass_fields__)


def test_maturity_is_evidence_based():
    assert qualify.maturity(snap(activity=[]), NOW)[0] == qualify.INACTIVE
    assert qualify.maturity(snap(activity=[qualify.ActivityView("restock", "activity", None, "https://x", "hypothesis")]),
                            NOW)[0] == qualify.UNCLEAR_ACT
    assert qualify.maturity(snap(complexity_keys={"delivery"}), NOW)[0] == qualify.EARLY
    assert qualify.maturity(snap(), NOW)[0] == qualify.GROWING
    established = snap(complexity_keys={"custom_orders", "deadlines", "advance_payment", "recurring"},
                       activity=[qualify.ActivityView("product_launch", "activity", NOW - timedelta(days=5), "https://x/1", "hypothesis"),
                                 qualify.ActivityView("sold_out", "demand_indicator", NOW - timedelta(days=12), "https://x/2", "hypothesis"),
                                 qualify.ActivityView("order_announcement", "demand_indicator", NOW - timedelta(days=20), "https://x/3", "hypothesis")])
    assert qualify.maturity(established, NOW)[0] == qualify.ESTABLISHED


def test_no_win_probability_is_ever_produced():
    s = snap()
    assert qualify.buying_intent(s) == "unknown"
    assert qualify.commercial_readiness(s, NOW) in ("unknown", "limited_public")
    for value in (qualify.operational_fit(s), qualify.evidence_quality(s), qualify.friction(s)[0]):
        assert isinstance(value, str) and "%" not in value


# ------------------------------------------------------------------------------------------------
# Solutions: cheapest effective option first (§12, §16)
# ------------------------------------------------------------------------------------------------
def rec(**kw):
    d = dict(category=cat.BAKERY, complexity_keys={"custom_orders", "deadlines", "advance_payment"}, tools=[],
             sales_setup=cat.SOCIAL_WHATSAPP, confirmed_problems=[], order_channels=["dm", "whatsapp"],
             workflow_gaps=["Orders arrive as chat messages"])
    d.update(kw)
    return solutions.recommend(**d)


def test_each_category_gets_its_offer():
    assert rec()["offer"] == "Pre-Order and Delivery Tracker"
    assert rec(category=cat.FASHION)["offer"] == "Social OrderFlow Lite"
    assert rec(category=cat.GIFTS)["offer"] == "Custom OrderFlow"
    assert rec(category=cat.MEALS, complexity_keys={"recurring", "delivery", "advance_payment"})["offer"] == "Subscription OrderFlow"


def test_existing_software_is_configured_before_anything_is_built():
    out = rec(tools=["dukaan"])
    assert out["level"] == 2
    assert "dukaan" in out["improvement"]
    assert "dukaan" in out["existing_software"]["advice"]


def test_simple_seller_is_offered_a_free_form_not_a_build():
    out = rec(complexity_keys={"delivery"})
    assert out["level"] == 1
    assert "free form" in out["improvement"]


def test_existing_checkout_is_not_replaced():
    out = rec(sales_setup=cat.SOCIAL_FULL_ECOM)
    assert "Keep their existing checkout" in out["improvement"]
    assert "replac" in out["why"]


def test_one_confirmed_problem_gets_the_smallest_fix():
    out = rec(confirmed_problems=["I lose track of which orders are paid"])
    assert out["offer"] == "Small Automation"
    assert "I lose track" in out["improvement"]


def test_no_platform_api_integration_is_promised():
    for category in cat.CATEGORIES:
        out = rec(category=category)
        if out["offer"]:
            assert "approved Meta API access" in out["delivery_note"]


# ------------------------------------------------------------------------------------------------
# Sources: honest availability (§9)
# ------------------------------------------------------------------------------------------------
def test_meta_api_is_reported_unavailable(db, camp):
    s = core.source(db, "meta_api")
    assert s is not None and s.health == "needs_setup"
    assert "permissions" in (s.last_error or "")


def test_manual_source_is_the_one_that_always_works(db, camp):
    assert core.source(db, "manual_profile").health == "working"
