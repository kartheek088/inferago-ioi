"""Finding social sellers: permitted sources only, plus the import the owner drives themselves.

Every candidate — whether it came from a search result, a public market page or a pasted link — goes
through `ingest`, so all of them get the same category, Chennai and duplicate checks.

What is deliberately NOT here: reading a private profile, a DM, a WhatsApp chat, a group's members,
a follower list, or anything behind a login or CAPTCHA. A source that would need access IOI does not
have reports itself unavailable instead.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.ioi3.models import SOCIAL, Campaign, Company, RawItem, SocialAccount
from app.ioi3.social import categories as cat
from app.ioi3.social import core
from app.ioi3.social import geo as geomod
from app.ioi3.social import platforms as plat
from app.normalize import domain_of, normalize_org_name

_EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RX = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b")


@dataclass
class Candidate:
    source_key: str
    external_id: str
    source_url: str
    name: str
    links: list[str] = field(default_factory=list)  # profile / catalogue / website links found with the candidate
    description: str | None = None  # bio or listing text, in the seller's own words where possible
    address_text: str | None = None
    locality: str | None = None
    website: str | None = None
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    category_hint: str | None = None  # owner-chosen category
    geo_evidence: list[tuple[str, str]] = field(default_factory=list)  # (basis, text)
    note: str | None = None
    followers: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    outcome: str
    # accepted | outside_chennai | not_social_category | duplicate | no_name | no_profile | already_seen
    company: Company | None = None
    reason: str = ""


def _seen(db: Session, campaign_id: int, c: Candidate) -> bool:
    return db.scalar(select(RawItem.id).where(RawItem.campaign_id == campaign_id, RawItem.source_key == c.source_key,
                                              RawItem.external_id == c.external_id)) is not None


def _raw(db: Session, campaign_id: int, job_id: int | None, c: Candidate, outcome: str, company: Company | None) -> None:
    db.add(RawItem(campaign_id=campaign_id, job_id=job_id, source_key=c.source_key, external_id=c.external_id[:200],
                   source_url=c.source_url, title=c.name[:500], payload=c.payload or {}, outcome=outcome,
                   company_id=company.id if company is not None and company.id else None))


def find_existing(db: Session, campaign_id: int, refs: list[plat.ProfileRef], name: str,
                  domain: str | None, phones: set[str]) -> Company | None:
    """A platform handle identifies a seller. Name similarity alone never merges two sellers."""
    for r in refs:
        hit = db.scalar(select(Company).join(SocialAccount, SocialAccount.company_id == Company.id)
                        .where(Company.campaign_id == campaign_id, Company.review_status != "duplicate",
                               SocialAccount.platform == r.platform, SocialAccount.handle == r.handle))
        if hit is not None:
            return hit
    if domain:
        hit = db.scalar(select(Company).where(Company.campaign_id == campaign_id, Company.domain == domain,
                                             Company.review_status != "duplicate"))
        if hit is not None:
            return hit
    if phones:
        for b in db.scalars(select(Company).where(Company.campaign_id == campaign_id,
                                                  Company.normalized_name == normalize_org_name(name),
                                                  Company.review_status != "duplicate")):
            if phones & {re.sub(r"\D", "", x.value)[-10:] for x in b.contacts if x.kind == "phone"}:
                return b
    return None


def cross_channel_match(db: Session, c: Candidate, domain: str | None, phones: set[str]) -> Company | None:
    """The same business may legitimately appear in both channels. Note it rather than merge it."""
    from app.ioi3.models import B2B

    q = select(Company).where(Company.channel == B2B, Company.review_status != "duplicate")
    if domain:
        hit = db.scalar(q.where(Company.domain == domain))
        if hit is not None:
            return hit
    if phones:
        for b in db.scalars(q.where(Company.normalized_name == normalize_org_name(c.name))):
            if phones & {re.sub(r"\D", "", x.value)[-10:] for x in b.contacts if x.kind == "phone"}:
                return b
    return None


def ingest(db: Session, campaign: Campaign, cand: Candidate, *, job_id: int | None = None,
           require_category: bool = True, is_test: bool = False) -> IngestResult:
    """Check one social candidate and store it if it belongs in the campaign. Caller commits."""
    name = (cand.name or "").strip()
    if not name:
        return IngestResult("no_name", reason="No business name")
    if _seen(db, campaign.id, cand):
        return IngestResult("already_seen")

    refs: list[plat.ProfileRef] = []
    rejected_links: list[str] = []
    for link in cand.links:
        try:
            refs.append(plat.parse(link))
        except plat.NotAProfile as exc:
            rejected_links.append(f"{link} — {exc}")
    website = cand.website or next((r.url for r in refs if r.platform == plat.OTHER), None)
    if not refs and not website:
        return IngestResult("no_profile", reason="No public profile, catalogue or website link to work from. "
                                                + ("; ".join(rejected_links[:2]) if rejected_links else ""))

    # What do they sell? The owner's choice wins; otherwise their own words decide.
    match = cat.classify_category(name, cand.description, cand.payload.get("category"))
    category = cand.category_hint or match.category
    if category is None and require_category:
        return IngestResult("not_social_category", reason=match.reasons[0] if match.reasons else "No category match")
    if category is not None and category not in (core.campaign_settings(campaign).get("categories") or cat.CATEGORIES):
        return IngestResult("not_social_category", reason=f"{cat.CATEGORY_LABEL.get(category, category)} is switched off for this campaign")

    # Where do they operate? Evidence from the business itself only (hashtags never count).
    approved = core.campaign_settings(campaign).get("approved_localities") or []
    ev = [geomod.GeoEvidence(basis, text) for basis, text in cand.geo_evidence if text]
    if cand.address_text:
        ev.append(geomod.GeoEvidence("profile_location", cand.address_text, cand.source_url))
    if cand.locality and not cand.address_text:
        ev.append(geomod.GeoEvidence("profile_location", cand.locality, cand.source_url))
    verdict = geomod.classify(ev, approved=approved)
    if verdict.confidence == geomod.OUTSIDE:
        _raw(db, campaign.id, job_id, cand, "outside_chennai", None)
        return IngestResult("outside_chennai", reason=verdict.reason)

    domain = domain_of(website) if website else None
    phones = {p for p in (plat.normalise_phone(x) for x in cand.phones) if p}
    phones |= {r.handle for r in refs if r.platform == plat.WHATSAPP}
    existing = find_existing(db, campaign.id, refs, name, domain, phones)
    if existing is not None:
        for r in refs:  # a newly found account still enriches the seller we already have
            core.add_account(existing, r, source_url=cand.source_url)
        for p in cand.phones:
            core.add_contact(existing, kind="phone", value=p, source_url=cand.source_url, official=False)
        core.evaluate(existing)
        _raw(db, campaign.id, job_id, cand, "duplicate", existing)
        return IngestResult("duplicate", existing, f"Same seller as #{existing.id}")

    c = core.new_company(campaign.id, name=name, source_key=cand.source_key,
                         source_ref=f"{cand.source_key}:{cand.external_id}", source_url=cand.source_url, is_test=is_test)
    db.add(c)
    db.flush()
    p = core.ensure_profile(c)
    p.product_category = category
    p.category_reasons = ["Category chosen by you"] if cand.category_hint else match.reasons
    p.products_excerpt = match.excerpt or (cand.description or None) and cand.description[:600]
    c.website, c.domain = website, domain
    c.address = cand.address_text
    core.set_geo(c, verdict)

    primary = True
    for r in refs:
        if r.platform == plat.WHATSAPP:
            core.add_contact(c, kind="phone", value=f"+91{r.handle}", source_url=cand.source_url, official=True,
                             label="WhatsApp Business (published by them)")
        core.add_account(c, r, source_url=cand.source_url, profile_name=name, bio=cand.description,
                         # A follower count belongs to the account it was counted on. Recorded, never scored.
                         followers=cand.followers if r.platform in (plat.INSTAGRAM, plat.FACEBOOK) else None,
                         catalogue_url=next((x for x in cand.links if plat.catalogue_hint(x)), None), primary=primary)
        primary = False

    src_name = core.SOURCE_LABEL.get(cand.source_key, cand.source_key)
    core.add_fact(c, kind="identity", key="listing", state="source_verified", source_url=cand.source_url,
                  source_name=src_name, reliability="low" if cand.source_key == "public_search" else "medium",
                  statement=f"Found via {src_name}" + (f": {name}" if name else ""))
    for basis, text in cand.geo_evidence:
        if geomod.BASES.get(basis, ("weak", ""))[0] == "weak":
            core.add_fact(c, kind="note", key="weak_location_evidence", state="unknown",
                          statement=geomod.BASES[basis][1], excerpt=text[:300], source_url=cand.source_url,
                          source_name=src_name)
    if cand.note:
        core.add_fact(c, kind="note", state="source_verified", statement=cand.note[:1000], source_url=cand.source_url,
                      source_name=src_name, detected_by="owner")
    core.add_fact(c, kind="tools", key="current_software", state="unknown",
                  statement="Whether they already use anything to track orders")

    for ph in cand.phones[:3]:
        core.add_contact(c, kind="phone", value=ph, source_url=cand.source_url, official=False)
    for em in cand.emails[:2]:
        if "@" in em:
            core.add_contact(c, kind="email", value=em, source_url=cand.source_url, official=False)

    # Order complexity and activity signals from whatever text came with the candidate.
    blob = "\n".join(t for t in (cand.description, cand.note) if t)
    if blob:
        keys = set()
        for f in cat.detect_complexity(blob, cand.source_url):
            keys.add(f.key)
            core.add_fact(c, kind="workflow", key=f.key, state="source_verified", statement=f.label,
                          excerpt=f.excerpt, source_url=cand.source_url, source_name=src_name, reliability="medium")
        p.complexity_keys = sorted(keys)
        for s in cat.detect_signals(blob, cand.source_url):
            core.add_activity(c, signal_type=s.key, statement=s.label, url=cand.source_url,
                              indicator_class=s.indicator_class, excerpt=s.excerpt, source_name=src_name,
                              platform=refs[0].platform if refs else None)

    setup = cat.classify_setup(platforms={r.platform for r in refs}, website_text=None, website=website,
                               catalogue_url=None, bio_text=cand.description)
    p.sales_setup, p.sales_setup_reason = setup.setup, setup.reason
    p.order_channels, p.workflow_gaps, p.known_tools = setup.order_channels, setup.gaps, setup.tools

    other = cross_channel_match(db, cand, domain, phones)
    if other is not None:
        core.add_fact(c, kind="note", key="cross_channel", state="source_verified",
                      statement=f"The same business is also tracked in the B2B pipeline as #{other.id} ({other.name}). "
                                "The two records are kept separate on purpose; contact them once.",
                      source_url=cand.source_url, source_name="IOI")

    c.description = (cat.CATEGORY_LABEL.get(category, "Social seller") if category else "Social seller")
    if cand.description:
        c.description += f" — {cand.description[:200]}"
    c.prescore = core.prescore(c)
    core.evaluate(c)
    _raw(db, campaign.id, job_id, cand, "accepted", c)
    return IngestResult("accepted", c)


# ------------------------------------------------------------------------------------------------
# Source E — the owner adds a profile, catalogue or website link (§8E). Always available.
# ------------------------------------------------------------------------------------------------
def add_profile(db: Session, campaign: Campaign, data: dict[str, Any]) -> IngestResult:
    """Add one seller from a pasted public link. The one source that never depends on an API."""
    link = (data.get("link") or "").strip()
    if not link:
        raise ValueError("Paste a public profile link, an @handle, a catalogue link or a website.")
    ref = plat.parse(link)  # raises NotAProfile with a plain reason
    extra = [x.strip() for x in (data.get("other_links") or "").replace(",", "\n").split("\n") if x.strip()]
    name = (data.get("name") or "").strip() or (ref.handle if ref.platform != plat.OTHER else ref.handle.split("/")[0])
    geo_ev: list[tuple[str, str]] = []
    for basis in ("profile_location", "delivery_area", "pickup_point", "event_listing"):
        if data.get(basis):
            geo_ev.append((basis, str(data[basis])))
    if data.get("owner_confirmed_locality"):
        geo_ev.append(("owner", str(data["owner_confirmed_locality"])))
    cand = Candidate(
        source_key="manual_profile", external_id=f"{ref.platform}:{ref.handle}"[:200],
        source_url=data.get("source_url") or ref.url, name=name, links=[ref.url, *extra],
        description=(data.get("description") or data.get("bio") or None),
        address_text=(data.get("address") or None), locality=(data.get("locality") or None),
        website=(data.get("website") or None),
        phones=[x for x in [data.get("phone")] if x], emails=[x for x in [data.get("email")] if x],
        category_hint=(data.get("category") or None), geo_evidence=geo_ev, note=(data.get("note") or None),
        payload={k: v for k, v in data.items() if k != "note"})
    # The owner chose to add this seller, so a category is not required up front.
    r = ingest(db, campaign, cand, require_category=False)
    db.commit()
    if r.outcome == "accepted":
        core.mark_source_ok(db, "manual_profile", records=1)
    return r


CSV_COLUMNS = ["name", "link", "other_links", "category", "description", "address", "locality", "phone", "email",
               "website", "delivery_area", "source_url", "note"]


def import_csv(db: Session, campaign: Campaign, text: str, *, default_source_url: str | None = None) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text))
    cols = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
    if "link" not in cols and "name" not in cols:
        raise ValueError("The CSV needs a header row with at least a 'link' or 'name' column. Columns: "
                         + ", ".join(CSV_COLUMNS))
    stats: dict[str, Any] = {"rows": 0, "accepted": 0, "outside_chennai": 0, "not_social_category": 0, "duplicate": 0,
                             "no_name": 0, "no_profile": 0, "already_seen": 0, "errors": []}
    for i, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        stats["rows"] += 1
        links = [row[k] for k in ("link", "website", "other_links") if row.get(k)]
        links = [x for part in links for x in re.split(r"[,\s]+", part) if x]
        if not links:
            stats["no_profile"] += 1
            stats["errors"].append(f"Row {i}: no profile, catalogue or website link")
            continue
        src = row.get("source_url") or default_source_url or links[0]
        refs_ok = False
        for link in links:
            try:
                plat.parse(link)
                refs_ok = True
                break
            except plat.NotAProfile:
                continue
        if not refs_ok:
            stats["no_profile"] += 1
            stats["errors"].append(f"Row {i}: no usable public profile link")
            continue
        geo_ev = [("delivery_area", row["delivery_area"])] if row.get("delivery_area") else []
        category = row.get("category") or None
        if category and category not in cat.CATEGORIES:
            category = next((k for k, v in cat.CATEGORY_LABEL.items() if category.lower() in v.lower()), None)
        cand = Candidate(source_key="csv_import",
                         external_id=f"{row.get('link') or row.get('name','')}"[:200].lower(), source_url=src,
                         name=row.get("name") or "", links=links, description=row.get("description") or None,
                         address_text=row.get("address") or None, locality=row.get("locality") or None,
                         website=row.get("website") or None,
                         phones=[row["phone"]] if row.get("phone") else [],
                         emails=[row["email"]] if row.get("email") else [], category_hint=category,
                         geo_evidence=geo_ev, note=row.get("note") or None, payload=row)
        if not cand.name:
            try:
                cand.name = plat.parse(links[0]).handle
            except plat.NotAProfile:
                pass
        r = ingest(db, campaign, cand, require_category=False)
        stats[r.outcome] = stats.get(r.outcome, 0) + 1
    db.commit()
    core.mark_source_ok(db, "csv_import", records=stats["rows"], freshness=f"Last import {utcnow():%d %b %Y}")
    db.commit()
    return stats


# ------------------------------------------------------------------------------------------------
# Source B — public Chennai market / exhibitor pages the owner authorises (§8B)
# ------------------------------------------------------------------------------------------------
_SELLER_NEAR_RX = re.compile(r"@([A-Za-z0-9._]{3,30})")


def sellers_from_market_page(url: str, html: str, text: str) -> list[Candidate]:
    """Seller names and profile links that a public market/exhibitor page publishes."""
    out: list[Candidate] = []
    seen: set[str] = set()
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", html, re.I | re.S):
        href, label = m.group(1).strip(), re.sub(r"<[^>]+>", " ", m.group(2))
        label = re.sub(r"\s+", " ", label).strip()
        if not plat.is_social_link(href):
            continue
        try:
            ref = plat.parse(href)
        except plat.NotAProfile:
            continue
        if ref.handle in seen:
            continue
        seen.add(ref.handle)
        window = re.sub(r"\s+", " ", text[max(0, text.find(label) - 200): text.find(label) + 300]) if label else ""
        out.append(Candidate(source_key="market_listings", external_id=f"{ref.platform}:{ref.handle}",
                             source_url=url, name=label or ref.handle, links=[ref.url],
                             description=window[:600] or None,
                             geo_evidence=[("event_listing", f"Listed as a seller at a Chennai event: {window[:200]}")],
                             payload={"page": url, "label": label}))
    # Handles written as plain text (@shopname) with no link.
    for m in _SELLER_NEAR_RX.finditer(text):
        h = m.group(1).lower()
        if h in seen or len(h) < 4:
            continue
        seen.add(h)
        window = re.sub(r"\s+", " ", text[max(0, m.start() - 160): m.end() + 200])
        out.append(Candidate(source_key="market_listings", external_id=f"instagram:{h}", source_url=url,
                             name=h, links=[f"https://www.instagram.com/{h}/"], description=window[:600],
                             geo_evidence=[("event_listing", f"Named as a seller at a Chennai event: {window[:200]}")],
                             payload={"page": url, "handle": h}))
    return out


def collect_market_pages(db: Session, campaign: Campaign, http_like, pages: list[str], *, limit: int,
                         job_id: int | None = None, progress: Callable[[str, dict], None] | None = None,
                         should_stop: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Read the public market/exhibitor pages the owner authorised and ingest the sellers they name."""
    from app.normalize import html_to_text

    stats: dict[str, Any] = {"pages_read": 0, "pages_failed": 0, "found": 0, "processed": 0, "accepted": 0,
                             "duplicate": 0, "outside_chennai": 0, "not_social_category": 0, "no_profile": 0,
                             "already_seen": 0, "errors": []}
    cands: list[Candidate] = []
    for url in pages:
        if should_stop and should_stop():
            break
        try:
            res = http_like.get(url)
            html = res.text
            cands += sellers_from_market_page(url, html, html_to_text(html))
            stats["pages_read"] += 1
        except Exception as exc:  # noqa: BLE001 — one bad page must not stop the rest
            stats["pages_failed"] += 1
            stats["errors"].append(f"{url}: {str(exc)[:160]}")
    stats["found"] = len(cands)
    for cand in cands[:limit]:
        if should_stop and should_stop():
            break
        r = ingest(db, campaign, cand, job_id=job_id, require_category=True)
        db.commit()
        stats[r.outcome] = stats.get(r.outcome, 0) + 1
        stats["processed"] += 1
        if progress:
            progress(f"Checking sellers from market pages — {stats['processed']} of {min(len(cands), limit)}", stats)
    return stats
