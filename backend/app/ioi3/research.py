"""Research a company on its official website (selective), and match business news to companies.

Facts are labelled by evidence level:
- what the pages say → source_verified (with URL + excerpt)
- what we think it might need → inferred (hypothesis)
- what we cannot see → unknown
Signals found by keyword rules stay `hypothesis` until the owner confirms them.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from app.ioi3.fetch import RETRY_AFTER, CachedHttp, Stats, classify_error, is_network_outage, with_retry
from app.ioi3.models import Person
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


_ADDR_START = re.compile(r"(?:\b(?:No\.?|Old No\.?|New No\.?|Door No\.?|Plot No\.?|Flat No\.?|Shop No\.?|Unit)\s*[\w/-]+|#\s?\d+|\b[A-Z]-\d+[A-Z]?\b|\b\d{1,4}[A-Z]?(?:/\d+)?\s*,)")


def clean_address(excerpt: str) -> str | None:
    """A readable address from a page snippet: from the door/plot number to the PIN. None if there isn't one."""
    pin = re.search(r"\b6\d{2}\s?\d{3}\b", excerpt)
    end = pin.end() if pin else None
    head = excerpt[:end] if end else excerpt
    # The address starts at the last door/plot number that still has "Chennai" after it.
    starts = [m for m in _ADDR_START.finditer(head) if re.search(r"chennai|madras", head[m.start():], re.I)]
    if not starts:
        return None
    i = len(starts) - 1
    while i > 0 and starts[i - 1].end() >= starts[i].start() - 2:  # "Unit 21,22, …": adjacent starts belong together
        i -= 1
    addr = re.sub(r"\s+", " ", head[starts[i].start():])
    addr = re.split(r"\s(?:\+91|Ph\b|Tel\b|Phone\b|Mob\b|Email\b|E-mail\b)|\s\S+@\S+", addr)[0].strip(" ,.-")  # stop at contact details
    return addr[:200] if 10 <= len(addr) <= 200 else None


def gather(http_like, website: str, deep: bool) -> tuple[list[tuple[str, str, str]] | None, str | None]:
    """Network phase only (no database): official pages, or the error message."""
    try:
        return fetch_site_pages(http_like, website, max_pages=7 if deep else 4), None
    except FetchError as exc:
        return None, str(exc)


def research_company(db: Session, c: Company, http: SafeHttp, *, deep: bool = False, ai_calls_left: int = 0,
                     use_cache: bool = True, stats: Stats | None = None) -> int:
    """Research one company now (gather + apply). Returns AI calls used. Caller commits."""
    if not c.website:
        return apply_result(db, c, None, None, deep=deep)
    db.commit()  # no transaction may stay open across network I/O (the page cache writes in its own short transactions)
    pages, err = gather(CachedHttp(http, stats, use_cache=use_cache), c.website, deep)
    return apply_result(db, c, pages, err, deep=deep, ai_calls_left=ai_calls_left)


def research_many(db: Session, companies: list[Company], *, deep: bool = False, workers: int = 4, ai_calls_left: int = 0,
                  use_cache: bool = True, on_done: Callable[[Company], None] | None = None,
                  should_stop: Callable[[], bool] | None = None, stats: Stats | None = None) -> dict[str, int]:
    """Research several companies: websites are fetched concurrently (bounded workers; SafeHttp's per-host
    rate limit still applies), results are applied and committed one company at a time as they arrive,
    so partial results are visible immediately. No DB transaction is held during network I/O."""
    stats = stats or Stats()
    db.commit()  # end any read transaction before the slow network phase (prevents stale-snapshot lock errors)
    by_id = {c.id: c for c in companies}
    todo = [(c.id, c.website) for c in companies if c.website]
    out = {"researched": 0, "failed": 0, "no_website": 0, "ai_calls": 0, "cancelled": 0, "network_outage": False}
    for c in companies:
        if not c.website:
            with_retry(lambda c=c: _apply_commit(db, c, None, None, deep, 0))
            out["no_website"] += 1
    local = threading.local()
    clients: list[SafeHttp] = []
    lock = threading.Lock()
    outage = threading.Event()  # this computer can't reach the internet: stop instead of blaming every website
    net = {"ok": 0, "down": 0}

    def work(cid: int, site: str):
        if outage.is_set() or (should_stop and should_stop()):
            return cid, None, "__cancelled__"
        h = getattr(local, "http", None)
        if h is None:
            h = local.http = SafeHttp(rate_limit_per_minute=20)
            with lock:
                clients.append(h)
        pages, err = gather(CachedHttp(h, stats, use_cache=use_cache), site, deep)
        with lock:  # counted in the workers: DNS failures are instant, so the main thread would notice too late
            if err is None:
                net["ok"] += 1
            elif is_network_outage(err):
                net["down"] += 1
                if net["down"] >= 3 and net["ok"] == 0:
                    outage.set()
        return cid, pages, err

    ex = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="ioi3-fetch")
    try:
        futures = [ex.submit(work, cid, site) for cid, site in todo]
        for fut in as_completed(futures):
            cid, pages, err = fut.result()
            if err == "__cancelled__":
                out["cancelled"] += 1
                continue
            c = by_id[cid]
            left = max(0, ai_calls_left - out["ai_calls"])
            used = with_retry(lambda c=c, pages=pages, err=err, left=left: _apply_commit(db, c, pages, err, deep, left))
            out["ai_calls"] += used
            out["failed" if c.research_error else "researched"] += 1
            if outage.is_set():
                out["network_outage"] = True
            if on_done:
                on_done(c)
            if outage.is_set() or (should_stop and should_stop()):
                for f in futures:
                    f.cancel()
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
        for h in clients:
            h.close()
    return {**out, **stats.as_dict()}


def _apply_commit(db: Session, c: Company, pages, err, deep: bool, ai_left: int) -> int:
    try:
        used = apply_result(db, c, pages, err, deep=deep, ai_calls_left=ai_left)
        db.commit()
        return used
    except Exception:
        db.rollback()
        raise


def apply_result(db: Session, c: Company, pages: list[tuple[str, str, str]] | None, err: str | None, *, deep: bool = False,
                 ai_calls_left: int = 0) -> int:
    """Database phase: turn fetched official pages (or the fetch error) into labelled evidence. Returns AI calls used."""
    now = utcnow()
    c.researched_at = now
    ai_used = 0
    if not c.website:
        c.research_error, c.research_error_kind, c.research_retry_after = "No official website known — add one, or research by hand", "permanent", None
        core.evaluate(c, now)
        return 0
    if err is not None or pages is None:
        kind, plain = classify_error(err or "unknown error")
        c.research_error = f"Website could not be loaded: {plain}"
        c.research_error_kind = kind
        c.research_retry_after = now + (RETRY_AFTER["outage"] if is_network_outage(err or "") else RETRY_AFTER[kind])
        core.evaluate(c, now)
        return 0
    c.research_error = c.research_error_kind = c.research_retry_after = None
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
                c.address = clean_address(excerpt)  # None if no clean address; the full excerpt stays as evidence
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

    # Company profile from its own pages: management roles, testimonials, year established
    extract_profile(c, pages)

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
# Company profile extraction (deterministic; every item keeps its verbatim quote and page URL)
# ------------------------------------------------------------------------------------------------
_ROLE = (r"(Managing Director|Founder\s*(?:&|and)\s*(?:CEO|Managing Director|Director)|Co-?Founder|Founder|Proprietor|Managing Partner|"
         r"Chief Executive Officer|CEO|Technical Director|Director|General Manager|Service Manager|Operations Manager|"
         r"Sales Manager|Business Development Manager|Chairman)")
_NAME = r"((?:(?:Mr|Mrs|Ms|Dr|Er)\.?\s+)?(?:[A-Z]\.\s?){0,3}[A-Z][a-z]{2,}(?:\s+(?:[A-Z]\.\s?)*[A-Z][a-z]{2,}){0,3})"
_NOT_NAMES = {"Our", "The", "Company", "Chennai", "Team", "India", "Limited", "Private", "Services", "Contact", "About", "Home",
              "Equipment", "Equipments", "Systems", "Solutions", "Engineering", "Engineers", "Group", "Pvt", "Ltd", "Welcome", "Board",
              "Message", "From", "Meet", "Who", "Leadership", "Management", "Industries", "Enterprises", "Technologies"}
_PEOPLE_RX = [re.compile(rf"{_NAME}\s*[,–—-]\s*(?:our\s+)?{_ROLE}\b"), re.compile(rf"\b{_ROLE}\s*(?:[:,–—-]|is)?\s*{_NAME}")]
_ROLE_GROUP = [("owner", r"founder|proprietor|partner|chairman"), ("leadership", r"managing director|ceo|chief executive|director|general manager"),
               ("service", r"service"), ("operations", r"operations"), ("sales", r"sales|business development")]
_FOUNDED = re.compile(r"\b(?:since|established in|established|founded in|incorporated in|started in|in business since)\s+(19[5-9]\d|20[0-2]\d)\b", re.I)
_TESTIMONIAL_PAGE = re.compile(r"testimonial|what[- ]our[- ]clients|client[- ]speak|case[- ]stud|success[- ]stor", re.I)


def _clean_name(raw: str) -> str | None:
    name = re.sub(r"\s+", " ", raw).strip(" ,.-")
    words = [w.strip(".") for w in name.split()]
    if not words or any(w in _NOT_NAMES for w in words) or len(name) < 4:
        return None
    if sum(1 for w in words if len(w) > 2) < 1:
        return None
    return name


def extract_people(pages: list[tuple[str, str, str]]) -> list[dict]:
    found: dict[tuple[str, str], dict] = {}
    for url, _, text in pages:
        for rx in _PEOPLE_RX:
            for m in rx.finditer(text):
                groups = m.groups()
                name_raw, role = (groups[0], groups[1]) if rx is _PEOPLE_RX[0] else (groups[1], groups[0])
                name = _clean_name(name_raw)
                if not name:
                    continue
                role = re.sub(r"\s+", " ", role).strip()
                group = next((g for g, r in _ROLE_GROUP if re.search(r, role, re.I)), "other")
                window = text[max(0, m.start() - 40): m.end() + 160]
                email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text[m.end(): m.end() + 160])
                found.setdefault((name.lower(), role.lower()), {
                    "name": name[:200], "role": role[:120], "role_group": group, "source_url": url,
                    "excerpt": re.sub(r"\s+", " ", window).strip()[:400], "published_contact": email.group(0) if email else None})
    return list(found.values())[:6]


def extract_profile(c: Company, pages: list[tuple[str, str, str]]) -> None:
    for p in extract_people(pages):
        if not any(x.name.lower() == p["name"].lower() and x.role.lower() == p["role"].lower() for x in c.people):
            c.people.append(Person(**p, detected_by="rule"))
    for url, _, text in pages:
        m = _FOUNDED.search(text)
        if m:
            core.add_fact(c, kind="identity", key="founded", state="source_verified", statement=f"Says it was established in {m.group(1)}",
                          excerpt=lead_rules._excerpt(text, m, 80), source_url=url, source_name="Official website", reliability="medium")
            break
    for url, _, text in pages:
        if not _TESTIMONIAL_PAGE.search(url) and not _TESTIMONIAL_PAGE.search(text[:400]):
            continue
        paras = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?”\"])\s{2,}", text) if 60 <= len(p.strip()) <= 400]
        for para in paras[:2]:
            core.add_fact(c, kind="testimonial", key=None, state="source_verified", statement="Testimonial / case study published on their own website",
                          excerpt=para, source_url=url, source_name="Official website", reliability="low", account_type="company_published")
        break


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
    stats: dict[str, Any] = {"feeds_ok": 0, "feeds_failed": [], "articles": 0, "relevant": 0, "matched": 0, "new_signals": 0,
                             "skipped_backoff": 0}
    from app.settings_store import get_setting, set_setting

    backoff: dict[str, dict] = dict(get_setting(db, "ioi3_feed_backoff") or {})
    db.commit()  # no transaction stays open while feeds download
    fetched: list[tuple[str, list[dict]]] = []
    now = utcnow()
    for fname, url in feeds.items():
        b = backoff.get(url) or {}
        if b.get("until") and datetime.fromisoformat(b["until"]) > now:
            stats["skipped_backoff"] += 1
            continue
        try:
            fetched.append((fname, fetch_feed(http, url)))
            backoff.pop(url, None)
        except FetchError as exc:
            fails = int(b.get("fails", 0)) + 1
            backoff[url] = {"fails": fails, "until": (now + timedelta(hours=min(24, 2 ** (fails - 1)))).isoformat(), "error": str(exc)[:200]}
            stats["feeds_failed"].append(f"{fname}: {str(exc)[:120]}")
            if on_feed:
                on_feed(fname, False)
    set_setting(db, "ioi3_feed_backoff", backoff)
    for fname, items in fetched:
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
