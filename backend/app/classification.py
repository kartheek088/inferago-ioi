"""Deterministic, rule-based opportunity classification.

Rules run first and always. Optional AI classification (app.ai) may refine the result, but
its output is validated and recorded with method="ai"; rules remain the fallback.
"""

import re
from dataclasses import dataclass, field

from app.enums import CATEGORY_PIPELINE, Category, Pipeline

# ---------------------------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------------------------

SERVICE_PATTERNS: dict[str, list[str]] = {
    "backend": [
        r"back[- ]?end", r"server[- ]side", r"django", r"fastapi", r"flask", r"node\.?js", r"express",
        r"\bpython\b", r"\bjava\b", r"golang", r"\brails\b", r"postgres", r"mysql", r"database",
        r"web app(lication)?", r"\bsaas\b", r"\bmvp\b", r"software development", r"custom software",
        r"build (a|an|our|the) (platform|app|system|tool|product)",
    ],
    "api": [r"\bapis?\b", r"\brest(ful)?\b", r"graphql", r"webhooks?", r"endpoints?", r"third[- ]party integration"],
    "automation": [
        r"automat(e|ion|ing)", r"workflows?", r"zapier", r"\bn8n\b", r"make\.com", r"\brpa\b",
        r"manual process", r"scripts?\b",
    ],
    "internal_apps": [
        r"internal tools?", r"admin (panel|dashboard)", r"dashboards?", r"\bcrm\b", r"inventory",
        r"back[- ]office", r"(customer|vendor|employee|internal) portal", r"\berp\b", r"line[- ]of[- ]business",
    ],
    "integration": [
        r"integrat(e|ion|ions|ing)", r"\berp\b", r"\bsap\b", r"odoo", r"tally", r"zoho", r"salesforce",
        r"hubspot", r"migrat(e|ion)", r"digiti[sz](e|ation)", r"paperless", r"legacy", r"moderni[sz](e|ation)",
    ],
    "website": [
        r"\bwebsites?\b", r"landing page", r"web ?design", r"wordpress", r"shopify", r"woocommerce", r"webflow",
        r"e-?commerce (site|store)", r"online store", r"redesign (our|my|the) (site|website)",
    ],
    "marketing": [
        r"\bseo\b", r"digital marketing", r"social media (marketing|management)", r"google ads", r"\bppc\b",
        r"google (my )?business profile", r"lead generation", r"performance marketing", r"meta ads", r"email marketing",
    ],
    "crm": [r"\bcrm\b", r"zoho", r"hubspot", r"salesforce", r"pipedrive", r"freshsales", r"lead management"],
    "ai": [
        r"\bai\b", r"artificial intelligence", r"chat ?bots?", r"\bllms?\b", r"\bgpt\b", r"openai", r"\brag\b",
        r"machine learning", r"ai agents?", r"voice (bot|agent)", r"whatsapp bot",
    ],
    "erp": [r"\berp\b", r"\bsap\b", r"s/?4 ?hana", r"\babap\b", r"odoo", r"netsuite", r"dynamics 365", r"tally"],
    "strategy": [r"digital (strategy|transformation)", r"online presence", r"go[- ]digital", r"growth strategy"],
}

OUT_OF_SCOPE = [
    r"\blogo\b", r"graphic design", r"video edit", r"\bgame (dev|development)\b",
    r"unity3d", r"illustrat(or|ion)", r"copywrit", r"voice[- ]over", r"data entry",
]

# (pattern, signal_type, strength)
DIRECT_SIGNALS: list[tuple[str, str, str]] = [
    (r"seeking freelancer", "seeking_freelancer", "strong"),
    (r"\[\s*hiring\s*\]", "hiring_tag", "strong"),
    (r"\b(developer|expert|freelancer|consultant|builder) needed\b", "needed_post", "strong"),
    (r"looking for (a |an )?(freelance |contract |remote |experienced |senior )*(developer|dev|engineer|programmer|agency|dev shop|development (agency|team|partner|company)|contractor|consultant)s?", "looking_for_developer", "strong"),
    (r"(need|needs|needed|require|requires) (a |an )?(freelance |contract )?(developer|engineer|programmer|agency|contractor)", "needs_developer", "strong"),
    (r"(need|want|looking) (someone|somebody|help) to (build|develop|create|integrate|automate)", "needs_build", "strong"),
    (r"hire (a |an )?(freelancer|agency|contractor|dev shop)", "hire_external", "strong"),
    (r"request for proposals?|\brfp\b", "rfp", "strong"),
    (r"request for quotations?|\brfq\b|quote for", "rfq", "moderate"),
    (r"outsourc(e|ing) (software|development|our)", "outsourcing", "strong"),
    (r"(contract|freelance|fixed[- ]price|hourly) (role|project|gig|work|engagement|position)", "contract_work", "moderate"),
    (r"(budget|paying|pay) (is |of )?(\$|usd|inr|₹|rs\.?|eur|€|£)", "budget_stated", "moderate"),
    (r"api integration required|integration required", "integration_required", "strong"),
    (r"need (workflow )?automation|automate our", "automation_need", "strong"),
    (r"internal tool development", "internal_tool_need", "strong"),
    (r"(looking for|need|seeking|hire|hiring) (a |an )?(freelancer|freelance \w+|contractor)", "external_request", "moderate"),
    (r"\b\d+[- ](month|week)s?[- ]contract\b|\bcontract (role|basis|position|engagement|to hire)\b|\|\s*(contract|contractor|freelance)\s*(\||$)", "contract_engagement", "moderate"),
]

WEAK_SIGNALS: list[tuple[str, str, str]] = [
    (r"\bwe('| a)?re hiring\b|\bhiring\b", "hiring_employees", "weak"),
    (r"full[- ]time", "full_time_role", "weak"),
    (r"(planning|plan) to (build|launch|digiti[sz]e|automate)", "planning_project", "weak"),
    (r"exploring (options|vendors|tools)", "exploring", "weak"),
]

VENDOR_ONBOARDING = [
    r"vendor registration", r"supplier registration", r"vendor onboarding", r"supplier onboarding",
    r"empanel(l)?ment", r"become a (supplier|vendor)", r"supplier portal", r"vendor portal",
    r"register as a (vendor|supplier)", r"vendor enlistment",
]
SUBCONTRACTING = [
    r"sub[- ]?contract(or|ing|ors)?", r"white[- ]label", r"delivery partner", r"outsourcing partner",
    r"overflow (work|projects)", r"external (delivery|technical|implementation) (partner|team)",
    r"software implementation subcontractor",
]
IMPLEMENTATION_PARTNERSHIP = [
    r"implementation partners?", r"partner program(me)?", r"become a partner", r"\bsi partner",
    r"system integrators?", r"certified partners?", r"(erp|crm) partners?", r"technical implementation partner",
    r"channel partner",
]
GOV_TENDER = [
    r"\btender\b", r"e-?procurement", r"notice inviting tender", r"\bnit\b", r"\bgem\b", r"\bcppp\b",
    r"earnest money", r"\bemd\b", r"bid submission", r"government of", r"ministry of", r"municipal",
    r"\bpsu\b", r"department of",
]
PRIVATE_PROCUREMENT = [
    r"\brfp\b", r"\brfq\b", r"request for (proposal|quotation)", r"expression of interest", r"\beoi\b",
    r"procurement", r"invitation to bid", r"\bitb\b",
]
SELF_PROMOTION = [
    r"^\s*seeking work", r"who wants to be hired", r"^\s*freelancer\s*[|:]", r"available for (hire|work)",
    r"^\s*\[?\s*for[- ]hire\s*\]?", r"^\s*i can help you",
]
# Not a paying engagement for Inferago's services.
UNPAID = [r"\bunpaid\b", r"commission[- ](based|only)", r"equity[- ]only", r"revenue[- ]share only", r"looking for (bd|business development|referral) partners"]
EXTERNAL_VENDOR_POSITIVE = [
    r"freelanc", r"contract", r"agency", r"outsourc", r"vendor", r"consultant", r"remote", r"partner",
    r"fixed[- ]price", r"\brfp\b", r"tender", r"subcontract",
]
EXTERNAL_VENDOR_NEGATIVE = [r"full[- ]time", r"\bw-?2\b", r"on[- ]?site only", r"no agencies", r"no recruiters", r"employees only"]

# --- Geography (explicit statements only; never inferred from the platform's domain) ---------
TN_PLACES = [
    "tamil nadu", "chennai", "coimbatore", "madurai", "tiruchirappalli", "trichy", "salem", "tirunelveli",
    "erode", "vellore", "hosur", "tiruppur", "thanjavur", "kanchipuram", "sriperumbudur",
]
INDIA_PLACES = [
    "india", "bangalore", "bengaluru", "mumbai", "delhi", "new delhi", "hyderabad", "pune", "kolkata",
    "ahmedabad", "noida", "gurgaon", "gurugram", "kochi", "jaipur",
]
COUNTRY_PATTERNS: list[tuple[str, str]] = [
    (r"\bUSA\b|\bU\.S\.A?\.?|\bUnited States\b|\bUS\b(?=[\s,)/-]|$)", "United States"),
    (r"\bUnited Kingdom\b|\bUK\b|\bLondon\b|\bEngland\b", "United Kingdom"),
    (r"\bCanada\b|\bToronto\b|\bVancouver\b", "Canada"),
    (r"\bGermany\b|\bBerlin\b|\bMunich\b", "Germany"),
    (r"\bFrance\b|\bParis\b", "France"),
    (r"\bNetherlands\b|\bAmsterdam\b", "Netherlands"),
    (r"\bAustralia\b|\bSydney\b|\bMelbourne\b", "Australia"),
    (r"\bSingapore\b", "Singapore"),
    (r"\bUAE\b|\bDubai\b|\bAbu Dhabi\b|United Arab Emirates", "United Arab Emirates"),
    (r"\bSaudi Arabia\b|\bRiyadh\b", "Saudi Arabia"),
    (r"\bIreland\b|\bDublin\b", "Ireland"),
    (r"\bSpain\b|\bMadrid\b|\bBarcelona\b", "Spain"),
    (r"\bSweden\b|\bStockholm\b", "Sweden"),
    (r"\bSri Lanka\b|\bColombo\b", "Sri Lanka"),
    (r"\bNew Zealand\b", "New Zealand"),
    (r"\bJapan\b|\bTokyo\b|\bOsaka\b", "Japan"),
    (r"\bSwitzerland\b|\bGeneva\b|\bZurich\b|\bZürich\b", "Switzerland"),
    (r"\bItaly\b|\bMilan\b|\bRome\b", "Italy"),
    (r"\bPoland\b|\bWarsaw\b|\bKrakow\b", "Poland"),
    (r"\bPortugal\b|\bLisbon\b", "Portugal"),
    (r"\bBrazil\b|\bSão Paulo\b|\bSao Paulo\b", "Brazil"),
    (r"\bMexico\b", "Mexico"),
    (r"\bIsrael\b|\bTel Aviv\b", "Israel"),
    (r"\bSouth Africa\b|\bCape Town\b|\bJohannesburg\b", "South Africa"),
    (r"\bKenya\b|\bNairobi\b", "Kenya"),
    (r"\bNigeria\b|\bLagos\b", "Nigeria"),
    (r"\bPhilippines\b|\bManila\b", "Philippines"),
    (r"\bIndonesia\b|\bJakarta\b", "Indonesia"),
    (r"\bMalaysia\b|\bKuala Lumpur\b", "Malaysia"),
    (r"\bVietnam\b|\bHo Chi Minh\b|\bHanoi\b", "Vietnam"),
    (r"\bPakistan\b|\bKarachi\b|\bLahore\b", "Pakistan"),
    (r"\bBangladesh\b|\bDhaka\b", "Bangladesh"),
    (r"\bNepal\b|\bKathmandu\b", "Nepal"),
    (r"\bDenmark\b|\bCopenhagen\b", "Denmark"),
    (r"\bNorway\b|\bOslo\b", "Norway"),
    (r"\bFinland\b|\bHelsinki\b", "Finland"),
    (r"\bAustria\b|\bVienna\b", "Austria"),
    (r"\bBelgium\b|\bBrussels\b", "Belgium"),
    (r"\bEstonia\b|\bTallinn\b", "Estonia"),
    (r"\bQatar\b|\bDoha\b", "Qatar"),
    (r"\bSan Francisco\b|\bNew York\b|\bNYC\b|\bSeattle\b|\bAustin\b|\bBoston\b|\bChicago\b|\bLos Angeles\b|\bSF\b|\bBay Area\b", "United States"),
]
RESTRICTION_PATTERNS: list[tuple[str, str]] = [
    (r"\b(US|USA|U\.S\.)[- ]?(only|based( only)?)\b|must be (located|based) in the (US|United States)|us citizens? only|(US|U\.S\.) work authori[sz]ation", "United States"),
    (r"\b(UK)[- ]?(only|based only)\b|must be (located|based) in the UK|right to work in the UK", "United Kingdom"),
    (r"\b(EU|Europe)[- ]?(only|based only)\b|must be (located|based) in (the )?(EU|Europe)", "European Union"),
    (r"\b(Canada)[- ]?(only)\b|must be (located|based) in Canada", "Canada"),
    (r"\b(Australia)[- ]?(only)\b|must be (located|based) in Australia", "Australia"),
    (r"\b(timezone|time zone)s?:?\s*(US|EST|PST|CET) only", "Timezone-restricted"),
]
# "Remote (EU)", "Remote - UK or EU": probably location-limited, but not explicit → soft (non-mandatory).
_REG = r"(?:USA|US|UK|EU|Europe|Canada|Australia)"
SOFT_REMOTE_RE = re.compile(r"remote\s*[(\-–:]\s*(" + _REG + r"(?:\s*(?:or|/|,|&|and)\s*" + _REG + r")*)\b(?![^)\n|]*(?:time|overlap|hours|tz))", re.I)
REGION_NAMES = {"US": "United States", "USA": "United States", "UK": "United Kingdom", "EU": "European Union", "EUROPE": "European Union", "CANADA": "Canada", "AUSTRALIA": "Australia"}
WORLDWIDE = [r"\bworldwide\b", r"\banywhere\b", r"\bglobal(ly)?\b remote", r"remote \(global\)", r"remote \(worldwide\)"]

BUDGET_RE = re.compile(
    r"((?:US)?\$\s?\d[\d,]*(?:\.\d+)?\s?(?:k|K)?(?:\s?[-–]\s?\$?\d[\d,]*(?:k|K)?)?(?:\s?(?:/|per)\s?(?:hr|hour|month|mo))?"
    r"|(?:₹|INR|Rs\.?)\s?\d[\d,]*(?:\.\d+)?\s?(?:lakhs?|crores?|L|Cr)?"
    r"|\d[\d,.]*\s?(?:lakhs?|crores?)"
    r"|(?:€|EUR|£|GBP)\s?\d[\d,]*(?:\.\d+)?\s?(?:k|K)?)",
)


@dataclass
class Signal:
    signal_type: str
    strength: str
    text: str


@dataclass
class ClassificationResult:
    category: Category
    pipeline: Pipeline
    confidence: float
    evidence: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    country: str | None = None
    region: str | None = None
    geography_basis: str | None = None
    country_restrictions: list[tuple[str, str, bool]] = field(default_factory=list)  # (countries '|'-joined, excerpt, hard)
    remote_ok: bool | None = None
    worldwide: bool = False
    budget_text: str | None = None
    vendor_positive: list[str] = field(default_factory=list)
    vendor_negative: list[str] = field(default_factory=list)
    method: str = "rules"


def _snippet(text: str, m: re.Match, width: int = 70) -> str:
    start = max(0, m.start() - width)
    end = min(len(text), m.end() + width)
    s = text[start:end].replace("\n", " ").strip()
    return ("…" if start else "") + s + ("…" if end < len(text) else "")


def _find(patterns: list[str], text: str, flags=re.I) -> list[re.Match]:
    out = []
    for p in patterns:
        m = re.search(p, text, flags | re.M)
        if m:
            out.append(m)
    return out


def detect_geography(text: str) -> tuple[str | None, str | None, str | None]:
    """Return (country, region, basis) from the EARLIEST explicit place mention in the text.

    Never inferred from a platform's domain; unknown stays (None, None, None).
    """
    best: tuple[int, str, str | None, str] | None = None
    low = text.lower()

    def consider(pos: int, country: str, region: str | None, matched: str) -> None:
        nonlocal best
        if best is None or pos < best[0]:
            best = (pos, country, region, matched)

    for place in TN_PLACES:
        m = re.search(r"\b" + re.escape(place) + r"\b", low)
        if m:
            consider(m.start(), "India", "Tamil Nadu", text[m.start():m.end()])
    for place in INDIA_PLACES:
        m = re.search(r"\b" + re.escape(place) + r"\b", low)
        if m:
            consider(m.start(), "India", None, text[m.start():m.end()])
    for pat, country in COUNTRY_PATTERNS:
        m = re.search(pat, text)
        if m:
            consider(m.start(), country, None, m.group(0).strip())
    if best is None:
        return None, None, None
    _, country, region, matched = best
    return country, region, f"Text mentions '{matched}'"


def match_services(text: str) -> list[str]:
    found = []
    for key, pats in SERVICE_PATTERNS.items():
        if any(re.search(p, text, re.I) for p in pats):
            found.append(key)
    return found


def classify(title: str | None, text: str | None, *, source_category: str | None = None) -> ClassificationResult:
    title = title or ""
    body = text or ""
    full = f"{title}\n{body}".strip()
    if not full:
        return ClassificationResult(Category.UNKNOWN, Pipeline.NONE, 0.0, ["No text available"])

    r = ClassificationResult(Category.UNKNOWN, Pipeline.NONE, 0.0)
    r.services = match_services(full)
    r.out_of_scope = [m.group(0) for m in _find(OUT_OF_SCOPE, full)]
    r.country, r.region, r.geography_basis = detect_geography(full)
    for pat, country in RESTRICTION_PATTERNS:
        m = re.search(pat, full, re.I)
        if m:
            r.country_restrictions.append((country, _snippet(full, m, 50), True))
    if not r.country_restrictions:
        m = SOFT_REMOTE_RE.search(full)
        if m:
            names = [REGION_NAMES[t.upper()] for t in re.findall(r"USA|US|UK|EU|Europe|Canada|Australia", m.group(1), re.I)]
            if names:
                r.country_restrictions.append(("|".join(dict.fromkeys(names)), _snippet(full, m, 50), False))
    r.worldwide = bool(_find(WORLDWIDE, full))
    if re.search(r"\bremote\b", full, re.I):
        r.remote_ok = True
    elif re.search(r"on[- ]?site only|no remote", full, re.I):
        r.remote_ok = False
    bm = BUDGET_RE.search(full)
    if bm:
        r.budget_text = bm.group(0).strip()[:100]
    r.vendor_positive = [m.group(0) for m in _find(EXTERNAL_VENDOR_POSITIVE, full)]
    r.vendor_negative = [m.group(0) for m in _find(EXTERNAL_VENDOR_NEGATIVE, full)]

    for pat, stype, strength in DIRECT_SIGNALS + WEAK_SIGNALS:
        m = re.search(pat, full, re.I | re.M)
        if m:
            r.signals.append(Signal(stype, strength, _snippet(full, m)))

    # Self-promotion (people offering services) is not demand.
    promo = _find(SELF_PROMOTION, full)
    if promo and not any(s.signal_type == "seeking_freelancer" for s in r.signals):
        r.category = Category.IRRELEVANT
        r.confidence = 0.85
        r.evidence = [f"Self-promotion / offer of services: '{promo[0].group(0).strip()}'"]
        r.signals = []
        r.pipeline = CATEGORY_PIPELINE[r.category]
        return r

    unpaid = _find(UNPAID, full)
    if unpaid:
        r.category, r.confidence, r.pipeline = Category.IRRELEVANT, 0.75, CATEGORY_PIPELINE[Category.IRRELEVANT]
        r.evidence = [f"Not a paid engagement: '{unpaid[0].group(0)}'"]
        return r

    gov = _find(GOV_TENDER, full)
    vend = _find(VENDOR_ONBOARDING, full)
    sub = _find(SUBCONTRACTING, full)
    impl = _find(IMPLEMENTATION_PARTNERSHIP, full)
    proc = _find(PRIVATE_PROCUREMENT, full)
    strong = [s for s in r.signals if s.strength in ("strong", "moderate")]
    weak = [s for s in r.signals if s.strength == "weak"]

    def pick(cat: Category, conf: float, ev: list[str]) -> None:
        r.category, r.confidence, r.evidence = cat, conf, ev

    if (len(gov) >= 2 or source_category == "government_procurement") and (gov or proc):
        pick(Category.GOVERNMENT_TENDER, min(0.95, 0.6 + 0.1 * len(gov)), [f"Tender indicator: '{m.group(0)}'" for m in gov[:4]])
    elif vend:
        pick(Category.VENDOR_ONBOARDING, min(0.9, 0.65 + 0.1 * len(vend)), [f"Vendor onboarding indicator: '{m.group(0)}'" for m in vend[:3]])
    elif sub:
        pick(Category.SUBCONTRACTING, min(0.9, 0.6 + 0.1 * len(sub)), [f"Subcontracting indicator: '{m.group(0)}'" for m in sub[:3]])
    elif impl:
        pick(Category.IMPLEMENTATION_PARTNERSHIP, min(0.85, 0.55 + 0.1 * len(impl)), [f"Partnership indicator: '{m.group(0)}'" for m in impl[:3]])
    elif proc and not strong:
        pick(Category.PRIVATE_PROCUREMENT, min(0.85, 0.55 + 0.1 * len(proc)), [f"Procurement indicator: '{m.group(0)}'" for m in proc[:3]])
    elif strong:
        conf = 0.55 + 0.1 * len(strong) + (0.1 if r.services else 0)
        pick(Category.DIRECT_SOFTWARE_PROJECT, min(0.95, conf), [f"Buying signal ({s.signal_type}): {s.text}" for s in strong[:3]])
    elif weak:
        pick(Category.WEAK_BUYING_SIGNAL, 0.5, [f"Weak signal ({s.signal_type}): {s.text}" for s in weak[:3]])
    elif source_category in ("business_directory", "company_website"):
        pick(Category.GENERAL_ORGANISATION, 0.5, ["Organisation record without an explicit buying signal"])
    else:
        pick(Category.UNKNOWN, 0.2, ["No recognised buying, vendor or procurement signal"])

    # Demand outside approved services is irrelevant (no new service categories without approval).
    if r.category in (Category.DIRECT_SOFTWARE_PROJECT, Category.WEAK_BUYING_SIGNAL) and not r.services:
        if r.out_of_scope:
            pick(Category.IRRELEVANT, 0.7, [f"Request appears outside approved services: '{r.out_of_scope[0]}'"])
        else:
            r.confidence = min(r.confidence, 0.5)
            r.evidence.append("No approved service keywords matched; service fit unknown")

    r.pipeline = CATEGORY_PIPELINE[r.category]
    r.confidence = round(r.confidence, 2)
    return r
