"""Finding businesses: Overture places (local open-data file), authorised CSV import, manual entry.

All three go through `ingest`, so every candidate gets the same industry, Chennai and duplicate checks.
Out-of-scope businesses never become companies (only a provenance row in ioi_raw_items).
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import chennai, lead_rules
from app.config import BACKEND_DIR
from app.db import utcnow
from app.ioi3 import core
from app.ioi3.models import Campaign, Company, RawItem
from app.normalize import domain_of

MAPS_DIR = BACKEND_DIR / "data" / "maps"
_SOCIAL = re.compile(r"facebook\.com|instagram\.com|linkedin\.com|twitter\.com|x\.com|youtube\.com|wa\.me|whatsapp|justdial|indiamart", re.I)


@dataclass
class Candidate:
    source_key: str
    external_id: str
    source_url: str
    name: str
    category: str | None = None
    address: str | None = None
    locality: str | None = None
    postcode: str | None = None
    lat: float | None = None
    lon: float | None = None
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    websites: list[str] = field(default_factory=list)
    brand: str | None = None
    industry_hint: str | None = None  # owner-chosen industry (manual/CSV)
    location_evidence_url: str | None = None  # owner says: this official page shows the address
    note: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    outcome: str  # accepted | outside_chennai | wrong_industry | duplicate | chain_outlet | no_name | already_seen
    company: Company | None = None
    reason: str = ""


def _seen(db: Session, campaign_id: int, cand: Candidate) -> bool:
    return db.scalar(select(RawItem.id).where(RawItem.campaign_id == campaign_id, RawItem.source_key == cand.source_key,
                                              RawItem.external_id == cand.external_id)) is not None


def _raw(db: Session, campaign_id: int, job_id: int | None, cand: Candidate, outcome: str, company: Company | None) -> None:
    db.add(RawItem(campaign_id=campaign_id, job_id=job_id, source_key=cand.source_key, external_id=cand.external_id[:200],
                   source_url=cand.source_url, title=cand.name[:500], payload=cand.payload or {}, outcome=outcome,
                   company_id=company.id if company is not None and company.id else None))


def ingest(db: Session, campaign: Campaign, cand: Candidate, *, job_id: int | None = None, is_test: bool = False) -> IngestResult:
    """Check one candidate and store it if it belongs in the campaign. Caller commits."""
    name = (cand.name or "").strip()
    if not name:
        return IngestResult("no_name", reason="No business name")
    if _seen(db, campaign.id, cand):
        return IngestResult("already_seen")
    if cand.brand:
        _raw(db, campaign.id, job_id, cand, "chain_outlet", None)
        return IngestResult("chain_outlet", reason=f"Outlet of the brand {cand.brand}")
    ind = lead_rules.classify_industry(name, cand.category)
    industry = cand.industry_hint or ind.industry
    if industry not in campaign.industries:
        # Not stored as a raw row: the directory holds tens of thousands of unrelated businesses.
        return IngestResult("wrong_industry", reason="; ".join(ind.reasons))
    approved = core.campaign_settings(campaign).get("approved_localities") or []
    # The street address outranks a directory "locality" field (directories often label suburbs and even
    # other towns "Chennai"): if the address itself is outside the city, the business is out of scope.
    addr_only = chennai.classify_location(cand.address, cand.postcode, approved=approved)
    verdict = addr_only if addr_only.status in (chennai.OUTSIDE, chennai.GCMA_OUTSIDE) else \
        chennai.classify_location(cand.address, cand.locality, cand.postcode, approved=approved)
    if verdict.status in (chennai.OUTSIDE, chennai.GCMA_OUTSIDE):
        _raw(db, campaign.id, job_id, cand, "outside_chennai", None)
        return IngestResult("outside_chennai", reason=verdict.reason)

    websites = [w for w in cand.websites if w and not _SOCIAL.search(w)]
    website = websites[0] if websites else None
    domain = domain_of(website) if website else None
    phones = {re.sub(r"\D", "", p)[-10:] for p in cand.phones if p}
    existing = core.find_existing(db, campaign.id, name, domain, phones, cand.lat, cand.lon)
    if existing is not None:
        for p in cand.phones:
            core.add_contact(existing, kind="phone", value=p, source_url=cand.source_url, official=False)
        _raw(db, campaign.id, job_id, cand, "duplicate", existing)
        return IngestResult("duplicate", existing, f"Same business as #{existing.id}")

    c = core.new_company(campaign.id, name=name, source_key=cand.source_key, source_ref=f"{cand.source_key}:{cand.external_id}",
                         source_url=cand.source_url, is_test=is_test)
    c.industry = industry
    c.industry_strength = "candidate"
    c.industry_subtype = ind.subtype
    c.industry_reasons = ["Industry chosen by you"] if cand.industry_hint else ind.reasons
    c.directory_category = cand.category
    c.website, c.domain = website, domain
    c.address, c.locality, c.pincode, c.lat, c.lon = cand.address, verdict.locality or cand.locality, verdict.pincode or cand.postcode, cand.lat, cand.lon
    basis = "owner" if cand.location_evidence_url and verdict.status == chennai.CHENNAI_CITY else "directory"
    core.add_location(c, address=cand.address, verdict=verdict, basis=basis,
                      evidence_url=cand.location_evidence_url or cand.source_url, lat=cand.lat, lon=cand.lon)
    c.location_confidence = core.location_confidence(verdict.status, basis)
    c.location_reason = verdict.reason + (" (checked by you)" if basis == "owner" else " (directory; not yet verified)")
    src_name = {"overture_places": "Overture Maps", "csv_import": "Your CSV import", "manual": "Added by you"}.get(cand.source_key, cand.source_key)
    core.add_fact(c, kind="identity", key="listing", state="source_verified", source_url=cand.source_url, source_name=src_name,
                  reliability="low" if cand.source_key == "overture_places" else "medium",
                  statement=f"Listed in {src_name}" + (f" as '{cand.category}'" if cand.category else ""))
    if cand.note:
        core.add_fact(c, kind="note", state="source_verified", statement=cand.note[:1000], source_url=cand.source_url,
                      source_name=src_name, detected_by="owner")
    core.add_fact(c, kind="tools", key="current_software", state="unknown",
                  statement="Whether they already use software for " + ("service tracking" if industry == lead_rules.EQUIPMENT else "orders and dispatch"))
    for p in cand.phones[:3]:
        core.add_contact(c, kind="phone", value=p, source_url=cand.source_url, official=False)
    for e in cand.emails[:2]:
        if "@" in e:
            core.add_contact(c, kind="email", value=e, source_url=cand.source_url, official=False)
    c.description = f"{lead_rules.INDUSTRY_LABEL.get(industry, industry)} (from directory listing; not yet researched)"
    c.prescore = core.prescore(c)
    core.evaluate(c)
    db.add(c)
    db.flush()
    _raw(db, campaign.id, job_id, cand, "accepted", c)
    return IngestResult("accepted", c)


# ------------------------------------------------------------------------------------------------
# Overture connector
# ------------------------------------------------------------------------------------------------
def overture_file() -> Path | None:
    files = sorted(MAPS_DIR.glob("overture-india-*.parquet"))
    return files[-1] if files else None


def overture_candidates(path: Path) -> list[Candidate]:
    """Real records from the local Overture Parquet file (Chennai box only)."""
    from app.leads import overture_rows
    from app.overture import explorer_url

    out = []
    for r in overture_rows(path):
        lat, lon = r.get("lat"), r.get("lon")
        out.append(Candidate(
            source_key="overture_places", external_id=str(r["id"]),
            source_url=explorer_url(lat, lon) if lat is not None and lon is not None else "https://explore.overturemaps.org/",
            name=(r.get("name") or "").strip(), category=r.get("category") or r.get("basic_category"), address=r.get("address"),
            locality=r.get("locality"), postcode=r.get("postcode"), lat=lat, lon=lon, phones=list(r.get("phones") or []),
            emails=list(r.get("emails") or []), websites=list(r.get("websites") or []), brand=r.get("brand"),
            payload={k: (list(v) if isinstance(v, (list, tuple)) else v) for k, v in r.items() if k not in ("socials",)},
        ))
    return out


def rank_candidates(cands: list[Candidate], campaign: Campaign, limit: int, filtered: dict[str, int] | None = None) -> list[Candidate]:
    """Pick up to `limit` relevant candidates, split by the campaign's industry mix (e.g. 70/30).

    `filtered` (optional) receives counts of target-industry listings dropped for location or brand.
    """
    filtered = filtered if filtered is not None else {}
    by_ind: dict[str, list[tuple[float, Candidate]]] = {i: [] for i in campaign.industries}
    for cand in cands:
        if not cand.name:
            continue
        ind = lead_rules.classify_industry(cand.name, cand.category)
        if ind.industry not in by_ind:
            continue
        if cand.brand:
            filtered["chain_outlet"] = filtered.get("chain_outlet", 0) + 1
            continue
        v = chennai.classify_location(cand.address, cand.postcode)
        if v.status not in (chennai.OUTSIDE, chennai.GCMA_OUTSIDE):
            v = chennai.classify_location(cand.address, cand.locality, cand.postcode)
        if v.status in (chennai.OUTSIDE, chennai.GCMA_OUTSIDE):
            filtered["outside_chennai"] = filtered.get("outside_chennai", 0) + 1
            continue
        has_site = any(w and not _SOCIAL.search(w) for w in cand.websites)
        rank = (3 if has_site else 0) + (2 if v.status == chennai.CHENNAI_CITY else 0) + (1 if cand.emails else 0) + \
               (1 if re.search(r"\b(distributors?|wholesale|equipments?|instruments?|biomedical|surgical|systems|engineers?)\b", cand.name, re.I) else 0)
        by_ind[ind.industry].append((rank, cand))
    mix = campaign.industry_mix or core.DEFAULT_MIX
    total = sum(mix.get(i, 0) for i in by_ind) or 1
    picked: list[Candidate] = []
    filtered["relevant_total"] = sum(len(r) for r in by_ind.values())
    for i, rows in by_ind.items():
        rows.sort(key=lambda t: (-t[0], t[1].external_id))
        picked += [c for _, c in rows[: round(limit * mix.get(i, 0) / total)]]
    if len(picked) < limit:  # fill from whichever industry still has candidates
        rest = sorted((t for rows in by_ind.values() for t in rows if t[1] not in picked), key=lambda t: (-t[0], t[1].external_id))
        picked += [c for _, c in rest[: limit - len(picked)]]
    return picked[:limit]


def collect_overture(db: Session, campaign: Campaign, *, limit: int, job_id: int | None = None,
                     progress: Callable[[str, dict], None] | None = None, should_stop: Callable[[], bool] | None = None,
                     cands: list[Candidate] | None = None) -> dict[str, int]:
    path = overture_file()
    if cands is None:
        if path is None:
            raise FileNotFoundError("needs_setup: the Overture business file is not downloaded (Settings → Advanced → Sources)")
        cands = overture_candidates(path)
    seen = {x for x in db.scalars(select(RawItem.external_id).where(RawItem.campaign_id == campaign.id,
                                                                    RawItem.source_key == "overture_places"))}
    fresh = [c for c in cands if c.external_id not in seen]
    filtered: dict[str, int] = {}
    chosen = rank_candidates(fresh, campaign, limit, filtered)
    stats = {"read": len(cands), "new_relevant": len(chosen), "accepted": 0, "outside_chennai": 0, "duplicate": 0, "chain_outlet": 0,
             "wrong_industry": 0, "processed": 0, "prefiltered_outside": filtered.get("outside_chennai", 0),
             "prefiltered_chain": filtered.get("chain_outlet", 0),
             "unseen_relevant": max(0, filtered.get("relevant_total", 0) - len(chosen))}
    for cand in chosen:
        if should_stop and should_stop():
            break
        def one(cand=cand):
            try:
                r = ingest(db, campaign, cand, job_id=job_id)
                db.commit()
                return r
            except Exception:
                db.rollback()
                raise
        from app.ioi3.fetch import with_retry

        r = with_retry(one)
        stats[r.outcome] = stats.get(r.outcome, 0) + 1
        stats["processed"] += 1
        if progress:
            progress(f"Checking businesses — {stats['processed']} of {len(chosen)} reviewed", stats)
    return stats


# ------------------------------------------------------------------------------------------------
# CSV import (authorised lists) and manual entry
# ------------------------------------------------------------------------------------------------
CSV_COLUMNS = ["name", "address", "website", "phone", "email", "category", "industry", "source_url", "note"]


def import_csv(db: Session, campaign: Campaign, text: str, *, default_source_url: str | None = None) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "name" not in [f.strip().lower() for f in reader.fieldnames]:
        raise ValueError("The CSV needs a header row with at least a 'name' column. Columns: " + ", ".join(CSV_COLUMNS))
    stats: dict[str, Any] = {"rows": 0, "accepted": 0, "outside_chennai": 0, "wrong_industry": 0, "duplicate": 0, "no_name": 0,
                             "already_seen": 0, "chain_outlet": 0, "errors": []}
    for i, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        stats["rows"] += 1
        src = row.get("source_url") or default_source_url
        if not src:
            stats["errors"].append(f"Row {i}: no source_url (where this business came from)")
            continue
        ind = row.get("industry") or None
        if ind and ind not in campaign.industries:
            ind = {"equipment": lead_rules.EQUIPMENT, "wholesale": lead_rules.WHOLESALE}.get(ind.split()[0].lower())
        cand = Candidate(source_key="csv_import", external_id=f"{row.get('name','').lower()}|{row.get('address','').lower()}"[:200],
                         source_url=src, name=row.get("name", ""), category=row.get("category") or None,
                         address=row.get("address") or None, phones=[row["phone"]] if row.get("phone") else [],
                         emails=[row["email"]] if row.get("email") else [], websites=[row["website"]] if row.get("website") else [],
                         industry_hint=ind, note=row.get("note") or None, payload=row)
        r = ingest(db, campaign, cand)
        stats[r.outcome] = stats.get(r.outcome, 0) + 1
    db.commit()
    core.mark_source(db, "csv_import", ok=True, records=stats["rows"], freshness=f"Last import {utcnow():%d %b %Y}")
    db.commit()
    return stats


def add_manual(db: Session, campaign: Campaign, data: dict[str, Any]) -> IngestResult:
    if not (data.get("source_url") or "").startswith(("http://", "https://")):
        raise ValueError("Add the link where you found this business (http/https).")
    cand = Candidate(source_key="manual", external_id=uuid.uuid4().hex, source_url=data["source_url"], name=data.get("name", ""),
                     address=data.get("address") or None, phones=[data["phone"]] if data.get("phone") else [],
                     emails=[data["email"]] if data.get("email") else [], websites=[data["website"]] if data.get("website") else [],
                     industry_hint=data.get("industry") or None, location_evidence_url=data.get("location_evidence_url") or None,
                     note=data.get("note") or None)
    r = ingest(db, campaign, cand)
    db.commit()
    return r
