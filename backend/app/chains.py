"""Multi-branch (regional) businesses found by grouping Overture listings.

A group is a chain when it has 3–40 separate locations (≥ ~1 km apart) in at most two states and
either shares a phone number / social page between branches (strong evidence) or has the same
name and category in one state. National brands (Overture brand field, known chain names, more
than two states) are left out: they have their own IT teams. Everything else follows the
prospect rules (no government, banks, IT companies; colleges allowed).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.geo_states import state_from_code
from app.models import BusinessChain, ProspectRun

_NORM = (
    "trim(regexp_replace(regexp_replace(regexp_replace(lower(regexp_replace(name, '\\s+[-|,(@].*$', '')), "
    "'\\b(the|new|branch|pvt|private|ltd|limited|llp|co|and|&|sri|shri|shree)\\b', ' ', 'g'), '[^a-z0-9]+', ' ', 'g'), '\\s+', ' ', 'g'))"
)
SOCIAL = "facebook\\.com|instagram\\.com|fb\\.com|youtube\\.com|linkedin\\.com|wa\\.me|linktr\\.ee|justdial\\.com|indiamart\\.com|sulekha\\.com"


def find_groups(path: str, min_confidence: float = 0.3) -> list[dict[str, Any]]:
    import duckdb

    con = duckdb.connect()
    con.execute(f"""
        CREATE TEMP TABLE p AS
        SELECT id, name, category, basic_category, phones, websites, socials, region, locality, address, lat, lon, brand, confidence,
               {_NORM} AS k
        FROM read_parquet('{path}') WHERE country = 'IN' AND confidence >= {float(min_confidence)} AND name IS NOT NULL""")
    con.execute("""
        CREATE TEMP TABLE g AS
        SELECT k, count(*) n, count(DISTINCT (round(lat, 2), round(lon, 2))) nloc, count(DISTINCT region) nreg,
               count(DISTINCT category) ncat, bool_or(brand IS NOT NULL) branded
        FROM p WHERE (length(k) >= 5 AND k LIKE '% %') OR length(k) >= 7 GROUP BY k""")
    con.execute("""
        CREATE TEMP TABLE sh AS
        SELECT k, count(*) shared, list(c) shared_values FROM (
          SELECT k, c FROM (SELECT k, unnest(list_concat(coalesce(phones, []), coalesce(socials, []))) c FROM p)
          GROUP BY k, c HAVING count(*) >= 2) GROUP BY k""")
    rows = con.execute(f"""
        SELECT g.k, g.nloc, g.nreg, g.ncat, coalesce(sh.shared, 0) AS shared, sh.shared_values,
               list(struct_pack(id := p.id, name := p.name, category := p.category, basic := p.basic_category, phone := p.phones[1],
                                socials := p.socials, websites := p.websites, region := p.region, city := p.locality,
                                address := p.address, lat := p.lat, lon := p.lon, conf := p.confidence)) AS branches
        FROM g LEFT JOIN sh USING (k) JOIN p USING (k)
        WHERE NOT g.branded AND g.nloc BETWEEN 3 AND 40 AND g.nreg <= 2 AND g.k NOT LIKE 'dr %'
          AND (coalesce(sh.shared, 0) >= 1 OR (g.nreg = 1 AND g.ncat <= 2))
        GROUP BY ALL""").fetchall()
    cols = ["key", "nloc", "nreg", "ncat", "shared", "shared_values", "branches"]
    return [dict(zip(cols, r)) for r in rows]


def build_chain(g: dict[str, Any]) -> dict[str, Any] | None:
    """Apply the prospect rules to a group and score it. None = not for us."""
    import re
    from collections import Counter

    from app.overture import classify, extra_exclusion
    from app.prospects import _CHAIN_NAMES, _is_social, check_phone, exclusion_reason

    branches = g["branches"]
    names = Counter(b["name"] for b in branches)
    name = names.most_common(1)[0][0]
    cat = Counter(b["category"] or b["basic"] for b in branches).most_common(1)[0][0]
    c = classify(cat, None, None)
    if c is None:
        return None
    _, biz, _ = c
    if _CHAIN_NAMES.search(name) or exclusion_reason({}, name, None) or extra_exclusion(name, biz.label, biz.segment):
        return None
    phones = []
    for b in branches:
        norm, kind = check_phone(b["phone"], "India")
        if kind in ("mobile", "landline") and norm not in phones:
            phones.append(norm)
    if not phones:
        return None
    socials = sorted({s for b in branches for s in (b["socials"] or [])} | {w for b in branches for w in (b["websites"] or []) if _is_social(w)})
    sites = sorted({w for b in branches for w in (b["websites"] or []) if not _is_social(w)})
    states = Counter(state_from_code(b["region"]) for b in branches if state_from_code(b["region"]))
    cities = sorted({b["city"] for b in branches if b["city"]})
    nloc = int(g["nloc"])
    shared = int(g["shared"] or 0)
    evidence = "shared_contact" if shared else "same_name_one_state"
    detail = (f"{shared} phone number(s) / page(s) shared between branches" if shared
              else f"same name and type in {len(cities) or 'several'} place(s) of one state — check they are one business")
    score, reasons = 0.0, []
    pts = 10 if nloc <= 3 else 20 if nloc <= 5 else 30 if nloc <= 15 else 35
    score += pts
    reasons.append(f"+{pts} {nloc} branches")
    if shared:
        score += 15
        reasons.append("+15 branches share a phone number or page (same business)")
    if not sites:
        score += 15
        reasons.append("+15 no website for any branch")
    if socials:
        score += 10
        reasons.append("+10 active on social media")
    tier_pts = {3: 15, 2: 8, 1: 0}[biz.tier]
    if tier_pts:
        score += tier_pts
        reasons.append(f"+{tier_pts} business type that wins customers online")
    main_state = states.most_common(1)[0][0] if states else None
    if main_state == "Tamil Nadu":
        score += 15
        reasons.append("+15 in Tamil Nadu")
    elif main_state in ("Karnataka", "Kerala", "Andhra Pradesh", "Telangana", "Puducherry"):
        score += 8
        reasons.append(f"+8 in South India ({main_state})")
    services = ["crm", "integration", "website", "internal_apps", "ai"] if sites else ["website", "crm", "integration", "marketing", "ai"]
    if biz.segment == "enterprise":
        services = ["erp", "crm", "integration", "internal_apps", "website"]
    return {
        "key": g["key"][:200], "name": re.sub(r"\s+[-|,(@].*$", "", name)[:300] or name[:300], "type_label": biz.label, "segment": biz.segment,
        "branch_count": nloc, "cities": cities[:40], "states": sorted(states), "main_state": main_state, "phones": phones[:20],
        "socials": socials[:10], "has_website": bool(sites), "evidence": evidence, "evidence_detail": detail,
        "branches": [{"name": b["name"], "address": b["address"], "city": b["city"], "state": state_from_code(b["region"]), "phone": b["phone"],
                      "lat": b["lat"], "lon": b["lon"], "source_url": f"https://explore.overturemaps.org/#17/{b['lat']:.5f}/{b['lon']:.5f}"}
                     for b in branches[:30]],
        "services": services, "score": min(100.0, score), "score_reasons": reasons,
    }


def run_chain_search(db: Session, run: ProspectRun, path: str, max_keep: int = 20000) -> ProspectRun:
    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(msg)
        run.log = list(logs)
        db.commit()

    try:
        log("Grouping business listings into branches. This takes about a minute…")
        groups = find_groups(path)
        log(f"…{len(groups):,} possible multi-branch businesses; checking each one…")
        built = [c for c in (build_chain(g) for g in groups) if c]
        built.sort(key=lambda c: -c["score"])
        keep = built[:max_keep]
        new = 0
        for i, c in enumerate(keep, 1):
            row = db.scalar(select(BusinessChain).where(BusinessChain.key == c["key"]))
            if row is None:
                row = BusinessChain(status="new", contact_log=[])
                db.add(row)
                new += 1
            for k, v in c.items():
                setattr(row, k, v)
            if i % 2000 == 0:
                db.commit()
        run.found, run.new = len(keep), new
        logs.append(f"✓ Done: {len(built):,} multi-branch businesses meet the rules, kept the best {len(keep):,} ({new:,} new).")
        run.status = "success"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logs.append(f"✗ Could not group the listings: {str(exc)[:300]}")
        run.status = "failed"
    finally:
        run.log = logs
        run.finished_at = utcnow()
        db.commit()
    return run
