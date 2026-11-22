"""Research a company on its official website (selective), and match business news to companies.

Facts are labelled by evidence level:
- what the pages say → source_verified (with URL + excerpt)
- what we think it might need → inferred (hypothesis)
- what we cannot see → unknown
Signals found by keyword rules stay `hypothesis` until the owner confirms them.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import chennai, lead_rules
from app.db import utcnow
from app.http_client import FetchError, SafeHttp
from app.ioi3 import core
from app.ioi3.models import Campaign, Company, RawItem
from app.leads import CHENNAI_FEEDS, _NEWS_INDUSTRY, _official_contacts, _YEAR, fetch_site_pages
from app.normalize import normalize_org_name

HYPOTHESES = {
    lead_rules.EQUIPMENT: [
        ("technician_tracking", "May benefit from one place to assign technicians and track service jobs"),
        ("amc_reminders", "May benefit from automatic AMC/warranty renewal reminders"),
    ],
    lead_rules.WHOLESALE: [
        ("order_intake", "May benefit from taking dealer orders in one place instead of calls/WhatsApp"),
        ("dispatch_status", "May benefit from dispatch status tracking and pending-order reminders"),
    ],
}


class _AIWorkflow(BaseModel):
    class Item(BaseModel):
        statement: str
        quote: str

    items: list[Item] = []


def _ai_workflow(db: Session, c: Company, text: str, pages: list[tuple[str, str, str]]) -> int:
    """Deep mode only: AI proposes workflow statements; kept only if the quote is found verbatim on a page."""
    from app.ai.extraction import quote_in
    from app.ai.openrouter import get_ai

    ai = get_ai(db)
    if ai is None:
        return 0
    instruction = ("From this company's website text, list up to 5 concrete things about HOW the business operates "
                   "(service, installation, AMC, technicians, orders, warehouses, dispatch, dealers). For each give a short "
                   "statement and an exact verbatim quote from the text. Do not guess; skip anything not stated.")
    try:
        out = ai.complete_json("ioi3_workflow", instruction, text[:12000], _AIWorkflow, max_tokens=700)
    except Exception:  # noqa: BLE001 — AI is optional; research continues without it
        return 1
    for it in out.items[:5]:
        for url, _, page_text in pages:
            if it.quote and len(it.quote) > 15 and quote_in(it.quote, page_text):
                core.add_fact(c, kind="workflow", key="ai_workflow", state="source_verified", statement=it.statement[:300],
                              excerpt=it.quote[:600], source_url=url, source_name="Official website (AI-located, quote checked)",
                              detected_by="ai", reliability="medium")
                break
    return 1


def research_company(db: Session, c: Company, http: SafeHttp, *, deep: bool = False, ai_calls_left: int = 0) -> int:
    """Research one company. Returns AI calls used. Caller commits."""
    now = utcnow()
    c.researched_at = now
    ai_used = 0
    if not c.website:
        c.research_error = "No official website known — add one, or research by hand"
        core.evaluate(c, now)
        return 0
    try:
        pages = fetch_site_pages(http, c.website, max_pages=7 if deep else 4)
    except FetchError as exc:
        c.research_error = f"Website could not be loaded: {str(exc)[:200]}"
        core.evaluate(c, now)
        return 0
    c.research_error = None
    camp = db.get(Campaign, c.campaign_id)
    approved = (core.campaign_settings(camp).get("approved_localities") if camp else None) or []
    text = "\n".join(t for _, _, t in pages)

    # Location from the official site
    best = None
    for url, _, t in pages:
        found = chennai.find_chennai_address(t, approved)
        if found and (best is None or found[0].status == chennai.CHENNAI_CITY):
            best = (found[0], found[1], url)
            if found[0].status == chennai.CHENNAI_CITY:
                break
    if best:
        v, excerpt, url = best
        core.add_location(c, address=excerpt[:300], verdict=v, basis="official_site", evidence_url=url, excerpt=excerpt)
        conf = core.location_confidence(v.status, "official_site")
        if conf == "verified" or c.location_confidence != "verified":
            c.location_confidence = conf
            c.location_reason = f"{v.reason} (official website)"
            c.locality = v.locality or c.locality
            c.pincode = v.pincode or c.pincode
            if conf == "verified" and not c.address:  # keep a clean known address; the page snippet stays as evidence
                c.address = excerpt[:300]
    elif c.location_confidence == "partial":
        c.location_reason = (c.location_reason or "") + " — no Chennai address found on the website pages checked"

    # Operations (source-verified workflow facts)
    ops_keys = []
    for key, (label, rx) in lead_rules.OPERATIONS.items():
        for url, _, t in pages:
            m = rx.search(t)
            if m:
                core.add_fact(c, kind="workflow", key=key, state="source_verified", statement=f"The business mentions {label.lower()}",
                              excerpt=lead_rules._excerpt(t, m), source_url=url, source_name="Official website", reliability="high")
                ops_keys.append(key)
                break
    ind = lead_rules.classify_industry(c.name, c.directory_category, text, ops_keys)
    if ind.industry and (c.industry is None or ind.industry == c.industry or c.industry_reasons == ["Industry chosen by you"]):
        c.industry = c.industry or ind.industry
        if ind.industry == c.industry:
            c.industry_strength, c.industry_subtype, c.industry_reasons = ind.strength, ind.subtype, ind.reasons
    m = re.search(r"\b(\d{1,3})\s+branches\b", text, re.I)
    if m:
        core.add_fact(c, kind="identity", key="branches", state="source_verified", statement=f"Says it has {m.group(1)} branches",
                      excerpt=lead_rules._excerpt(text, m), source_url=pages[0][0], source_name="Official website")

    # Public contacts on the official site
    emails, phones = _official_contacts(pages, c.domain)
    for e in emails:
        core.add_contact(c, kind="email", value=e["value"], source_url=e["source_url"], official=True)
    for p in phones:
        core.add_contact(c, kind="phone", value=p["value"], source_url=p["source_url"], official=True)
    for url, html, _ in pages:
        if re.search(r"<form\b", html, re.I) and re.search(r"contact|enquir|inquir|service|complaint", url + html[:20000], re.I) and \
                re.search(r"contact|enquir|support|service", url, re.I):
            core.add_contact(c, kind="contact_form", value=url, source_url=url, official=True, label="Website form")
            break

    # Activity
    years = [int(y) for y in _YEAR.findall(" ".join(h for _, h, _ in pages))]
    recent_date = None
    for url, _, t in pages:  # any explicit date on the site within the last 18 months (news, events, posts)
        for rx, conv in lead_rules._DATE_RX:
            for m in rx.finditer(t):
                try:
                    d = conv(m)
                except ValueError:
                    continue
                if timedelta(0) <= now - d <= timedelta(days=548) and (recent_date is None or d > recent_date[0]):
                    recent_date = (d, url, lead_rules._excerpt(t, m, 60))
    if recent_date and not (years and max(years) >= now.year - 1):
        c.activity = "active"
        core.add_fact(c, kind="activity", key="dated_content", state="source_verified",
                      statement=f"Website shows dated content from {recent_date[0]:%d %b %Y}", excerpt=recent_date[2],
                      source_url=recent_date[1], source_name="Official website", reliability="medium")
    elif years and max(years) >= now.year - 1:
        c.activity = "active"
        core.add_fact(c, kind="activity", key="copyright", state="source_verified", statement=f"Website live with © {max(years)}",
                      source_url=pages[0][0], source_name="Official website", reliability="medium")
    else:
        c.activity = "likely_active" if c.activity != "active" else c.activity
        core.add_fact(c, kind="activity", key="site_live", state="source_verified",
                      statement=f"Website live on {now:%d %b %Y}" + (f" (latest © {max(years)})" if years else " (no dated content found)"),
                      source_url=pages[0][0], source_name="Official website", reliability="low")

    # Existing software mentioned
    for m in core.TOOL_RX.finditer(text):
        tool = m.group(1).lower()
        core.add_fact(c, kind="tools", key=tool, state="source_verified", statement=f"Their website mentions '{m.group(1)}'",
                      excerpt=lead_rules._excerpt(text, m, 80), source_url=pages[0][0], source_name="Official website", reliability="low")

    # Signals (hypotheses until confirmed)
    for url, _, t in pages:
        for found in lead_rules.detect_signals(t):
            if found["signal_type"] == "expansion" and not re.search(r"new|recent|launch|open", found["excerpt"], re.I):
                continue
            pos = t.find(found["excerpt"][:40])
            date = lead_rules.find_date_near(t, max(pos, 0), max(pos, 0) + len(found["excerpt"])) if pos >= 0 else None
            core.add_fact(c, kind="signal", key=found["signal_type"], state="source_verified", review_status="hypothesis",
                          statement=lead_rules.SIGNAL_LABEL[found["signal_type"]], excerpt=found["excerpt"], source_url=url,
                          source_name="Official website", published_at=date, reliability="medium")

    # Hypotheses and unknowns, clearly labelled
    for key, text_h in HYPOTHESES.get(c.industry or "", []):
        core.add_fact(c, kind="problem", key=key, state="inferred", statement=text_h, detected_by="rule")

    if deep and ai_calls_left > 0:
        ai_used = _ai_workflow(db, c, text, pages)

    ops_labels = [lead_rules.OPERATIONS[k][0].lower() for k in ops_keys]
    c.description = (f"{lead_rules.INDUSTRY_LABEL.get(c.industry or '', 'Business')}"
                     + (f" ({c.industry_subtype})" if c.industry_subtype and c.industry_subtype != "other" else "")
                     + (". Website mentions: " + ", ".join(ops_labels[:4]) + "." if ops_labels else ". Website does not describe its operations."))
    c.research_level = "deep" if deep else "website"
    c.last_verified_at = now
    c.prescore = core.prescore(c)
    core.evaluate(c, now)
    return ai_used


# ------------------------------------------------------------------------------------------------
# News
# ------------------------------------------------------------------------------------------------
def scan_news(db: Session, campaign: Campaign, http: SafeHttp, *, feeds: dict[str, str] | None = None, max_age_days: int = 90,
              job_id: int | None = None, on_feed=None) -> dict[str, Any]:
    from app.big_projects import fetch_feed

    feeds = feeds or CHENNAI_FEEDS
    cutoff = utcnow() - timedelta(days=max_age_days)
    names = [(c, f" {c.normalized_name} ") for c in db.scalars(select(Company).where(
        Company.campaign_id == campaign.id, Company.archived.is_(False), Company.review_status != "duplicate"))
        if len(c.normalized_name.split()) >= 2 or len(c.normalized_name) >= 8]
    stats: dict[str, Any] = {"feeds_ok": 0, "feeds_failed": [], "articles": 0, "relevant": 0, "matched": 0, "new_signals": 0}
    for fname, url in feeds.items():
        try:
            items = fetch_feed(http, url)
        except FetchError as exc:
            stats["feeds_failed"].append(f"{fname}: {str(exc)[:120]}")
            if on_feed:
                on_feed(fname, False)
            continue
        stats["feeds_ok"] += 1
        if on_feed:
            on_feed(fname, True)
        for it in items:
            stats["articles"] += 1
            link = it.get("link")
            if not link:
                continue
            pub = datetime.fromtimestamp(it["published_ts"], UTC).replace(tzinfo=None) if it.get("published_ts") else None
            if pub and pub < cutoff:
                continue
            text = f"{it['title']}. {it['summary']}"
            if not re.search(r"\b(chennai|madras)\b", text, re.I) or not _NEWS_INDUSTRY.search(text):
                continue
            found = lead_rules.detect_signals(text)
            if not found:
                continue
            stats["relevant"] += 1
            norm = f" {normalize_org_name(text)} "
            hits = [c for c, n in names if n in norm]
            for c in hits:
                for f in found:
                    if core.add_fact(c, kind="signal", key=f["signal_type"], state="source_verified", review_status="hypothesis",
                                     statement=lead_rules.SIGNAL_LABEL[f["signal_type"]], excerpt=f["excerpt"], source_url=link,
                                     source_name=fname, published_at=pub, reliability="medium") is not None:
                        stats["new_signals"] += 1
                core.evaluate(c)
            stats["matched"] += int(bool(hits))
            ext = link[:200]
            if db.scalar(select(RawItem.id).where(RawItem.campaign_id == campaign.id, RawItem.source_key == "news_rss",
                                                  RawItem.external_id == ext)) is None:
                db.add(RawItem(campaign_id=campaign.id, job_id=job_id, source_key="news_rss", external_id=ext, source_url=link,
                               title=it["title"][:500], published_at=pub, outcome="news_matched" if hits else "unmatched_news",
                               payload={"feed": fname, "signals": [f["signal_type"] for f in found], "summary": it["summary"][:600]},
                               company_id=hits[0].id if hits else None))
    db.commit()
    return stats
