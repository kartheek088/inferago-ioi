"""Overture Maps places (open data: CDLA-Permissive-2.0; sources include Meta, Microsoft, Foursquare).

Much richer than OpenStreetMap for Indian small businesses: most listings carry a phone number
and a Facebook page. We download one country's places that list a phone into a local Parquet
file once (DuckDB reads only the matching parts of the public S3 dataset), then scan it locally.

Facts come only from the Overture record. Each prospect links to the Overture explorer at its
location (`source_url`) so the owner can check where it came from.
"""

from __future__ import annotations

import os
from pathlib import Path

RELEASE_INDEX = "https://overturemaps-us-west-2.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/"
S3_PLACES = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
COUNTRY_BBOX = {"India": (68.0, 6.5, 97.5, 35.7)}  # xmin, ymin, xmax, ymax (also covers bits of neighbours: phone prefix decides)


def connect():
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    return con


def latest_release(http) -> str:
    import re

    res = http.get(RELEASE_INDEX, check_robots=False)  # S3 bucket listing API, not a website (no robots.txt: 404)
    releases = sorted(re.findall(r"<Prefix>release/([^/<]+)/</Prefix>", res.text))
    if not releases:
        raise RuntimeError("No Overture releases found")
    return releases[-1]


def download_country(release: str, out: Path, country: str = "India") -> int:
    """Save places with a phone number inside the country's box to a local Parquet file. Returns row count."""
    xmin, ymin, xmax, ymax = COUNTRY_BBOX[country]
    tmp = out.with_suffix(".part")
    con = connect()
    con.execute(f"""
        COPY (
          SELECT id, names.primary AS name, basic_category, taxonomy.primary AS category, taxonomy.hierarchy AS hierarchy,
                 phones, websites, socials, emails, confidence, operating_status,
                 addresses[1].freeform AS address, addresses[1].locality AS locality, addresses[1].region AS region,
                 addresses[1].postcode AS postcode, addresses[1].country AS country,
                 brand.names.primary AS brand, sources[1].dataset AS dataset,
                 (bbox.xmin + bbox.xmax) / 2 AS lon, (bbox.ymin + bbox.ymax) / 2 AS lat
          FROM read_parquet('{S3_PLACES.format(release=release)}', hive_partitioning=0)
          WHERE bbox.xmin BETWEEN {xmin} AND {xmax} AND bbox.ymin BETWEEN {ymin} AND {ymax}
            AND phones IS NOT NULL AND len(phones) > 0
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)
    """)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
    os.replace(tmp, out)
    return int(n)


# ------------------------------------------------------------------------------------------------
# Overture category → our business types
# ------------------------------------------------------------------------------------------------
import re  # noqa: E402

from app.prospects import BizType, _ENT, _APPT, _PRO, _RETAIL  # noqa: E402

# (regex on "category basic_category hierarchy", segment, label, tier, services, dealer_shop)
_RULES: list[tuple[str, str, str, int, tuple[str, ...], str | None]] = [
    (r"college|university|polytechnic|institute_of", "college", "College / university", 3, ("website", "crm", "erp", "ai", "marketing"), None),
    (r"dentist|dental", "professional", "Dentist", 3, _APPT, None),
    (r"hospital", "small_business", "Hospital", 3, ("website", "crm", "ai", "erp", "marketing"), None),
    (r"doctor|physician|clinic|medical_center|pediatric|gynecolog|dermatolog|orthop|ayurved|homeopath|physiotherap|diagnostic|laborator",
     "professional", "Doctor / clinic", 3, _APPT, None),
    (r"veterinar|animal_hospital|pet_service", "professional", "Veterinary / pet care", 2, _APPT, None),
    (r"lawyer|law_firm|legal|attorney|advocate|notar", "professional", "Lawyer / law firm", 3, _PRO, None),
    (r"accountant|accounting|tax_|chartered|bookkeep|audit", "professional", "Accountant / tax", 3, _PRO, None),
    (r"architect", "professional", "Architect", 3, _PRO, None),
    (r"interior_design", "professional", "Interior designer", 3, _PRO, None),
    (r"real_estate", "professional", "Real estate", 3, _PRO, None),
    (r"insurance", "professional", "Insurance agent", 2, _PRO, None),
    (r"financial_advis|investment_advis|wealth|loan_agent|mortgage", "professional", "Financial advisor", 3, _PRO, None),
    (r"manufactur|factory|industrial|(?:^|[\s_])mills?(?:$|[\s_])|machine_shop|fabricat|printing_press|wholesale|distributor|supplier|"
     r"export|import|logistics|warehouse|transport|freight|courier", "enterprise", "Manufacturer / wholesaler / logistics", 3, _ENT, "wholesale"),
    (r"photograph|videograph", "professional", "Photographer", 2, _PRO, None),
    (r"wedding|event_plan|event_or_party|party_and_event|caterer|catering|banquet|event_venue", "small_business", "Events / weddings / catering", 3, _APPT, None),
    (r"tutor|coaching|test_prep|educational_service|training|language_school|driving_school|music_school|dance_school|preschool|kindergarten|day_care",
     "small_business", "Coaching / training", 3, _APPT, None),
    (r"(?:^|[\s_])school(?:$|[\s_])|elementary_school|high_school", "small_business", "School", 3, ("website", "crm", "erp", "marketing"), None),
    (r"hotel|resort|guest_house|lodg|homestay|hostel|motel|bed_and_breakfast", "small_business", "Hotel / stay", 3, ("website", "marketing", "crm", "ai"), None),
    (r"gym|fitness|yoga|martial_arts|sports_club|swimming", "small_business", "Gym / fitness", 3, _APPT, None),
    (r"(?:^|[\s_])spa(?:$|[\s_])|salon|beauty|barber|(?:^|[\s_])hair(?:$|[\s_])|nail_salon|makeup|tattoo|wellness", "small_business", "Salon / beauty / spa", 2, _APPT, None),
    (r"restaurant|cafe|coffee|eatery|bakery|sweet|dessert|food_court|(?:^|[\s_])bar(?:$|[\s_])|(?:^|[\s_])pub(?:$|[\s_])|juice|ice_cream|fast_food|delicatessen|caterer",
     "small_business", "Restaurant / cafe / food", 2, ("website", "marketing", "ai"), None),
    (r"car_dealer|automotive_dealer|used_car|motorcycle_dealer|motorsports_store|vehicle_dealer|truck_dealer|tractor", "small_business",
     "Vehicle dealer", 3, ("website", "crm", "marketing"), "car"),
    (r"automotive_repair|auto_repair|car_wash|(?:^|[\s_])tires?(?:$|[\s_])|(?:^|[\s_])tyres?(?:$|[\s_])|vehicle_parts|auto_parts|spare_parts|automotive_service", "small_business",
     "Auto service / parts", 2, _APPT, "car_repair"),
    (r"jewel", "small_business", "Jewellery", 3, ("website", "marketing", "crm"), None),
    (r"furniture|home_decor|mattress", "small_business", "Furniture / home decor", 3, _RETAIL, "furniture"),
    (r"electronics|mobile_phone|computer_store|appliance", "small_business", "Electronics / mobiles", 2, _RETAIL, "electronics"),
    (r"hardware|building_material|paint|(?:^|[\s_])tiles?(?:$|[\s_])|sanitary|plumbing_supply|electrical_supply", "small_business", "Hardware / building materials",
     2, ("website", "marketing", "erp"), "hardware"),
    (r"pharmac|drugstore|chemist|medical_supply", "small_business", "Pharmacy / medical store", 2, ("website", "marketing", "crm"), None),
    (r"travel|tour_operator|ticket", "small_business", "Travel agency", 3, _APPT, None),
    (r"fashion|apparel|clothing|boutique|tailor|saree|textile_store|footwear|shoe", "small_business", "Clothing / fashion", 2,
     ("website", "marketing", "strategy"), None),
    (r"grocery|supermarket|convenience|department_store|food_and_beverage_store|provision", "small_business", "Grocery / supermarket", 1,
     ("website", "marketing", "erp"), None),
    (r"contractor|construction|builder|renovation|home_service|plumber|electrician|carpenter|pest_control|cleaning|packers|movers|interior",
     "small_business", "Contractor / home services", 2, ("website", "marketing", "crm"), None),
    (r"professional_service|consult|agency|business_service", "professional", "Professional services", 2, _PRO, None),
    (r"store|shop|shopping|retail|market", "small_business", "Shop", 1, _RETAIL, None),
]
_SKIP_CATEGORY = re.compile(
    r"government|public_service|civic|religio|place_of_worship|temple|church|mosque|gurdwara|(?:^|[\s_])atm(?:$|[\s_])|(?:^|[\s_])bank(?:$|[\s_])|"
    r"credit_union|information_technology|it_service|software|web_design|web_develop|computer_programm|telecom|internet_service|"
    r"political|embassy|police|post_office|military|toilet|parking|bus_station|train_station|airport|landmark|(?:^|[\s_])park(?:$|[\s_])|natural|"
    r"monument|cemetery|structure_and_geography|road|bridge|charity|non_profit|(?:^|[\s_])ngo(?:$|[\s_])|community_center|library|"
    r"advertising_agency|marketing_agency|digital_marketing|(?:^|[\s_])seo(?:$|[\s_])", re.I,
)


def classify(category: str | None, basic: str | None, hierarchy: list[str] | None) -> tuple[str, BizType, str | None] | None:
    text = " ".join([category or "", basic or "", *(hierarchy or [])]).lower()
    if not text.strip() or _SKIP_CATEGORY.search(text):
        return None
    for pat, seg, label, tier, services, dealer in _RULES:
        if re.search(pat, text):
            return f"overture={category or basic}", BizType(seg, label, tier, services), dealer
    return f"overture={category or basic}", BizType("small_business", f"Business ({(category or basic or '').replace('_', ' ')})", 1,
                                                    ("website", "marketing")), None


# ------------------------------------------------------------------------------------------------
# Scan the local file into prospects
# ------------------------------------------------------------------------------------------------
def explorer_url(lat: float, lon: float) -> str:
    return f"https://explore.overturemaps.org/#17/{lat:.5f}/{lon:.5f}"


_STRONG_IT = re.compile(r"\b(infotech|infosys|software|softwares|technologies|technology solutions|it services|it solutions|"
                        r"web ?(design|solutions|services)|digital marketing|cyber|computer (academy|education|institute|training|centre|center))\b", re.I)
_BANK = re.compile(r"\bbank\b", re.I)
_NOT_A_BANK = re.compile(r"blood bank|food bank|bank (road|colony|street|nagar)", re.I)
_EDU_LIKE = {"School", "Coaching / training", "Hospital", "Doctor / clinic", "Professional services"}


def extra_exclusion(name: str, label: str, segment: str) -> str | None:
    """Name checks that OSM tags usually cover but Overture categories do not."""
    from app.prospects import _COLLEGE_NAMES, _SKIP_NAME

    if _SKIP_NAME.search(name):
        return "government or public place"
    if _STRONG_IT.search(name) and label != "Vehicle dealer":
        return "IT / software company"
    if _BANK.search(name) and not _NOT_A_BANK.search(name) and label not in ("School", "Hospital"):
        return "bank"
    return None


def to_parsed(row: dict):
    """One Overture row → ParsedProspect (or None when it is not a business we can help)."""
    from app.prospects import ParsedProspect, _is_social, exclusion_reason

    name = (row.get("name") or "").strip()
    if not name or row.get("operating_status") not in (None, "open"):
        return None
    c = classify(row.get("category"), row.get("basic_category"), row.get("hierarchy"))
    if c is None:
        return None
    key, biz, dealer_shop = c
    from app.prospects import _COLLEGE_NAMES

    if biz.label in ("School", "Coaching / training") and _COLLEGE_NAMES.search(name):
        biz = BizType("college", "College / university", 3, ("website", "crm", "erp", "ai", "marketing"))
    websites = [w for w in (row.get("websites") or []) if w]
    socials = [w for w in (row.get("socials") or []) if w]
    real_sites = [w for w in websites if not _is_social(w)]
    socials += [w for w in websites if _is_social(w)]  # a Facebook link in "websites" is still not a website
    tags = {"name": name, "addr:full": row.get("address") or "", "addr:city": row.get("locality") or "",
            "addr:postcode": row.get("postcode") or "", "overture:category": row.get("category") or row.get("basic_category") or "",
            "overture:confidence": str(round(row.get("confidence") or 0, 2)), "overture:dataset": row.get("dataset") or "",
            "overture:country": row.get("country") or "", "addr:state": row.get("region") or ""}
    if row.get("brand"):
        tags["brand"] = row["brand"]
    if dealer_shop:
        tags["shop"] = dealer_shop
    if biz.segment == "enterprise" and dealer_shop == "wholesale":
        tags.pop("shop", None)  # manufacturers with a brand are usually the brand owner, not a dealer
        if row.get("brand"):
            return None
    if exclusion_reason(tags, name, key if key.startswith("office=") else None) or extra_exclusion(name, biz.label, biz.segment):
        return None
    lat, lon = row.get("lat"), row.get("lon")
    return ParsedProspect(
        ref=f"overture:{row['id']}", url=explorer_url(lat, lon), name=name[:300], type_key=key, biz=biz, tags=tags,
        lat=lat, lon=lon, phone=(row.get("phones") or [None])[0], email=(row.get("emails") or [None])[0],
        website=real_sites[0] if real_sites else None, social=socials[:5],
    )


def run_overture_scan(db, run, path: str, *, max_keep: int, min_confidence: float = 0.3, cities: list[str] | None = None,
                      radius_km: float = 15.0, rules=None, mode: str = "no_website"):
    from app.db import utcnow
    from app.prospects import SearchRules, _dropped_text, _km, _place_name, nearest_city, resolve_area, upsert

    logs: list[str] = list(run.log or [])

    def log(msg: str) -> None:
        logs.append(msg[:500])
        run.log = list(logs)
        db.commit()

    rules = rules or SearchRules()
    centres = [resolve_area(c) for c in (cities or [])]
    try:
        import duckdb

        log(f"Reading {Path(path).name} ({ {'no_website': 'businesses without a website', 'upgrade': 'businesses whose website may need an upgrade', 'colleges': 'colleges and universities'}.get(mode, mode)}). This usually takes 1–5 minutes…")
        con = duckdb.connect()
        where = [f"confidence >= {float(min_confidence)}", "country = 'IN'"]  # the download box also covers neighbours
        real_sites = ("len(list_filter(coalesce(websites, []), lambda w: NOT regexp_matches(lower(w), "
                      "'facebook\\.com|instagram\\.com|fb\\.com|youtube\\.com|linkedin\\.com|wa\\.me|linktr\\.ee|justdial\\.com|indiamart\\.com|sulekha\\.com')))")
        is_college = "regexp_matches(lower(coalesce(category, '') || ' ' || coalesce(basic_category, '')), 'college|university')"
        if mode == "colleges":
            where.append(is_college)
            rules.only_no_website = False
        elif mode == "upgrade":
            where.append(f"{real_sites} > 0")
            rules.only_no_website, rules.only_with_website = False, True
        elif rules.only_no_website:
            where.append(f"({real_sites} = 0 OR {is_college})")
        if centres:
            boxes = []
            for _, lat, lon, _c in centres:
                dlat, dlon = radius_km / 111.0, radius_km / 111.0 / max(0.2, __import__("math").cos(__import__("math").radians(lat)))
                boxes.append(f"(lat BETWEEN {lat - dlat} AND {lat + dlat} AND lon BETWEEN {lon - dlon} AND {lon + dlon})")
            where.append("(" + " OR ".join(boxes) + ")")
        cur = con.execute(f"SELECT * FROM read_parquet('{path}') WHERE {' AND '.join(where)}")
        cols = [d[0] for d in cur.description]
        buckets: dict[tuple, list] = {}  # sort key → candidates; each capped at max_keep so memory stays small
        dropped: dict[str, int] = {}
        found, total = 0, 0
        while True:
            batch = cur.fetchmany(20000)
            if not batch:
                break
            for tup in batch:
                total += 1
                row = dict(zip(cols, tup))
                if centres and not any(_km(row["lat"], row["lon"], c[1], c[2]) <= radius_km for c in centres):
                    continue
                pp = to_parsed(row)
                if not pp:
                    continue
                why = rules.keep(pp, "India")
                if why:
                    dropped[why] = dropped.get(why, 0) + 1
                    continue
                found += 1
                k = (not pp.social, -pp.biz.tier, not pp.tags.get("addr:full"))
                b = buckets.setdefault(k, [])
                if len(b) < max_keep:
                    b.append(pp)
            log(f"…{total:,} listings read, {found:,} possible prospects so far")
            db.refresh(run, ["status"])
            if run.status == "stopping":
                logs.append("Stopped by you.")
                run.status = "stopped"
                return run
        # Best first: social media presence (active online, no site), then business value, then has an address.
        keep = [pp for k in sorted(buckets) for pp in buckets[k]][:max_keep]
        log(f"Saving the best {len(keep):,} of {found:,}…")
        for i, pp in enumerate(keep, 1):
            area, country = nearest_city(pp.lat, pp.lon)
            if area == "Other":
                area = _place_name(pp.tags.get("addr:city")) or "Other"
            _, created = upsert(db, pp, area, country or "India")  # phone already checked as an Indian number
            run.new += int(created)
            run.updated += int(not created)
            if i % 2000 == 0:
                db.commit()
                log(f"…saved {i:,} of {len(keep):,}")
        run.found = len(keep)
        run.skipped = total - found
        logs.append(f"✓ Done: read {total:,} listings with a phone; {found:,} possible prospects, kept the best {len(keep):,} ({run.new:,} new){_dropped_text(dropped)}.")
        run.status = "success"
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logs.append(f"✗ Could not read the Overture file: {str(exc)[:300]}")
        run.status = "failed"
    finally:
        run.log = logs
        run.finished_at = utcnow()
        db.commit()
    return run
