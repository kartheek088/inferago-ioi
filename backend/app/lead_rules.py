"""Deterministic rules for Chennai leads: industry, operations, buying signals, A–D category, sales difficulty.

Everything here is pure (no DB, no network) and explainable: every decision returns its reasons.

Principles (owner brief, 2026-11-23):
- Only two industries: wholesale distribution, and equipment sales WITH service operations.
- Expansion, hiring or company registration are NOT software demand. They can make a lead
  "promising" (B), never "high contract potential" (A).
- Category A needs a CONFIRMED (human-added or human-confirmed), dated, recent signal of explicit
  technical need or an immediate operational problem — never an AI or keyword guess alone.
- Unknown stays unknown: missing facts never count as satisfied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# ------------------------------------------------------------------------------------------------
# Industries
# ------------------------------------------------------------------------------------------------
WHOLESALE = "wholesale_distribution"
EQUIPMENT = "equipment_sales_service"
INDUSTRY_LABEL = {WHOLESALE: "Wholesale distributor", EQUIPMENT: "Equipment sales & service"}

_WHOLESALE_CAT = re.compile(
    r"wholesal|distributor|distribution|supplier_or_distributor|stockist|food_beverage_distributor|"
    r"pharmaceutical_products_wholesaler|(?:^|[\s_])warehouse(?:$|[\s_])|exporter|importer"
)
_WHOLESALE_CAT_EXCLUDE = re.compile(r"warehouse_club_store|grocery_store|supermarket|convenience")
_WHOLESALE_NAME = re.compile(
    r"\b(distributors?|distribution|wholesalers?|wholesale|stockists?|super stockists?|c ?& ?f agents?|"
    r"carrying (?:and|&) forwarding)\b", re.I)

_EQUIP_CAT = re.compile(
    r"industrial_equipment|medical_supply|hospital_equipment|laboratory_equipment|"
    r"electronic_equipment_supplier|hvac_service|hvac_supplier|elevator_service|hydraulic_equipment|"
    r"printing_equipment|bank_equipment_service|automation_service|b2b_industrial_and_machine_service|"
    r"vending_machine_supplier|restaurant_equipment|electrical_supply|generator|fire_protection|water_purif|"
    r"weighing|scale_supplier|machinery|equipment_supplier|equipment_rental|engine_repair"
)
_EQUIP_NAME = re.compile(
    r"\b(equipments?|instruments?|biomedical|surgicals?|scientific|hvac|elevators?|lifts|generators?|gensets?|"
    r"ups systems?|compressors?|pumps|machinery|machines|weighing|refrigeration|air ?condition\w*|"
    r"diagnostics? systems?|automation|power systems?|fire safety|water treatment|x-?ray|imaging)\b", re.I)

# Sectors outside both target industries even when names look similar.
_EXCLUDE = re.compile(
    r"laboratory_testing|oncology|surgery_center|surgeon|doctor|physician|dentist|dental_clinic|medical_center|diagnostic_center|"
    r"pediatric|orthop|gynecolog|cardiolog|dermatolog|it_service|computer_repair|software|web_design|mobile_phone_repair|automotive_repair|motorcycle_repair|"
    r"bike_repair|tire_dealer|car_dealer|motorcycle_dealer|appliance_repair|beauty|salon|restaurant(?!_equipment)|"
    r"hospital(?!_equipment)|clinic|pharmacy|chemist|school|college|bank(?!_equipment)|real_estate|hotel|"
    r"government|religio|temple|church|mosque|jewel|clothing|apparel|textile_store|footwear|grocery_store|"
    # consumer retail / events / vehicles
    r"electronics_store|appliance_store|^shopping$|party_and_event|event_planning|audiovisual_equipment_rental|engine_repair|automotive|"
    # manufacturing plants and raw-material traders (not distribution or equipment service)
    r"chemical_plant|metal_plating|powder_coating|metal_supplier|granite_supplier|cement_supplier|sand_and_gravel|aluminum_supplier|"
    r"stationery|book_magazine",
)
_SUBTYPE = (
    ("medical", re.compile(r"medical|hospital|surgical|biomedical|diagnostic|x-?ray|imaging|dental|healthcare", re.I)),
    ("laboratory", re.compile(r"laborator|scientific|lab equipment|analytical", re.I)),
    ("electrical", re.compile(r"electrical|generator|genset|ups|power systems?|transformer|switchgear|solar", re.I)),
    ("hvac_elevator", re.compile(r"hvac|air ?condition|refrigeration|elevator|lift", re.I)),
    ("industrial", re.compile(r"industrial|machine|machinery|hydraulic|compressor|pump|automation|weighing|printing", re.I)),
)


@dataclass
class IndustryVerdict:
    industry: str | None  # WHOLESALE | EQUIPMENT | None
    strength: str  # strong | candidate | none
    subtype: str | None
    reasons: list[str] = field(default_factory=list)


def classify_industry(name: str | None, category: str | None = None, page_text: str = "",
                      indicators: list[str] | None = None) -> IndustryVerdict:
    """Decide which of the two target industries (if any) a business belongs to.

    `strength`:
      - strong: directory/name evidence AND operations evidence from the official website
      - candidate: directory/name evidence only (website not checked yet, or no operations found)
      - none: not one of the two industries
    """
    name = name or ""
    cat = (category or "").lower()
    ind = set(indicators or [])
    reasons: list[str] = []
    if cat and _EXCLUDE.search(cat):
        return IndustryVerdict(None, "none", None, [f"Directory category '{cat}' is outside the two target industries"])
    if re.match(r"\s*dr\.?\s", name, re.I) or re.search(r"\b(surgeon|clinic|hospital|doctor)\b", name, re.I) and not _EQUIP_NAME.search(name):
        return IndustryVerdict(None, "none", None, ["Name indicates a medical practice, not an equipment business"])

    w_hit = bool(cat and _WHOLESALE_CAT.search(cat) and not _WHOLESALE_CAT_EXCLUDE.search(cat)) or bool(_WHOLESALE_NAME.search(name))
    e_hit = bool(cat and _EQUIP_CAT.search(cat)) or bool(_EQUIP_NAME.search(name))
    if cat == "medical_supply_store" and not _EQUIP_NAME.search(name) and "service_ops" not in ind:
        e_hit = False  # retail medical shops: only equipment businesses with service count
        reasons.append("Medical supply store without equipment/service evidence")

    w_ops = ind & {"dealer_network", "warehouse", "dispatch_delivery", "multi_branch", "b2b_orders"}
    e_ops = ind & {"service_ops", "amc_warranty", "technicians", "installation", "service_request"}

    if w_hit and (not e_hit or len(w_ops) >= len(e_ops)):
        if cat and _WHOLESALE_CAT.search(cat):
            reasons.append(f"Directory category '{cat}'")
        if _WHOLESALE_NAME.search(name):
            reasons.append(f"Name says '{_WHOLESALE_NAME.search(name).group(0)}'")
        if w_ops:
            reasons.append("Website shows distribution operations: " + ", ".join(sorted(w_ops)))
            return IndustryVerdict(WHOLESALE, "strong", None, reasons)
        reasons.append("Distribution operations not yet confirmed on the official website")
        return IndustryVerdict(WHOLESALE, "candidate", None, reasons)

    if e_hit:
        hay = f"{name} {cat} {page_text[:3000]}"
        subtype = next((k for k, rx in _SUBTYPE if rx.search(hay)), "other")
        if cat and _EQUIP_CAT.search(cat):
            reasons.append(f"Directory category '{cat}'")
        if _EQUIP_NAME.search(name):
            reasons.append(f"Name says '{_EQUIP_NAME.search(name).group(0)}'")
        if e_ops:
            reasons.append("Website shows service operations: " + ", ".join(sorted(e_ops)))
            return IndustryVerdict(EQUIPMENT, "strong", subtype, reasons)
        reasons.append("Service operations (installation/repair/AMC) not yet confirmed — pure resellers are excluded")
        return IndustryVerdict(EQUIPMENT, "candidate", subtype, reasons)

    return IndustryVerdict(None, "none", None, reasons or ["No distribution or equipment-service evidence"])


# ------------------------------------------------------------------------------------------------
# Operations seen on the official website (facts about how they work — NOT buying signals)
# ------------------------------------------------------------------------------------------------
OPERATIONS: dict[str, tuple[str, re.Pattern[str]]] = {
    "service_ops": ("After-sales service / repairs", re.compile(r"\b(after[- ]sales|breakdown service|repair services?|service support|service cent(?:re|er)s?|on-?site service)\b", re.I)),
    "amc_warranty": ("AMC / warranty", re.compile(r"\b(AMC|annual maintenance contracts?|comprehensive maintenance|CMC|warranty (?:support|service|claims?)|extended warranty)\b", re.I)),
    "technicians": ("Field technicians / service engineers", re.compile(r"\b(service engineers?|field (?:service )?engineers?|technicians?|field staff|service team of \d+)\b", re.I)),
    "installation": ("Installation & commissioning", re.compile(r"\b(installation(?: and| &) commissioning|installation services?|commissioning|calibration services?|preventive maintenance)\b", re.I)),
    "service_request": ("Online service request / complaint form", re.compile(r"\b(service request|raise a (?:ticket|complaint)|register (?:a )?complaint|book a service|service booking)\b", re.I)),
    "dealer_network": ("Dealer / retailer network", re.compile(r"\b(dealer network|our dealers|channel partners?|retail(?:er)? network|\d+\+? (?:dealers|retailers|outlets)|sub-?distributors?)\b", re.I)),
    "warehouse": ("Warehouse / godown", re.compile(r"\b(warehouses?|godowns?|distribution cent(?:re|er)s?|depots?|storage facility)\b", re.I)),
    "dispatch_delivery": ("Dispatch / delivery fleet", re.compile(r"\b(dispatch|delivery vans?|own fleet|fleet of|same[- ]day delivery|doorstep delivery|logistics)\b", re.I)),
    "multi_branch": ("Multiple branches", re.compile(r"\b(our branches|branch offices?|branches (?:in|across|at)|\d+ branches|offices across)\b", re.I)),
    "b2b_orders": ("Business customers / bulk orders", re.compile(r"\b(bulk orders?|B2B|institutional (?:sales|customers)|hospitals? and clinics|supply to (?:hospitals|industries|retailers|shops))\b", re.I)),
}


def detect_operations(text: str) -> list[dict[str, str]]:
    out = []
    for key, (label, rx) in OPERATIONS.items():
        m = rx.search(text)
        if m:
            out.append({"key": key, "label": label, "excerpt": _excerpt(text, m)})
    return out


# ------------------------------------------------------------------------------------------------
# Buying signals
# ------------------------------------------------------------------------------------------------
# Signal types that can support Category A (explicit need or immediate operational problem).
INTENT_TYPES = {"explicit_software_request", "vendor_request", "operational_problem"}
SIGNAL_LABEL = {
    "explicit_software_request": "Asked for software / automation / integration",
    "vendor_request": "Looking for an implementation partner or tech vendor",
    "operational_problem": "Publicly discussed operational problem",
    "integration_need": "Existing system needing integration",
    "new_facility": "New service centre / warehouse / branch",
    "expansion": "Expanding distribution or service operations",
    "modernisation": "Technology modernisation initiative",
}
SIGNAL_STRENGTH = {
    "explicit_software_request": "strong", "vendor_request": "strong", "operational_problem": "strong",
    "integration_need": "medium", "modernisation": "medium", "new_facility": "medium", "expansion": "medium",
}
_SW = r"(?:software|ERP|CRM|app|application|portal|automation|integration|API|dealer management|order management|" \
      r"inventory (?:management )?system|service management|field service|ticketing|DMS|billing system)"
SIGNAL_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("explicit_software_request", re.compile(
        rf"\b(?:looking for|seeking|requires?|need(?:s|ed)?|invit(?:e|es|ing)|request for (?:proposals?|quotations?)|RFP|RFQ|EOI|tender for)\b.{{0,60}}\b{_SW}\b", re.I | re.S)),
    ("vendor_request", re.compile(
        r"\b(?:implementation partner|technology partner|IT vendors?|software vendors?|system integrators?|vendor empanelment)\b.{0,40}\b(?:invited|wanted|required|looking|seeking|sought)\b|"
        r"\b(?:invit(?:e|es|ing)|looking for|seeking)\b.{0,40}\b(?:implementation partner|technology partner|IT vendors?|software vendors?|system integrators?)\b", re.I | re.S)),
    ("operational_problem", re.compile(
        r"\b(?:delays? in (?:delivery|deliveries|service|dispatch)|service backlog|stock-?outs?|manual (?:tracking|entry|records|processes)|"
        r"shortage of (?:technicians|service engineers)|missed service visits|billing errors)\b", re.I)),
    ("integration_need", re.compile(
        r"\b(?:integrat(?:e|ion) with|migrat(?:e|ion) (?:to|from))\b.{0,40}\b(?:Tally|SAP|ERP|Zoho|e-?invoic\w*|GST portal|e-?way bill|Shopify|marketplace)\b", re.I | re.S)),
    ("new_facility", re.compile(
        r"\b(?:inaugurat\w*|open(?:s|ed|ing)?|launch(?:es|ed)?|commission(?:s|ed)?|set(?:s|ting)? up)\b.{0,60}\b"
        r"(?:service cent(?:re|er)|warehouse|distribution cent(?:re|er)|branch|godown|depot|experience cent(?:re|er)|facility)\b", re.I | re.S)),
    ("expansion", re.compile(
        r"\b(?:expand\w*|expansion|scal(?:e|es|ing) up|appoint\w* (?:new )?(?:dealers|distributors)|new dealers|dealer network|distribution network)\b", re.I)),
    ("modernisation", re.compile(
        r"\b(?:digital transformation|digiti[sz]\w*|moderni[sz]\w*|automat(?:e|es|ed|ing|ion))\b.{0,60}\b(?:operations?|warehouse|service|distribution|supply chain|inventory)\b", re.I | re.S)),
]


def detect_signals(text: str) -> list[dict[str, str]]:
    """Keyword-rule signal candidates. They are HYPOTHESES until a human confirms them."""
    found = []
    for st, rx in SIGNAL_RULES:
        m = rx.search(text)
        if m:
            found.append({"signal_type": st, "strength": SIGNAL_STRENGTH[st], "excerpt": _excerpt(text, m)})
    return found


_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE_RX = [
    (re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b"), lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})[a-z]*\.?,?\s+(20\d{{2}})\b", re.I),
     lambda m: datetime(int(m[3]), _month(m[2]), int(m[1]))),
    (re.compile(rf"\b({_MONTHS})[a-z]*\.?\s+(\d{{1,2}}),?\s+(20\d{{2}})\b", re.I),
     lambda m: datetime(int(m[3]), _month(m[1]), int(m[2]))),
]


def _month(s: str) -> int:
    return [m for m in _MONTHS.split("|") if m != "sept"].index(s.lower()[:3]) + 1


def find_date_near(text: str, start: int, end: int, window: int = 200) -> datetime | None:
    """An explicit date written close to the excerpt (never inferred from anything else)."""
    chunk = text[max(0, start - window): end + window]
    for rx, conv in _DATE_RX:
        m = rx.search(chunk)
        if m:
            try:
                return conv(m)
            except ValueError:
                continue
    return None


def _excerpt(text: str, m: re.Match[str], pad: int = 120) -> str:
    s = text[max(0, m.start() - pad): m.end() + pad]
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------------------------------------
# Category A–D and sales difficulty
# ------------------------------------------------------------------------------------------------
A_RECENT_DAYS = 90
B_RECENT_DAYS = 180


@dataclass
class Signal:
    signal_type: str
    url: str
    published_at: datetime | None
    review_status: str  # hypothesis | confirmed | rejected
    excerpt: str = ""


@dataclass
class LeadFacts:
    name: str
    industry: str | None
    industry_strength: str  # strong | candidate | none
    location_status: str  # chennai_city | gcma_outside | outside | unknown
    location_verified: bool
    activity_status: str  # active | likely_active | unknown | inactive | closed
    has_contact_route: bool  # published phone/email with a source URL
    contact_from_official_site: bool
    signals: list[Signal] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    is_duplicate: bool = False
    eligibility_blocker: str | None = None  # e.g. "requires ISO 27001 vendor" (owner-entered)
    owner_rejected: bool = False
    branch_count: int | None = None
    legal_form: str | None = None  # from name only: "limited" | "private_limited" | None


def _age_days(dt: datetime | None, now: datetime) -> int | None:
    return None if dt is None else (now - dt).days


def categorise(f: LeadFacts, now: datetime) -> tuple[str, list[str]]:
    """Return (A|B|C|D, reasons). Rules are checked top-down; the first that fails explains the outcome."""
    # --- D: reject -------------------------------------------------------------------------------
    if f.owner_rejected:
        return "D", ["Rejected by the owner"]
    if f.is_duplicate:
        return "D", ["Duplicate of another lead"]
    if f.location_status == "outside":
        return "D", ["Outside Chennai"]
    if f.location_status == "gcma_outside":
        return "D", ["In the metropolitan area but outside Chennai city (not approved)"]
    if f.industry is None:
        return "D", ["Not a wholesale distributor or equipment sales & service company"]
    if f.activity_status in ("inactive", "closed"):
        return "D", [f"Business appears {f.activity_status}"]
    if f.eligibility_blocker:
        return "D", [f"Eligibility obstacle: {f.eligibility_blocker}"]

    live = [s for s in f.signals if s.review_status != "rejected" and s.url]
    ages = {id(s): _age_days(s.published_at, now) for s in live}
    intent_ok = [s for s in live if s.signal_type in INTENT_TYPES and s.review_status == "confirmed"
                 and ages[id(s)] is not None and 0 <= ages[id(s)] <= A_RECENT_DAYS]
    recent_any = [s for s in live if ages[id(s)] is not None and 0 <= ages[id(s)] <= B_RECENT_DAYS]

    # --- A: every condition must hold ------------------------------------------------------------
    a_missing = []
    if not (f.location_status == "chennai_city" and f.location_verified):
        a_missing.append("Chennai-city address not verified on an official source")
    if f.industry_strength != "strong":
        a_missing.append("industry match not confirmed by operations on the official website")
    if f.activity_status != "active":
        a_missing.append("recent activity not confirmed")
    if not intent_ok:
        a_missing.append(f"no confirmed, dated (≤{A_RECENT_DAYS} days) explicit requirement or operational problem")
    if not f.has_contact_route:
        a_missing.append("no public business contact route")
    if not a_missing:
        s = intent_ok[0]
        return "A", [
            "Verified Chennai-city operations",
            "Strong industry match (operations seen on official website)",
            f"Confirmed signal: {SIGNAL_LABEL.get(s.signal_type, s.signal_type)} ({ages[id(s)]} days old) — {s.url}",
            "Public contact route available",
            "No known eligibility obstacle",
        ]

    # --- B ---------------------------------------------------------------------------------------
    b_missing = []
    if not (f.location_status == "chennai_city" and f.location_verified):
        b_missing.append("Chennai-city address not verified")
    if f.activity_status not in ("active", "likely_active"):
        b_missing.append("business activity unclear")
    if not f.has_contact_route:
        b_missing.append("no public contact route")
    if not (recent_any or (f.industry_strength == "strong" and len(f.operations) >= 2)):
        b_missing.append(f"no dated signal in the last {B_RECENT_DAYS} days and too little operations evidence")
    if not b_missing:
        why = ["Verified Chennai-city business with relevant operations"]
        if recent_any:
            s = recent_any[0]
            why.append(f"Recent signal: {SIGNAL_LABEL.get(s.signal_type, s.signal_type)} ({ages[id(s)]} days) — {s.url}")
        else:
            why.append("Operations seen: " + ", ".join(f.operations[:4]))
        why.append("Plausible software need, but no confirmed buying intention: " + "; ".join(a_missing))
        return "B", why

    # --- C ---------------------------------------------------------------------------------------
    return "C", ["Watchlist — " + "; ".join(b_missing)]


def sales_difficulty(f: LeadFacts, now: datetime, suggested_services: list[str]) -> tuple[str, list[str]]:
    """Estimate how hard it is to approach (not a probability of winning)."""
    reasons: list[str] = []
    pts = 0
    known = 0
    live = [s for s in f.signals if s.review_status != "rejected"]
    if any(s.signal_type in INTENT_TYPES and s.review_status == "confirmed" for s in live):
        pts += 2; known += 1; reasons.append("+2 confirmed current need")
    elif any(_age_days(s.published_at, now) is not None and _age_days(s.published_at, now) <= B_RECENT_DAYS for s in live):
        pts += 1; known += 1; reasons.append("+1 recent operational signal (need not confirmed)")
    if f.contact_from_official_site:
        pts += 1; known += 1; reasons.append("+1 contact published on their own website")
    elif f.has_contact_route:
        known += 1; reasons.append("0 contact only from a directory listing")
    else:
        pts -= 1; reasons.append("−1 no public contact route")
    if suggested_services:
        pts += 1; known += 1; reasons.append("+1 needs fit Inferago's services (" + ", ".join(suggested_services[:3]) + ")")
    if f.legal_form == "limited":
        pts -= 2; known += 1; reasons.append("−2 public limited company: formal procurement likely")
    elif f.legal_form == "private_limited":
        known += 1; reasons.append("0 private limited company: vendor onboarding may apply")
    elif f.legal_form == "small_firm":
        pts += 1; known += 1; reasons.append("+1 owner-run firm (proprietorship/partnership style name): decision-maker likely reachable")
    if f.branch_count and f.branch_count >= 5:
        pts -= 1; reasons.append(f"−1 {f.branch_count} branches: more stakeholders")
    if f.eligibility_blocker:
        return "difficult", reasons + [f"Eligibility obstacle: {f.eligibility_blocker}"]
    if known < 2:
        return "unknown", reasons + ["Too little known to estimate"]
    if pts >= 3:
        return "easier", reasons
    if pts >= 1:
        return "moderate", reasons
    return "difficult", reasons


def legal_form(name: str | None) -> str | None:
    n = (name or "").lower()
    if re.search(r"\bprivate limited\b|\bpvt\.? ?ltd\b|\(p\) ?ltd", n):
        return "private_limited"
    if re.search(r"\blimited\b|\bltd\b", n):
        return "limited"
    if re.search(r"\b(enterprises|agencies|traders|associates|& co|and co|sons|brothers|bros)\b", n):
        return "small_firm"
    return None


def evidence_confidence(f: LeadFacts) -> str:
    confirmed = any(s.review_status == "confirmed" and s.published_at for s in f.signals)
    if f.location_verified and f.industry_strength == "strong" and confirmed:
        return "high"
    if f.location_verified or f.industry_strength == "strong" or any(s.published_at for s in f.signals):
        return "medium"
    return "low"


# ------------------------------------------------------------------------------------------------
# Problem → Inferago service (only services in app/profile.py)
# ------------------------------------------------------------------------------------------------
def suggest(industry: str | None, operations: list[str], signal_types: list[str]) -> tuple[str | None, str | None, list[str]]:
    """(potential problem, suggested solution, service keys). Phrased as hypotheses to check on a call."""
    ops = set(operations)
    sig = set(signal_types)
    if industry == WHOLESALE:
        problem = "May be taking dealer/retailer orders by phone or WhatsApp and tracking stock, dispatch and dues by hand or in separate tools"
        if "integration_need" in sig:
            problem = "Existing accounting/ERP system may need to connect with ordering, dispatch or e-invoicing"
        solution = "Dealer order portal + inventory and dispatch tracking, integrated with their accounting system (e.g. Tally)"
        return problem, solution, ["internal_apps", "integration", "api", "automation"]
    if industry == EQUIPMENT:
        problem = "May be scheduling technicians and tracking service calls, AMC renewals and warranties manually"
        if "amc_warranty" in ops:
            problem = "AMC/warranty contracts and renewal reminders may be tracked manually"
        solution = "Field-service app: service tickets, technician scheduling, AMC/warranty tracker and renewal reminders, customer status updates"
        return problem, solution, ["internal_apps", "automation", "crm", "integration"]
    return None, None, []


def next_action(category: str, location_verified: bool, industry_strength: str, has_contact: bool, has_unreviewed_signal: bool) -> str:
    if category == "D":
        return "No action (rejected)."
    if has_unreviewed_signal:
        return "Review the detected signal(s): open the source link, then confirm or reject."
    if category == "A":
        return "Review the brief and outreach draft, edit, then approve and contact them yourself."
    if not location_verified:
        return "Run 'Verify website' (or check the address yourself) to confirm a Chennai-city location."
    if industry_strength != "strong":
        return "Check their website for service/distribution operations before investing time."
    if not has_contact:
        return "Find a published business phone or email on their official website."
    if category == "B":
        return "Look for a current need (news, posts, tenders). Add any signal you find with its link and date."
    return "Keep on watchlist; re-check in 30 days."
