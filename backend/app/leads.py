"""Chennai lead pipeline: collect → filter industry → dedupe + location → website check → signals → A–D.

Cost-conscious by design (owner has no API budget):
1. Collect   — local Overture Parquet file (already downloaded; no network), Chennai box only.
2. Filter    — deterministic industry rules (`lead_rules.classify_industry`).
3. Dedupe    — same normalised name + same phone / domain / ~300 m; location from address text.
4. Verify    — only the top N by `prescore`: official website (≤ 4 pages, robots.txt respected) for a
               Chennai-city address, published contacts, operations and signal candidates.
5. Signals   — public news RSS (Chennai mention + industry + signal rule), matched to lead names;
               plus anything the owner adds by hand (with URL and date).
6. Evaluate  — `lead_rules.categorise` / `sales_difficulty` with reasons. No AI involved.

Nothing is ever sent. Outreach drafts need explicit owner approval and are sent by the owner.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import chennai, lead_rules
from app.db import utcnow
from app.http_client import FetchError, SafeHttp
from app.models import ChennaiLead, LeadSignal, ProspectRun
from app.normalize import domain_of, html_to_text, normalize_org_name
from app.profile import SERVICE_KEYS

RUN_LABEL = "Chennai leads"

# Public RSS feeds worth scanning for Chennai distribution / equipment-service news (robots.txt checked per fetch).
CHENNAI_FEEDS: dict[str, str] = {
    "The Hindu · Chennai": "https://www.thehindu.com/news/cities/chennai/feeder/default.rss",
    "The Hindu · Tamil Nadu": "https://www.thehindu.com/news/national/tamil-nadu/feeder/default.rss",
    "The Hindu · Business": "https://www.thehindu.com/business/feeder/default.rss",
    "BusinessLine · Companies": "https://www.thehindubusinessline.com/companies/feeder/default.rss",
    "ET · Industry": "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
    "ET · Small business": "https://economictimes.indiatimes.com/small-biz/rssfeeds/5575607.cms",
    "ET Health": "https://health.economictimes.indiatimes.com/rss/topstories",
    "ET Retail": "https://retail.economictimes.indiatimes.com/rss/topstories",
}
_NEWS_INDUSTRY = re.compile(
    r"\b(distribut\w*|wholesal\w*|stockist|warehous\w*|dealer network|dealers|logistics park|"
    r"medical (?:devices?|equipment)|diagnostic equipment|equipment|service cent(?:re|er)|after-sales|"
    r"elevators?|HVAC|generators?|machine tools?|laboratory)\b", re.I)
_SOCIAL = re.compile(r"facebook\.com|instagram\.com|linkedin\.com|twitter\.com|x\.com|youtube\.com|wa\.me|whatsapp", re.I)
_EMAIL = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w-])")
_PHONE = re.compile(r"(?:\+91[\s-]?|\b0)?(?:44[\s-]?\d{4}[\s-]?\d{4}|[6-9]\d{4}[\s-]?\d{5})\b")
_LINK = re.compile(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_SUBPAGE = re.compile(r"contact|about|service|support|branch|location|amc|reach|network|dealer|career|news|press|team|leadership|management|testimonial|client|case", re.I)
_YEAR = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d{2})", re.I)


# ------------------------------------------------------------------------------------------------
# Evaluation (deterministic)
# ------------------------------------------------------------------------------------------------
def _approved_localities(db: Session | None) -> list[str]:
    if db is None:
        return []
    from app.settings_store import get_setting

    v = get_setting(db, "chennai_approved_localities")
    return [str(x) for x in v] if isinstance(v, list) else []


def facts_of(lead: ChennaiLead) -> lead_rules.LeadFacts:
    sigs = [lead_rules.Signal(s.signal_type, s.url, s.published_at, s.review_status, s.excerpt) for s in lead.signals]
    contacts = (lead.phones or []) + (lead.emails or [])
    return lead_rules.LeadFacts(
        name=lead.name,
        industry=lead.industry,
        industry_strength=lead.industry_strength,
        location_status=lead.location_status,
        location_verified=lead.location_verified,
        activity_status=lead.activity_status,
        has_contact_route=any(c.get("source_url") for c in contacts),
        contact_from_official_site=any(c.get("official") and c.get("source_url") for c in contacts),
        signals=sigs,
        operations=[o["key"] for o in (lead.operations or [])],
        is_duplicate=lead.status == "duplicate",
        eligibility_blocker=lead.eligibility_blocker,
        owner_rejected=lead.status == "rejected",
        branch_count=lead.branch_count,
        legal_form=lead_rules.legal_form(lead.name),
    )


def evaluate(lead: ChennaiLead, now: datetime | None = None) -> ChennaiLead:
    now = now or utcnow()
    f = facts_of(lead)
    problem, solution, services = lead_rules.suggest(lead.industry, f.operations, [s.signal_type for s in f.signals if s.review_status != "rejected"])
    lead.potential_problem, lead.suggested_solution = problem, solution
    lead.suggested_services = services
    lead.category, lead.category_reasons = lead_rules.categorise(f, now)
    labels = [SERVICE_KEYS[k] for k in services if k in SERVICE_KEYS]
    lead.sales_difficulty, lead.difficulty_reasons = lead_rules.sales_difficulty(f, now, labels)
    if lead.category == "D":
        lead.sales_difficulty, lead.difficulty_reasons = "unknown", ["Rejected lead"]
    lead.evidence_confidence = lead_rules.evidence_confidence(f)
    unreviewed = any(s.review_status == "hypothesis" for s in lead.signals)
    lead.next_action = lead_rules.next_action(lead.category, lead.location_verified, lead.industry_strength,
                                              f.has_contact_route, unreviewed)
    return lead


def prescore(lead: ChennaiLead) -> float:
    """Order for selective research only (cheap, explainable). Not a win probability."""
    s = {"strong": 3, "candidate": 2}.get(lead.industry_strength, 0)
    s += 2 if lead.website else 0
    s += 1 if lead.emails else 0
    s += 2 if lead.location_status == chennai.CHENNAI_CITY else 0
    s += 1 if re.search(r"\b(distributors?|wholesale|equipments?|instruments?|biomedical|surgical|systems)\b", lead.name, re.I) else 0
    return float(s)


# ------------------------------------------------------------------------------------------------
# 1–3. Collect from the local Overture file
# ------------------------------------------------------------------------------------------------
def _run_log(db: Session, run: ProspectRun | None, msg: str) -> None:
    if run is not None:
        run.log = [*(run.log or []), msg]
        db.commit()


def overture_rows(path: str | Path) -> list[dict[str, Any]]:
    """Read places inside the Chennai box from the local Overture Parquet file (no network)."""
    from app.overture import connect

    lat0, lon0, lat1, lon1 = chennai.CITY_BBOX
    con = connect()
    sql = f"""
        SELECT id, name, category, basic_category, phones, websites, emails, socials, confidence, operating_status,
               address, locality, postcode, country, brand, lat, lon
        FROM read_parquet(?)
        WHERE lat BETWEEN {lat0} AND {lat1} AND lon BETWEEN {lon0} AND {lon1}
          AND coalesce(country, 'IN') = 'IN'
          AND coalesce(operating_status, 'open') NOT IN ('permanently_closed', 'closed')
          AND coalesce(confidence, 0) >= 0.5
    """
    cur = con.execute(sql, [str(path)])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def candidate_from_row(row: dict[str, Any], approved: list[str]) -> tuple[ChennaiLead | None, str]:
    """Turn one directory row into an unsaved lead, or (None, reason) if it is filtered out."""
    from app.overture import explorer_url

    name = (row.get("name") or "").strip()
    if not name:
        return None, "no name"
    if row.get("brand"):
        return None, "brand/chain outlet"
    # The specific category decides; Overture's broad basic_category (e.g. "supplier_or_distributor") only when it is missing.
    cat = row.get("category") or row.get("basic_category") or ""
    ind = lead_rules.classify_industry(name, cat)
    if ind.industry is None:
        return None, "industry"
    loc = chennai.classify_location(row.get("address"), row.get("locality"), row.get("postcode"), approved=approved)
    if loc.status in (chennai.OUTSIDE, chennai.GCMA_OUTSIDE):
        return None, "location"
    lat, lon = row.get("lat"), row.get("lon")
    src = explorer_url(lat, lon) if lat is not None and lon is not None else "https://explore.overturemaps.org/"
    websites = [w for w in (row.get("websites") or []) if w and not _SOCIAL.search(w)]
    phones = [{"value": p, "source_url": src, "official": False} for p in (row.get("phones") or [])[:3] if p]
    emails = [{"value": e, "source_url": src, "official": False} for e in (row.get("emails") or [])[:2] if e and "@" in e]
    lead = ChennaiLead(
        name=name[:300], normalized_name=normalize_org_name(name)[:300], industry=ind.industry, industry_strength=ind.strength,
        industry_subtype=ind.subtype, industry_reasons=ind.reasons, directory_category=(row.get("category") or None),
        address=row.get("address"), locality=row.get("locality"), pincode=loc.pincode or row.get("postcode"),
        lat=lat, lon=lon, location_status=loc.status, location_verified=False,
        location_basis=f"Directory address (Overture): {loc.reason}. Not yet verified on an official source.",
        website=websites[0] if websites else None, domain=domain_of(websites[0]) if websites else None,
        phones=phones, emails=emails, activity_status="unknown",
        activity_evidence="Listed in the Overture directory (not proof of current activity)",
        operations=[], source="overture", source_ref=f"overture:{row['id']}", source_url=src, status="new",
    )
    lead.signals = []
    lead.prescore = prescore(lead)
    return lead, "ok"


def _near(a: ChennaiLead, b: ChennaiLead, km: float = 0.3) -> bool:
    if None in (a.lat, a.lon, b.lat, b.lon):
        return False
    return abs(a.lat - b.lat) < km / 111 and abs(a.lon - b.lon) < km / 108


def _digits(leads: ChennaiLead) -> set[str]:
    return {re.sub(r"\D", "", p["value"])[-10:] for p in (leads.phones or []) if p.get("value")}


def is_duplicate(a: ChennaiLead, b: ChennaiLead) -> bool:
    """Same normalised name AND (same domain, shared phone, or within ~300 m)."""
    if not a.normalized_name or a.normalized_name != b.normalized_name:
        return False
    return bool((a.domain and a.domain == b.domain) or (_digits(a) & _digits(b)) or _near(a, b))


def collect(db: Session, path: str | Path, *, max_keep: int = 2000, run: ProspectRun | None = None,
            rows: list[dict[str, Any]] | None = None) -> dict[str, int]:
    """Steps 1–3. Idempotent: re-running never duplicates (unique source_ref + duplicate check)."""
    approved = _approved_localities(db)
    rows = rows if rows is not None else overture_rows(path)
    _run_log(db, run, f"Read {len(rows):,} directory listings inside the Chennai box")
    stats = {"read": len(rows), "industry": 0, "location": 0, "other": 0, "duplicates": 0, "new": 0, "existing": 0}
    cands: list[ChennaiLead] = []
    for row in rows:
        lead, why = candidate_from_row(row, approved)
        if lead is None:
            stats["industry" if why == "industry" else "location" if why == "location" else "other"] += 1
            continue
        cands.append(lead)
    cands.sort(key=lambda x: -x.prescore)

    existing = {r.source_ref for r in db.scalars(select(ChennaiLead))}
    by_name: dict[str, list[ChennaiLead]] = {}
    for r in db.scalars(select(ChennaiLead).where(ChennaiLead.status != "duplicate")):
        by_name.setdefault(r.normalized_name, []).append(r)
    for lead in cands:
        if lead.source_ref in existing:
            stats["existing"] += 1
            continue
        if any(is_duplicate(lead, o) for o in by_name.get(lead.normalized_name, [])):
            stats["duplicates"] += 1
            continue
        if stats["new"] >= max_keep:
            break
        evaluate(lead)
        db.add(lead)
        by_name.setdefault(lead.normalized_name, []).append(lead)
        existing.add(lead.source_ref)
        stats["new"] += 1
    db.commit()
    _run_log(db, run, f"Kept {stats['new']:,} new candidates · {stats['industry']:,} not in the two industries · "
                      f"{stats['location']:,} outside Chennai city · {stats['duplicates']:,} duplicates · {stats['existing']:,} already known")
    return stats


# ------------------------------------------------------------------------------------------------
# 4. Official website check (selective)
# ------------------------------------------------------------------------------------------------
def _site_url(website: str) -> str:
    url = website.strip() if re.match(r"^https?://", website.strip(), re.I) else f"http://{website.strip()}"
    return url + "/" if re.match(r"^https?://[^/]+$", url, re.I) else url


def fetch_site_pages(http: SafeHttp, website: str, max_pages: int = 4) -> list[tuple[str, str, str]]:
    """Homepage + up to (max_pages-1) same-site pages likely to hold address/services. Returns [(url, html, text)]."""
    home = http.get(_site_url(website))
    if "html" not in (home.content_type or "html").lower():
        raise FetchError(f"Homepage is {home.content_type}, not a web page")
    pages = [(home.url, home.text, html_to_text(home.text))]
    host = urlsplit(home.url).hostname
    seen = {home.url.rstrip("/")}
    picks: list[str] = []
    for href, label in _LINK.findall(home.text):
        u = urljoin(home.url, href.strip())
        if urlsplit(u).hostname != host or not u.startswith("http") or u.rstrip("/") in seen:
            continue
        if re.search(r"\.(pdf|jpe?g|png|zip|docx?)$", u, re.I):
            continue
        if _SUBPAGE.search(u) or _SUBPAGE.search(html_to_text(label)):
            seen.add(u.rstrip("/"))
            picks.append(u)
    # Contact pages first: they carry the address.
    picks.sort(key=lambda u: 0 if re.search(r"contact|reach|location|branch", u, re.I) else 1)
    for u in picks[: max_pages - 1]:
        try:
            r = http.get(u)
            if "html" in (r.content_type or "html").lower():
                pages.append((r.url, r.text, html_to_text(r.text)))
        except FetchError:
            continue
    return pages


def _official_contacts(pages: list[tuple[str, str, str]], domain: str | None) -> tuple[list[dict], list[dict]]:
    emails: dict[str, dict] = {}
    phones: dict[str, dict] = {}
    for url, html, text in pages:
        for m in re.finditer(r"mailto:([^\"'?\s>]+)", html, re.I):
            e = m.group(1).strip().lower()
            if _EMAIL.fullmatch(e):
                emails.setdefault(e, {"value": e, "source_url": url, "official": True})
        for m in _EMAIL.finditer(text):
            e = m.group(1).lower()
            if not re.search(r"\.(png|jpe?g|gif|webp|svg)$", e) and "example." not in e:
                emails.setdefault(e, {"value": e, "source_url": url, "official": True})
        for m in _PHONE.finditer(text):
            d = re.sub(r"\D", "", m.group(0))[-10:]
            if len(d) == 10:
                phones.setdefault(d, {"value": m.group(0).strip(), "source_url": url, "official": True})
    return list(emails.values())[:4], list(phones.values())[:4]


def verify_website(db: Session, lead: ChennaiLead, http: SafeHttp | None = None) -> ChennaiLead:
    """Check the official website: Chennai-city address, operations, contacts, signals. Never guesses."""
    now = utcnow()
    lead.website_checked_at = now
    if not lead.website:
        lead.website_check_error = "No official website known"
        evaluate(lead, now)
        db.commit()
        return lead
    own = http is None
    http = http or SafeHttp(rate_limit_per_minute=20)
    try:
        pages = fetch_site_pages(http, lead.website)
    except FetchError as exc:
        lead.website_check_error = str(exc)[:300]
        lead.activity_evidence = f"Website could not be loaded on {now:%d %b %Y}: {str(exc)[:150]}"
        evaluate(lead, now)
        db.commit()
        return lead
    finally:
        if own:
            http.close()
    lead.website_check_error = None
    approved = _approved_localities(db)
    all_text = "\n".join(t for _, _, t in pages)

    # Location: first page that shows a Chennai-city address wins.
    best = None
    for url, _, text in pages:
        found = chennai.find_chennai_address(text, approved)
        if found and (best is None or found[0].status == chennai.CHENNAI_CITY):
            best = (found[0], found[1], url)
            if found[0].status == chennai.CHENNAI_CITY:
                break
    if best:
        v, excerpt, url = best
        lead.location_status = v.status
        lead.location_verified = v.status == chennai.CHENNAI_CITY
        lead.location_basis = f"Official website ({now:%d %b %Y}): {v.reason}. Address text: \"{excerpt[:220]}\""
        lead.location_evidence_url = url
        lead.locality = v.locality or lead.locality
        lead.pincode = v.pincode or lead.pincode
    else:
        lead.location_basis = (lead.location_basis or "") + f" Official website checked {now:%d %b %Y}: no Chennai address found."

    # Operations (facts) and industry re-check.
    ops = []
    for key, (label, rx) in lead_rules.OPERATIONS.items():
        for url, _, text in pages:
            m = rx.search(text)
            if m:
                ops.append({"key": key, "label": label, "excerpt": lead_rules._excerpt(text, m), "url": url})
                break
    lead.operations = ops
    ind = lead_rules.classify_industry(lead.name, lead.directory_category, all_text, [o["key"] for o in ops])
    lead.industry, lead.industry_strength, lead.industry_subtype, lead.industry_reasons = ind.industry, ind.strength, ind.subtype, ind.reasons
    m = re.search(r"\b(\d{1,3})\s+branches\b", all_text, re.I)
    lead.branch_count = int(m.group(1)) if m else lead.branch_count

    # Contacts published on the official site (kept alongside directory ones).
    emails, phones = _official_contacts(pages, lead.domain)
    official_e = {e["value"] for e in emails}
    lead.emails = [*emails, *[e for e in lead.emails or [] if e["value"].lower() not in official_e]]
    official_p = {re.sub(r"\D", "", p["value"])[-10:] for p in phones}
    lead.phones = [*phones, *[p for p in lead.phones or [] if re.sub(r"\D", "", p["value"])[-10:] not in official_p]]

    # Activity: an explicit current/previous copyright year or a dated item this year.
    years = [int(y) for y in _YEAR.findall(" ".join(h for _, h, _ in pages))]
    if years and max(years) >= now.year - 1:
        lead.activity_status = "active"
        lead.activity_evidence = f"Website live on {now:%d %b %Y} with © {max(years)}"
    else:
        lead.activity_status = "likely_active"
        lead.activity_evidence = f"Website live on {now:%d %b %Y}" + (f" (latest © {max(years)})" if years else " (no dated content found)")

    # Signal candidates from the site (hypotheses; dated only if a date is written next to them).
    for url, _, text in pages:
        for found in lead_rules.detect_signals(text):
            if found["signal_type"] in ("expansion",) and not re.search(r"new|recent|launch|open", found["excerpt"], re.I):
                continue  # "our dealer network" is a fact about operations, not news
            pos = text.find(found["excerpt"][:40])
            date = lead_rules.find_date_near(text, max(pos, 0), max(pos, 0) + len(found["excerpt"])) if pos >= 0 else None
            _add_signal(db, lead, signal_type=found["signal_type"], excerpt=found["excerpt"], url=url, published_at=date,
                        detected_by="rule", source_name="Official website", title=None)
    lead.last_verified_at = now
    lead.prescore = prescore(lead)
    evaluate(lead, now)
    db.commit()
    return lead


def _add_signal(db: Session, lead: ChennaiLead | None, **kw) -> LeadSignal | None:
    """Insert a signal unless the same (lead, url, type) exists. Returns the new row or None."""
    stmt = select(LeadSignal).where(LeadSignal.url == kw["url"], LeadSignal.signal_type == kw["signal_type"])
    stmt = stmt.where(LeadSignal.lead_id.is_(None)) if lead is None else stmt.where(LeadSignal.lead_id == lead.id)
    if lead is not None and lead.id is None:
        if any(s.url == kw["url"] and s.signal_type == kw["signal_type"] for s in lead.signals):
            return None
    elif db.scalar(stmt) is not None:
        return None
    sig = LeadSignal(strength=lead_rules.SIGNAL_STRENGTH.get(kw["signal_type"], "medium"),
                     review_status="confirmed" if kw.get("detected_by") == "manual" else "hypothesis", **kw)
    if lead is not None:
        lead.signals.append(sig)
    else:
        db.add(sig)
    return sig


def research_batch(db: Session, *, limit: int = 25, http: SafeHttp | None = None, run: ProspectRun | None = None) -> dict[str, int]:
    """Step 4 for the strongest unchecked candidates only."""
    stmt = (select(ChennaiLead)
            .where(ChennaiLead.website.is_not(None), ChennaiLead.website_checked_at.is_(None),
                   ChennaiLead.category != "D", ChennaiLead.status.in_(("new", "reviewing")))
            .order_by(ChennaiLead.prescore.desc(), ChennaiLead.id).limit(limit))
    leads = list(db.scalars(stmt))
    _run_log(db, run, f"Checking {len(leads)} official websites (≤4 pages each, robots.txt respected)…")
    own = http is None
    http = http or SafeHttp(rate_limit_per_minute=20)
    stats = {"checked": 0, "verified_chennai": 0, "failed": 0}
    try:
        for lead in leads:
            if run is not None:
                db.refresh(run)
                if run.status == "stopping":
                    break
            verify_website(db, lead, http)
            stats["checked"] += 1
            stats["verified_chennai"] += int(lead.location_verified)
            stats["failed"] += int(bool(lead.website_check_error))
    finally:
        if own:
            http.close()
    _run_log(db, run, f"✓ Checked {stats['checked']} websites: {stats['verified_chennai']} show a Chennai-city address, "
                      f"{stats['failed']} could not be loaded")
    return stats


# ------------------------------------------------------------------------------------------------
# 5. News signals
# ------------------------------------------------------------------------------------------------
def scan_news(db: Session, *, feeds: dict[str, str] | None = None, http: SafeHttp | None = None, max_age_days: int = 90,
              run: ProspectRun | None = None) -> dict[str, Any]:
    from app.big_projects import fetch_feed

    feeds = feeds or CHENNAI_FEEDS
    own = http is None
    http = http or SafeHttp(rate_limit_per_minute=20)
    cutoff = utcnow() - timedelta(days=max_age_days)
    names = [(lead, f" {lead.normalized_name} ") for lead in db.scalars(select(ChennaiLead).where(ChennaiLead.status != "duplicate"))
             if len(lead.normalized_name.split()) >= 2 or len(lead.normalized_name) >= 8]
    stats: dict[str, Any] = {"feeds_ok": 0, "feeds_failed": [], "articles": 0, "relevant": 0, "matched": 0, "new_signals": 0}
    touched: set[int] = set()
    try:
        for fname, url in feeds.items():
            try:
                items = fetch_feed(http, url)
            except FetchError as exc:
                stats["feeds_failed"].append(f"{fname}: {str(exc)[:120]}")
                continue
            stats["feeds_ok"] += 1
            for it in items:
                stats["articles"] += 1
                if not it.get("link"):
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
                hits = [lead for lead, n in names if n in norm]
                for f in found:
                    for lead in hits or [None]:
                        sig = _add_signal(db, lead, signal_type=f["signal_type"], excerpt=f["excerpt"], url=it["link"],
                                          published_at=pub, detected_by="rule", source_name=fname, title=it["title"][:500])
                        if sig is not None:
                            stats["new_signals"] += 1
                            if lead is not None:
                                touched.add(lead.id)
                stats["matched"] += int(bool(hits))
        for lead in db.scalars(select(ChennaiLead).where(ChennaiLead.id.in_(touched))):
            evaluate(lead)
        db.commit()
    finally:
        if own:
            http.close()
    _run_log(db, run, f"✓ News: {stats['articles']} articles from {stats['feeds_ok']} feeds · {stats['relevant']} relevant Chennai items · "
                      f"{stats['matched']} matched a lead · {stats['new_signals']} new signals")
    return stats


# ------------------------------------------------------------------------------------------------
# Owner actions
# ------------------------------------------------------------------------------------------------
def add_manual_lead(db: Session, data: dict[str, Any]) -> ChennaiLead:
    """Owner adds a company they found (exhibitor list, association directory, LinkedIn post they read…)."""
    approved = _approved_localities(db)
    name = data["name"].strip()
    website = (data.get("website") or "").strip() or None
    loc = chennai.classify_location(data.get("address"), approved=approved)
    evidence_url = (data.get("location_evidence_url") or "").strip() or None
    ind = lead_rules.classify_industry(name, data.get("category_hint"))
    industry = data.get("industry") or ind.industry
    src = (data.get("source_url") or evidence_url or website or "").strip()
    if not src:
        raise ValueError("A source URL (where you found this company) is required")
    lead = ChennaiLead(
        name=name[:300], normalized_name=normalize_org_name(name)[:300], industry=industry,
        industry_strength="candidate" if industry else "none",
        industry_subtype=ind.subtype, industry_reasons=(["Industry set by the owner"] if data.get("industry") else ind.reasons),
        address=data.get("address"), locality=loc.locality, pincode=loc.pincode, location_status=loc.status,
        location_verified=bool(evidence_url and loc.status == chennai.CHENNAI_CITY),
        location_basis=(f"Owner-entered address: {loc.reason}" + (f". Checked on {evidence_url}" if evidence_url else ". Not yet verified")),
        location_evidence_url=evidence_url, website=website, domain=domain_of(website) if website else None,
        phones=[{"value": data["phone"], "source_url": data.get("contact_source_url") or src, "official": bool(data.get("contact_source_url"))}] if data.get("phone") else [],
        emails=[{"value": data["email"], "source_url": data.get("contact_source_url") or src, "official": bool(data.get("contact_source_url"))}] if data.get("email") else [],
        activity_status="unknown", source="manual", source_ref=f"manual:{uuid.uuid4().hex}",
        source_url=src, status="new", notes=data.get("notes"),
    )
    lead.signals = []
    # Owner-entered leads often lack a phone or coordinates to compare, so the same name is enough to stop.
    dup = db.scalar(select(ChennaiLead).where(or_(ChennaiLead.normalized_name == lead.normalized_name,
                                                  and_(ChennaiLead.domain.is_not(None), ChennaiLead.domain == lead.domain)),
                                              ChennaiLead.status != "duplicate"))
    if dup is not None:
        raise ValueError(f"Looks like a duplicate of lead #{dup.id} ({dup.name})")
    lead.prescore = prescore(lead)
    evaluate(lead)
    db.add(lead)
    db.commit()
    return lead


def add_signal(db: Session, lead: ChennaiLead, *, signal_type: str, url: str, excerpt: str, published_at: datetime | None,
               title: str | None, actor: str) -> LeadSignal:
    if signal_type not in lead_rules.SIGNAL_LABEL:
        raise ValueError("Unknown signal type")
    if not re.match(r"^https?://", url or ""):
        raise ValueError("A source URL (http/https) is required")
    sig = _add_signal(db, lead, signal_type=signal_type, url=url, excerpt=excerpt.strip()[:2000], published_at=published_at,
                      detected_by="manual", source_name="Owner", title=title)
    if sig is None:
        raise ValueError("This signal is already recorded")
    sig.reviewed_by = actor
    evaluate(lead)
    db.commit()
    return sig


def review_signal(db: Session, sig: LeadSignal, decision: str, actor: str, lead: ChennaiLead | None = None) -> LeadSignal:
    if decision not in ("confirmed", "rejected", "hypothesis"):
        raise ValueError("decision must be confirmed, rejected or hypothesis")
    if lead is not None and sig.lead_id is None:  # attach a market-news item to a company
        sig.lead_id = lead.id
    sig.review_status = decision
    sig.reviewed_by = actor
    db.flush()
    target = lead or (db.get(ChennaiLead, sig.lead_id) if sig.lead_id else None)
    if target is not None:
        db.refresh(target)
        evaluate(target)
    db.commit()
    return sig


# ------------------------------------------------------------------------------------------------
# Brief + outreach draft (deterministic template; nothing is sent)
# ------------------------------------------------------------------------------------------------
QUESTIONS = {
    lead_rules.WHOLESALE: [
        "How do dealers/retailers place orders today (phone, WhatsApp, email, salesperson)?",
        "How many orders a day, and how many SKUs and delivery routes?",
        "How do you track stock across godowns/branches, and how often does it not match?",
        "Which accounting/ERP system do you use (e.g. Tally), and is it connected to orders and dispatch?",
        "How do you follow up on outstanding payments from dealers?",
        "Who decides on new software, and is there a budget or timeline?",
    ],
    lead_rules.EQUIPMENT: [
        "How do customers raise service requests today, and how are technicians assigned?",
        "How many field technicians and service calls per month?",
        "How do you track AMC/warranty contracts and renewal dates?",
        "How do customers get status updates on a service call?",
        "Which systems do you already use (accounting, CRM, spreadsheets)?",
        "Who decides on new software, and is there a budget or timeline?",
    ],
}


def brief(lead: ChennaiLead, sender_name: str = "", sender_link: str = "") -> dict[str, Any]:
    confirmed = [s for s in lead.signals if s.review_status == "confirmed"]
    facts: list[dict[str, str | None]] = [
        {"fact": f"Industry: {lead_rules.INDUSTRY_LABEL.get(lead.industry or '', 'unknown')}" + (f" ({lead.industry_subtype})" if lead.industry_subtype else ""),
         "source": lead.source_url},
        {"fact": f"Location: {lead.location_basis}", "source": lead.location_evidence_url or lead.source_url},
        {"fact": f"Activity: {lead.activity_evidence or 'unknown'}", "source": lead.website},
    ]
    for o in lead.operations or []:
        facts.append({"fact": f"{o['label']}: \"{o['excerpt'][:180]}\"", "source": o.get("url")})
    for s in lead.signals:
        if s.review_status == "rejected":
            continue
        when = f"{s.published_at:%d %b %Y}" if s.published_at else "date unknown"
        state = "confirmed" if s.review_status == "confirmed" else "unconfirmed"
        label = lead_rules.SIGNAL_LABEL.get(s.signal_type, s.signal_type)
        facts.append({"fact": f"{label} ({when} · {state}): \"{s.excerpt[:180]}\"", "source": s.url})
    why = [lead.potential_problem] if lead.potential_problem else []
    why += [f"{lead_rules.SIGNAL_LABEL.get(s.signal_type)}: {s.url}" for s in confirmed]
    me = f"I'm {sender_name} from Inferago Tech Services" if sender_name else "I'm writing from Inferago Tech Services"
    hook = (f"I read about {confirmed[0].title or 'your recent update'} ({confirmed[0].url})." if confirmed
            else "I came across your company while looking at Chennai " + ("distributors" if lead.industry == lead_rules.WHOLESALE else "equipment service companies") + ".")
    offer = ("We build simple order, stock and dispatch tools for distributors, connected to the accounting software they already use."
             if lead.industry == lead_rules.WHOLESALE else
             "We build simple field-service tools: service tickets, technician scheduling and AMC/warranty reminders.")
    draft = (f"Hello {lead.name} team,\n\n{me}, a small Udyam-registered software firm in Tamil Nadu. {hook}\n\n{offer} "
             "I don't know yet whether this is a problem for you, so I'd like to ask a few questions first — a 15-minute call, "
             "and if there's a fit, a small paid pilot rather than a big project.\n\nWould that be useful? If not, just say so and "
             "I won't follow up." + (f"\n\nAbout us: {sender_link}" if sender_link else "") + "\n\nRegards")
    return {
        "research_brief": facts,
        "why_inferago": why or ["No confirmed need yet — treat as research."],
        "recommended_solution": lead.suggested_solution,
        "services": [SERVICE_KEYS.get(k, k) for k in lead.suggested_services or []],
        "outreach_draft": lead.outreach_draft or draft,
        "draft_is_edited": bool(lead.outreach_draft),
        "qualification_questions": QUESTIONS.get(lead.industry or "", []),
        "approval": {"approved_by": lead.outreach_approved_by, "approved_at": lead.outreach_approved_at},
        "notice": "Nothing is sent automatically. Edit, approve, then contact them yourself.",
    }
