"""Chennai-only geography rules (deterministic).

Scope = Chennai city, meaning the Greater Chennai Corporation (GCC) area. Places in the wider
Chennai Metropolitan Area but outside the city (Tambaram, Avadi, Poonamallee, Sriperumbudur, OMR
beyond the city limit…) are OUT of scope unless the owner approves a locality (setting
`chennai_approved_localities`).

Rules:
- A location is decided from address TEXT only. A Chennai phone code (044) never counts.
- Directory text ("locality = Chennai" in Overture) is not verification: Overture labels many
  suburbs "Chennai". `location_verified` is set only when an official website (or a human) shows
  a Chennai-city address.
- An out-of-city locality wins over the word "Chennai" (addresses like "Tambaram, Chennai 600045"
  are common and are NOT in the city).
- If the text names no recognised locality and no core-city PIN code, the answer is `unknown`,
  never a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHENNAI_CITY = "chennai_city"
GCMA_OUTSIDE = "gcma_outside"
OUTSIDE = "outside"
UNKNOWN = "unknown"

# Coarse box around the GCC area (used only to pre-filter directory records; never as proof).
CITY_BBOX = (12.83, 80.15, 13.24, 80.33)  # lat_min, lon_min, lat_max, lon_max

# Localities inside the Greater Chennai Corporation limits.
CITY_LOCALITIES = (
    "t nagar", "thyagaraya nagar", "teynampet", "mylapore", "adyar", "besant nagar", "thiruvanmiyur", "velachery",
    "guindy", "saidapet", "kodambakkam", "vadapalani", "ashok nagar", "k k nagar", "kk nagar", "valasaravakkam",
    "virugambakkam", "saligramam", "alwarpet", "nungambakkam", "egmore", "kilpauk", "anna nagar", "aminjikarai",
    "arumbakkam", "koyambedu", "mogappair", "ambattur", "padi", "villivakkam", "kolathur", "perambur", "vyasarpadi",
    "tondiarpet", "royapuram", "george town", "parrys", "sowcarpet", "broadway", "park town", "purasawalkam",
    "purasaiwakkam", "vepery", "chetpet", "choolaimedu", "anna salai", "mount road", "triplicane", "chepauk",
    "royapettah", "gopalapuram", "r a puram", "raja annamalaipuram", "mandaveli", "alandur", "nanganallur",
    "adambakkam", "madipakkam", "pallikaranai", "perungudi", "thoraipakkam", "sholinganallur", "karapakkam",
    "neelankarai", "injambakkam", "palavakkam", "kottivakkam", "taramani", "kotturpuram", "ekkatuthangal",
    "ekkaduthangal", "thirumangalam", "maduravoyal", "ramapuram", "manapakkam", "mugalivakkam", "nesapakkam",
    "jafferkhanpet", "west mambalam", "mambalam", "kodungaiyur", "madhavaram", "manali", "tiruvottiyur",
    "thiruvottiyur", "ennore", "washermanpet", "korukkupet", "sembium", "ayanavaram", "otteri", "pulianthope",
    "basin bridge", "chintadripet", "thousand lights", "santhome", "kasimedu", "kellys", "shenoy nagar",
    "korattur", "pattaravakkam", "mannurpet", "nolambur", "k k nagar", "abiramapuram", "kosapet", "perambur barracks",
    "mint street", "anna nagar west", "anna nagar east", "periyar nagar", "kodambakkam high road", "guindy industrial estate",
    "ambattur industrial estate", "thiru vi ka industrial estate", "ekkattuthangal", "puzhuthivakkam", "ullagaram",
    "velacheri", "kandanchavadi", "kandhanchavadi", "mettukuppam",
)

# Chennai Metropolitan Area places OUTSIDE the city corporation (out of scope unless approved).
GCMA_OUTSIDE_LOCALITIES = (
    "tambaram", "pallavaram", "chromepet", "chrompet", "avadi", "poonamallee", "sriperumbudur", "chengalpattu",
    "guduvanchery", "guduvancheri", "oragadam", "irungattukottai", "thiruvallur", "tiruvallur", "kanchipuram",
    "kancheepuram", "ponneri", "minjur", "gummidipoondi", "kelambakkam", "siruseri", "navalur", "padur", "egattur",
    "thalambur", "medavakkam", "perumbakkam", "sithalapakkam", "mudichur", "selaiyur", "madambakkam", "chitlapakkam",
    "perungalathur", "vandalur", "urapakkam", "maraimalai nagar", "mangadu", "thiruverkadu", "thirumazhisai",
    "thiruninravur", "pattabiram", "moulivakkam", "gerugambakkam", "kovur", "kundrathur", "pammal", "anakaputhur",
    "pozhichalur", "polichalur", "thiruneermalai", "kolapakkam", "mappedu", "sholavaram", "red hills industrial",
    "mahindra world city", "singaperumal koil", "vallam vadagal", "chembarambakkam", "nemilichery", "thirumudivakkam",
    "tirumudivakkam", "thirumullaivoyal", "kattankulathur", "potheri", "vanagaram", "ayanambakkam",
)

# Places whose city-corporation status is mixed or uncertain: always sent to human review.
AMBIGUOUS_LOCALITIES = ("porur", "iyyappanthangal", "puzhal", "red hills", "semmancheri", "meenambakkam",
                        "st thomas mount", "st. thomas mount", "nandambakkam", "manapakkam porur")

OTHER_CITIES = (
    "bengaluru", "bangalore", "hyderabad", "secunderabad", "mumbai", "navi mumbai", "thane", "delhi", "new delhi",
    "noida", "gurgaon", "gurugram", "pune", "kolkata", "ahmedabad", "kochi", "cochin", "coimbatore", "madurai",
    "trichy", "tiruchirappalli", "salem", "erode", "tiruppur", "tirupur", "vellore", "hosur", "puducherry",
    "pondicherry", "tirunelveli", "thoothukudi", "tuticorin", "thanjavur", "kumbakonam", "karur", "namakkal",
    "dindigul", "nagercoil", "cuddalore", "villupuram", "krishnagiri", "dharmapuri", "visakhapatnam", "vijayawada",
    "nellore", "tirupati", "mysuru", "mysore", "mangaluru", "mangalore", "thiruvananthapuram", "trivandrum",
)

# PIN codes that lie in the core city. Supporting evidence only (with the word "Chennai");
# a PIN outside this list is not treated as out of scope by itself.
CORE_CITY_PINS = {f"6000{n:02d}" for n in range(1, 43)} | {
    "600078", "600083", "600085", "600086", "600090", "600093", "600094", "600096", "600097",
    "600101", "600102", "600106", "600107", "600113",
}

_PIN = re.compile(r"\b(6\d{2})\s?(\d{3})\b")


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return f" {re.sub(r' +', ' ', s).strip()} "


def _has(norm_text: str, phrase: str) -> bool:
    return f" {_norm(phrase).strip()} " in norm_text


def _first(norm_text: str, phrases) -> str | None:
    for p in phrases:
        if _has(norm_text, p):
            return p
    return None


@dataclass(frozen=True)
class LocationVerdict:
    status: str  # chennai_city | gcma_outside | outside | unknown
    reason: str
    locality: str | None = None
    pincode: str | None = None


def classify_location(*texts: str | None, approved: tuple[str, ...] | list[str] = ()) -> LocationVerdict:
    """Classify one address (possibly split across fields) as Chennai city / GCMA outside / outside / unknown."""
    raw = " , ".join(t for t in texts if t)
    if not raw.strip():
        return LocationVerdict(UNKNOWN, "No address text")
    n = _norm(raw)
    pins = ["".join(m.groups()) for m in _PIN.finditer(raw)]
    pin = next((p for p in pins if p.startswith("600") or p.startswith("601") or p.startswith("602") or p.startswith("603")), pins[0] if pins else None)
    says_chennai = _has(n, "chennai") or _has(n, "madras")

    approved_hit = _first(n, approved) if approved else None
    if approved_hit:
        return LocationVerdict(CHENNAI_CITY, f"Locality '{approved_hit}' approved by the owner", approved_hit, pin)

    outside_loc = _first(n, GCMA_OUTSIDE_LOCALITIES)
    if outside_loc:
        return LocationVerdict(GCMA_OUTSIDE, f"'{outside_loc}' is in the metropolitan area but outside Chennai city", outside_loc, pin)

    other = _first(n, OTHER_CITIES)
    if other and not says_chennai:
        return LocationVerdict(OUTSIDE, f"Address is in {other.title()}, not Chennai", other, pin)
    if pin and not pin.startswith("600") and not says_chennai:
        return LocationVerdict(OUTSIDE, f"PIN {pin} is not a Chennai PIN code", None, pin)

    amb = _first(n, AMBIGUOUS_LOCALITIES)
    if amb:
        return LocationVerdict(UNKNOWN, f"'{amb}' straddles the city limit: needs a human check", amb, pin)

    city_loc = _first(n, CITY_LOCALITIES)
    if city_loc:
        return LocationVerdict(CHENNAI_CITY, f"'{city_loc}' is inside Chennai city", city_loc, pin)
    if says_chennai and pin in CORE_CITY_PINS:
        return LocationVerdict(CHENNAI_CITY, f"Chennai address with core-city PIN {pin}", None, pin)
    if other:
        return LocationVerdict(UNKNOWN, f"Address mentions both Chennai and {other.title()}", other, pin)
    if says_chennai:
        return LocationVerdict(UNKNOWN, "Says 'Chennai' but names no locality inside the city limit" + (f" (PIN {pin})" if pin else ""), None, pin)
    return LocationVerdict(UNKNOWN, "No recognisable Chennai locality", None, pin)


def in_city_bbox(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    a, b, c, d = CITY_BBOX
    return a <= lat <= c and b <= lon <= d


def find_chennai_address(text: str, approved: tuple[str, ...] | list[str] = ()) -> tuple[LocationVerdict, str] | None:
    """Look through page text for an address mentioning Chennai. Prefers a city address if several exist.

    Returns (verdict, excerpt) or None when the page never mentions Chennai/Madras.
    """
    best: tuple[LocationVerdict, str] | None = None
    rank = {CHENNAI_CITY: 3, UNKNOWN: 1, GCMA_OUTSIDE: 2, OUTSIDE: 0}
    for m in re.finditer(r"chennai|madras", text, re.I):
        window = text[max(0, m.start() - 160): m.end() + 40]
        # Keep only the address-like tail of the window (after the last sentence break).
        window = re.split(r"(?<=[.!?])\s+(?=[A-Z])", window)[-1] if len(window) > 120 else window
        v = classify_location(window, approved=approved)
        excerpt = re.sub(r"\s+", " ", window).strip()
        if best is None or rank[v.status] > rank[best[0].status]:
            best = (v, excerpt)
        if v.status == CHENNAI_CITY:
            break
    return best
