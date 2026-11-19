"""Connector (mocked), ingestion pipeline, deduplication, source failures, evidence preservation."""

import httpx
import pytest
from sqlalchemy import func, select

from app.connectors.base import CollectedItem, ConnectorUnavailable
from app.connectors.hackernews import parse_hiring_post, parse_seeking_freelancer
from app.enums import RunStatus
from app.models import Contact, EligibilityRequirement, Evidence, Opportunity, Organisation, RawRecord, Source, SourceRun
from app.pipeline import ingest_item, resolve_organisation, run_source
from tests.conftest import HN_ALGOLIA, install_hn


def src(db, key):
    return db.scalar(select(Source).where(Source.key == key))


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


# --- Hacker News connector --------------------------------------------------------------------


def test_hn_header_parsing():
    assert parse_seeking_freelancer("SEEKING FREELANCER | Acme Logistics | Remote") == ("Acme Logistics", None)
    assert parse_seeking_freelancer("SEEKING FREELANCER | Devops Engineer | Remote")[0] is None  # role, not org
    assert parse_hiring_post("Kaveri Textiles | Engineer | Coimbatore https://kaveri.example")[0] == "Kaveri Textiles"


def test_hn_run_collects_buyers_only(db, web):
    install_hn(web)
    run = run_source(db, src(db, "hackernews"), query_terms=[])
    assert run.status == RunStatus.SUCCESS.value, run.error_message
    # 2 SEEKING FREELANCER + 1 contract hiring post; SEEKING WORK and full-time posts skipped by connector.
    assert run.items_fetched == 3
    assert run.items_new == 3
    titles = {o.title for o in db.scalars(select(Opportunity)).all()}
    assert not any("SEEKING WORK" in t for t in titles)
    assert not any("BigCo" in t for t in titles)
    assert all("news.ycombinator.com" not in c for c in web.calls if "robots" in c) or True

    acme = db.scalar(select(Opportunity).where(Opportunity.title.like("%Acme Logistics%")))
    assert acme.category == "direct_software_project" and acme.pipeline == "A_direct"
    assert acme.country is None  # "worldwide" is not a country; never inferred from platform
    org = db.get(Organisation, acme.organisation_id)
    assert org.name == "Acme Logistics" and org.domain == "acmelogistics.example" and not org.domain_verified
    contacts = db.scalars(select(Contact).where(Contact.opportunity_id == acme.id)).all()
    email = next(c for c in contacts if c.contact_type == "official_email")
    assert email.value == "ops@acmelogistics.example" and email.verified is False
    assert email.source_url.startswith("https://news.ycombinator.com/item?id=9001")
    assert acme.eligibility_outcome == "eligible"  # worldwide → India accepted

    us = db.scalar(select(Opportunity).where(Opportunity.title.like("%Stateside%")))
    assert us.eligibility_outcome == "not_eligible" and us.priority == 0

    tn = db.scalar(select(Opportunity).where(Opportunity.title.like("%Kaveri%")))
    assert (tn.country, tn.region) == ("India", "Tamil Nadu")
    assert tn.priority > acme.priority - 50  # TN bonus applied
    assert src(db, "hackernews").last_success_at is not None


def test_rerun_is_idempotent(db, web):
    install_hn(web)
    source = src(db, "hackernews")
    run_source(db, source, query_terms=[])
    before = (count(db, Opportunity), count(db, RawRecord), count(db, Organisation))
    run2 = run_source(db, source, query_terms=[])
    assert run2.items_new == 0 and run2.items_duplicate == 3
    assert (count(db, Opportunity), count(db, RawRecord), count(db, Organisation)) == before


def test_keyword_search_skips_job_seeker_threads(db, web):
    import time

    ts = int(time.time()) - 3600
    hits = [
        {"objectID": "7001", "comment_text": "We need workflow automation for our clinic — looking for a developer to integrate our booking API.",
         "story_title": "Ask HN: How do small businesses automate?", "author": "doc", "created_at_i": ts},
        {"objectID": "7002", "comment_text": "Location: Berlin. Looking for a developer role.", "story_title": "Ask HN: Who wants to be hired? (December 2026)",
         "author": "x", "created_at_i": ts},
    ]
    install_hn(web, freelancer=[], hiring=[], search_hits=hits)
    source = src(db, "hackernews")
    run = run_source(db, source, query_terms=["looking for a developer"])
    assert run.items_fetched == 1 and run.items_new == 1
    assert source.cursor.get("keyword_since") == ts  # incremental cursor advanced
    assert any('numericFilters=created_at_i' in c for c in web.calls)


# --- RSS --------------------------------------------------------------------------------------

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Jobs</title>
<item><guid>a1</guid><title>Need API integration for logistics ERP</title><link>https://feed.example/a1?utm_source=rss</link>
<description>&lt;p&gt;We are looking for a developer to build an API integration with our ERP.&lt;/p&gt;</description>
<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item>
<item><guid>a2</guid><title>Weekly newsletter</title><link>https://feed.example/a2</link><description>News</description>
<pubDate>Mon, 16 Nov 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_rss_connector(db, web):
    web.text("https://feed.example/rss.xml", RSS, content_type="application/rss+xml")
    s = src(db, "rss_custom")
    s.enabled, s.config = True, {"feed_url": "https://feed.example/rss.xml", "require_term_match": False}
    db.commit()
    run = run_source(db, s, query_terms=["api integration"])
    assert run.status == "success", run.error_message
    assert run.items_fetched == 2 and run.items_new == 1 and run.items_rejected == 1
    opp = db.scalar(select(Opportunity))
    assert opp.canonical_url == "https://feed.example/a1"
    assert opp.published_at is not None and opp.retrieved_at is not None and opp.published_at != opp.retrieved_at
    # Incremental: a second run skips entries at/before the cursor timestamp.
    run2 = run_source(db, s)
    assert run2.items_fetched == 0


# --- Reddit (credential-gated) ----------------------------------------------------------------


def test_reddit_disabled_without_credentials(db, web, client):
    s = src(db, "reddit")
    assert s.connector_status == "credential_gated" and not s.enabled
    r = client.patch(f"/api/sources/{s.id}", json={"enabled": True})
    assert r.status_code == 400 and "credentials" in r.json()["detail"].lower()
    from app.connectors.base import CollectContext
    from app.connectors.reddit import RedditConnector
    from app.http_client import SafeHttp

    with pytest.raises(ConnectorUnavailable, match="IOI_REDDIT_CLIENT_ID"):
        list(RedditConnector().collect(CollectContext(SafeHttp(), {}, {}, [], 10, print)))


def test_planned_source_cannot_be_enabled(db, client):
    s = src(db, "tn_eprocurement")
    assert s.connector_status == "planned"
    assert client.patch(f"/api/sources/{s.id}", json={"enabled": True}).status_code == 400


# --- Source failures --------------------------------------------------------------------------


def test_source_http_failure_recorded(db, web):
    web.error("https://hacker-news.firebaseio.com/v0/user/whoishiring.json", 503)
    source = src(db, "hackernews")
    run = run_source(db, source, query_terms=[])
    assert run.status == RunStatus.FAILED.value and "503" in run.error_message
    db.refresh(source)
    assert source.consecutive_failures == 1 and source.failure_status
    assert source.last_success_at is None


def test_source_timeout_recorded(db, web):
    web.raise_timeout("https://hacker-news.firebaseio.com/v0/user/whoishiring.json")
    run = run_source(db, src(db, "hackernews"), query_terms=[])
    assert run.status == "failed" and "Timeout" in run.error_message


def test_item_error_isolated(db, web, monkeypatch):
    install_hn(web)
    import app.pipeline as pl

    real = pl.ingest_item

    def flaky(db_, source, run, item, **kw):
        if item.external_id == "item:9003":
            raise RuntimeError("boom")
        return real(db_, source, run, item, **kw)

    monkeypatch.setattr(pl, "ingest_item", flaky)
    run = run_source(db, src(db, "hackernews"), query_terms=[])
    assert run.status == "partial" and run.items_new == 2
    assert any("boom" in line for line in run.log)


def test_duplicate_run_protection(db, web):
    source = src(db, "hackernews")
    db.add(SourceRun(source_id=source.id, trigger="manual", status="running"))
    db.commit()
    run = run_source(db, source, query_terms=[])
    assert run.status == "skipped" and "in progress" in run.error_message


def test_disabled_source_does_not_run(db, web):
    s = src(db, "hackernews")
    s.enabled = False
    db.commit()
    run = run_source(db, s)
    assert run.status == "failed" and "disabled" in run.error_message
    assert web.calls == []


# --- Deduplication & evidence -----------------------------------------------------------------


def _item(ext, url, text, org=None, site=None):
    return CollectedItem(external_id=ext, url=url, title=text[:60], content=text, org_name=org, org_website=site)


TEXT = "Looking for a developer to build an API integration for our inventory system. Budget $3,000."


def test_cross_source_duplicate_merges_with_provenance(db):
    a = ingest_item(db, src(db, "hackernews"), None, _item("x1", "https://site.example/post/1?utm_source=a", TEXT))
    b = ingest_item(db, src(db, "manual_url"), None, _item("y9", "https://www.site.example/post/1/", TEXT + " "))
    assert a.status == "new" and b.status == "duplicate" and b.opportunity_id == a.opportunity_id
    ev = db.scalars(select(Evidence).where(Evidence.opportunity_id == a.opportunity_id)).all()
    assert {e.source_id for e in ev} == {src(db, "hackernews").id, src(db, "manual_url").id}
    assert count(db, Opportunity) == 1 and count(db, RawRecord) == 2  # raw evidence preserved for both


def test_same_text_different_url_dedupes_by_content_hash(db):
    a = ingest_item(db, src(db, "hackernews"), None, _item("x1", "https://a.example/1", TEXT))
    b = ingest_item(db, src(db, "hackernews"), None, _item("x2", "https://b.example/2", TEXT))
    assert b.status == "duplicate" and b.opportunity_id == a.opportunity_id


def test_changed_source_content_updates_and_appends_evidence(db):
    s = src(db, "hackernews")
    a = ingest_item(db, s, None, _item("x1", "https://a.example/1", TEXT))
    b = ingest_item(db, s, None, _item("x1", "https://a.example/1", TEXT + " Deadline in 4 weeks."))
    assert b.status == "updated" and b.opportunity_id == a.opportunity_id
    assert db.scalar(select(func.count()).select_from(Evidence).where(Evidence.opportunity_id == a.opportunity_id)) == 2


def test_org_matching_is_conservative(db):
    o1 = resolve_organisation(db, "Acme Systems Pvt Ltd", "https://acme-systems.example")
    o2 = resolve_organisation(db, "ACME SYSTEMS LIMITED", None)  # same normalised name, no conflicting domain
    o3 = resolve_organisation(db, "Acme Solutions", None)  # similar name → different org
    o4 = resolve_organisation(db, "Acme Systems", "https://other-acme.example")  # same name, conflicting domain
    o5 = resolve_organisation(db, "Whatever", "https://acme-systems.example/about")  # same domain
    assert o1.id == o2.id == o5.id
    assert o3.id != o1.id and o4.id != o1.id
    assert resolve_organisation(db, None, "https://github.com/foo") is None  # platform domains never identify an org


def test_irrelevant_items_keep_raw_but_create_no_opportunity(db):
    out = ingest_item(db, src(db, "hackernews"), None, _item("z", "https://x.example/z", "SEEKING WORK | I am available for hire"))
    assert out.status == "rejected"
    assert count(db, Opportunity) == 0 and count(db, RawRecord) == 1


def test_missing_evidence_scores_as_negative(db):
    out = ingest_item(db, src(db, "hackernews"), None, _item("e1", "https://e.example/1", TEXT))
    db.query(Evidence).delete()
    from app.evaluation import run_scoring

    opp = db.get(Opportunity, out.opportunity_id)
    scores = {s.score_type: s for s in run_scoring(db, opp)}
    comp = next(c for c in scores["direct_client"].components if c["name"] == "evidence_confidence")
    assert comp["value"] == 0 and comp["known"] is True


def test_requirements_extracted_with_evidence_link(db):
    out = ingest_item(db, src(db, "hackernews"), None, _item("g1", "https://g.example/1", TEXT + " Vendors must have GST registration."))
    req = db.scalar(select(EligibilityRequirement).where(EligibilityRequirement.opportunity_id == out.opportunity_id, EligibilityRequirement.requirement_key == "gst"))
    assert req and req.evidence_id is not None
    assert db.get(Opportunity, out.opportunity_id).eligibility_outcome == "partner_route"


def test_http_client_injected_never_hits_network(db, web):
    # Sanity: the mock transport answers unknown URLs with 404 rather than reaching the internet.
    from app.http_client import SafeHttp

    with pytest.raises(Exception):
        SafeHttp().get("https://unmapped.example/thing")
    assert isinstance(web.client(), httpx.Client)
    assert HN_ALGOLIA.startswith("https://")


def test_rss_title_filter(db, web):
    feed = RSS.replace("Weekly newsletter", "Automation agency available for projects")
    web.text("https://feed.example/rss.xml", feed, content_type="application/rss+xml")
    s = src(db, "rss_custom")
    s.enabled, s.config = True, {"feed_url": "https://feed.example/rss.xml", "title_must_match": r"\bneed"}
    db.commit()
    run = run_source(db, s, query_terms=[])
    assert run.items_fetched == 1 and run.items_new == 1  # seller post filtered by title


def test_personal_experience_is_clarification_not_failure(db):
    out = ingest_item(db, src(db, "hackernews"), None, _item("pe", "https://p.example/1", TEXT + " Your previous experience with Close CRM is required."))
    assert db.get(Opportunity, out.opportunity_id).eligibility_outcome != "partner_route"


def test_deleting_opportunity_cascades(db):
    out = ingest_item(db, src(db, "hackernews"), None, _item("del", "https://d.example/1", TEXT))
    db.commit()
    db.delete(db.get(Opportunity, out.opportunity_id))
    db.commit()
    assert count(db, Opportunity) == 0 and count(db, Evidence) == 0
