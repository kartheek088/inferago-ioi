"""Prospect finder: businesses and independent professionals who MAY need Inferago's services.

They have not asked for anything. We look for *potential*: an active, reachable business with
no website, a weak website, or (for larger firms) signs they could use ERP/CRM/automation.

Data source: OpenStreetMap via a public Overpass API mirror (ODbL). The main overpass-api.de
instance disallows /api/ in robots.txt, so it is NOT used; SafeHttp enforces robots.txt anyway.

Rules kept from the rest of IOI:
- Facts come only from the OSM record (`source_url`) or a recorded website audit. No guessed
  emails, phones or websites.
- Scores are deterministic and every point has a reason.
- Nothing is sent. The pitch is a draft; the owner contacts the prospect by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from html import unescape
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.http_client import FetchError, SafeHttp
from app.models import Prospect, ProspectRun
from app.profile import SERVICE_KEYS

# Bump when scoring / exclusion rules change: existing prospects are then re-checked once at startup.
RULES_VERSION = "2026-11-22.3"

OVERPASS_ENDPOINTS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# --------------------------------------------------------------------------------------------
# Search areas (city centres). Owner can also enter "Name@lat,lon".
# --------------------------------------------------------------------------------------------
AREAS: dict[str, tuple[float, float, str, str]] = {
    # Tamil Nadu (local first)
    "Chennai": (13.0827, 80.2707, "India", "Tamil Nadu"),
    "Coimbatore": (11.0168, 76.9558, "India", "Tamil Nadu"),
    "Madurai": (9.9252, 78.1198, "India", "Tamil Nadu"),
    "Tiruchirappalli": (10.7905, 78.7047, "India", "Tamil Nadu"),
    "Salem": (11.6643, 78.1460, "India", "Tamil Nadu"),
    "Tiruppur": (11.1085, 77.3411, "India", "Tamil Nadu"),
    "Erode": (11.3410, 77.7172, "India", "Tamil Nadu"),
    "Tirunelveli": (8.7139, 77.7567, "India", "Tamil Nadu"),
    "Vellore": (12.9165, 79.1325, "India", "Tamil Nadu"),
    "Hosur": (12.7409, 77.8253, "India", "Tamil Nadu"),
    "Thanjavur": (10.7870, 79.1378, "India", "Tamil Nadu"),
    "Kanchipuram": (12.8342, 79.7036, "India", "Tamil Nadu"),
    "Nagercoil": (8.1833, 77.4119, "India", "Tamil Nadu"),
    "Thoothukudi": (8.7642, 78.1348, "India", "Tamil Nadu"),
    "Karur": (10.9601, 78.0766, "India", "Tamil Nadu"),
    "Dindigul": (10.3673, 77.9803, "India", "Tamil Nadu"),
    "Puducherry": (11.9416, 79.8083, "India", "Puducherry"),
    # Rest of India
    "Bengaluru": (12.9716, 77.5946, "India", "Karnataka"),
    "Hyderabad": (17.3850, 78.4867, "India", "Telangana"),
    "Mumbai": (19.0760, 72.8777, "India", "Maharashtra"),
    "Delhi": (28.6139, 77.2090, "India", "Delhi"),
    "Pune": (18.5204, 73.8567, "India", "Maharashtra"),
    "Kolkata": (22.5726, 88.3639, "India", "West Bengal"),
    "Ahmedabad": (23.0225, 72.5714, "India", "Gujarat"),
    "Kochi": (9.9312, 76.2673, "India", "Kerala"),
    "Thiruvananthapuram": (8.5241, 76.9366, "India", "Kerala"),
    "Mysuru": (12.2958, 76.6394, "India", "Karnataka"),
    "Visakhapatnam": (17.6868, 83.2185, "India", "Andhra Pradesh"),
    "Jaipur": (26.9124, 75.7873, "India", "Rajasthan"),
    "Indore": (22.7196, 75.8577, "India", "Madhya Pradesh"),
    "Bhopal": (23.2599, 77.4126, "India", "Madhya Pradesh"),
    "Gwalior": (26.2183, 78.1828, "India", "Madhya Pradesh"),
    "Jabalpur": (23.1815, 79.9864, "India", "Madhya Pradesh"),
    "Lucknow": (26.8467, 80.9462, "India", "Uttar Pradesh"),
    "Kanpur": (26.4499, 80.3319, "India", "Uttar Pradesh"),
    "Agra": (27.1767, 78.0081, "India", "Uttar Pradesh"),
    "Varanasi": (25.3176, 82.9739, "India", "Uttar Pradesh"),
    "Meerut": (28.9845, 77.7064, "India", "Uttar Pradesh"),
    "Prayagraj": (25.4358, 81.8463, "India", "Uttar Pradesh"),
    "Noida": (28.5355, 77.391, "India", "Uttar Pradesh"),
    "Gurugram": (28.4595, 77.0266, "India", "Haryana"),
    "Faridabad": (28.4089, 77.3178, "India", "Haryana"),
    "Chandigarh": (30.7333, 76.7794, "India", "Chandigarh"),
    "Ludhiana": (30.901, 75.8573, "India", "Punjab"),
    "Amritsar": (31.634, 74.8723, "India", "Punjab"),
    "Dehradun": (30.3165, 78.0322, "India", "Uttarakhand"),
    "Shimla": (31.1048, 77.1734, "India", "Himachal Pradesh"),
    "Jammu": (32.7266, 74.857, "India", "Jammu and Kashmir"),
    "Srinagar": (34.0837, 74.7973, "India", "Jammu and Kashmir"),
    "Jodhpur": (26.2389, 73.0243, "India", "Rajasthan"),
    "Udaipur": (24.5854, 73.7125, "India", "Rajasthan"),
    "Kota": (25.2138, 75.8648, "India", "Rajasthan"),
    "Surat": (21.1702, 72.8311, "India", "Gujarat"),
    "Vadodara": (22.3072, 73.1812, "India", "Gujarat"),
    "Rajkot": (22.3039, 70.8022, "India", "Gujarat"),
    "Nagpur": (21.1458, 79.0882, "India", "Maharashtra"),
    "Nashik": (19.9975, 73.7898, "India", "Maharashtra"),
    "Aurangabad": (19.8762, 75.3433, "India", "Maharashtra"),
    "Kolhapur": (16.705, 74.2433, "India", "Maharashtra"),
    "Panaji": (15.4909, 73.8278, "India", "Goa"),
    "Mangaluru": (12.9141, 74.856, "India", "Karnataka"),
    "Hubballi": (15.3647, 75.124, "India", "Karnataka"),
    "Belagavi": (15.8497, 74.4977, "India", "Karnataka"),
    "Vijayawada": (16.5062, 80.648, "India", "Andhra Pradesh"),
    "Guntur": (16.3067, 80.4365, "India", "Andhra Pradesh"),
    "Tirupati": (13.6288, 79.4192, "India", "Andhra Pradesh"),
    "Warangal": (17.9689, 79.5941, "India", "Telangana"),
    "Kozhikode": (11.2588, 75.7804, "India", "Kerala"),
    "Thrissur": (10.5276, 76.2144, "India", "Kerala"),
    "Kollam": (8.8932, 76.6141, "India", "Kerala"),
    "Patna": (25.5941, 85.1376, "India", "Bihar"),
    "Ranchi": (23.3441, 85.3096, "India", "Jharkhand"),
    "Raipur": (21.2514, 81.6296, "India", "Chhattisgarh"),
    "Bhubaneswar": (20.2961, 85.8245, "India", "Odisha"),
    "Cuttack": (20.4625, 85.883, "India", "Odisha"),
    "Guwahati": (26.1445, 91.7362, "India", "Assam"),
    "Siliguri": (26.7271, 88.3953, "India", "West Bengal"),
    "Durgapur": (23.5204, 87.3119, "India", "West Bengal"),
    "Shillong": (25.5788, 91.8933, "India", "Meghalaya"),
    "Imphal": (24.817, 93.9368, "India", "Manipur"),
    # International
    "Dubai": (25.2048, 55.2708, "United Arab Emirates", "Dubai"),
    "Abu Dhabi": (24.4539, 54.3773, "United Arab Emirates", "Abu Dhabi"),
    "Sharjah": (25.3463, 55.4209, "United Arab Emirates", "Sharjah"),
    "Doha": (25.2854, 51.5310, "Qatar", "Doha"),
    "Riyadh": (24.7136, 46.6753, "Saudi Arabia", "Riyadh"),
    "Muscat": (23.5880, 58.3829, "Oman", "Muscat"),
    "Kuwait City": (29.3759, 47.9774, "Kuwait", "Kuwait"),
    "Singapore": (1.3521, 103.8198, "Singapore", "Singapore"),
    "Kuala Lumpur": (3.1390, 101.6869, "Malaysia", "Kuala Lumpur"),
    "Colombo": (6.9271, 79.8612, "Sri Lanka", "Western"),
    "London": (51.5074, -0.1278, "United Kingdom", "England"),
    "Leicester": (52.6369, -1.1398, "United Kingdom", "England"),
    "Manchester": (53.4808, -2.2426, "United Kingdom", "England"),
    "New York": (40.7128, -74.0060, "United States", "New York"),
    "Houston": (29.7604, -95.3698, "United States", "Texas"),
    "Dallas": (32.7767, -96.7970, "United States", "Texas"),
    "Toronto": (43.6532, -79.3832, "Canada", "Ontario"),
    "Sydney": (-33.8688, 151.2093, "Australia", "New South Wales"),
    "Melbourne": (-37.8136, 144.9631, "Australia", "Victoria"),
    "Auckland": (-36.8485, 174.7633, "New Zealand", "Auckland"),
    "Nairobi": (-1.2921, 36.8219, "Kenya", "Nairobi"),
}

AREA_GROUPS = {
    "Tamil Nadu": [k for k, v in AREAS.items() if v[3] in ("Tamil Nadu", "Puducherry")],
    "Rest of India": [k for k, v in AREAS.items() if v[2] == "India" and v[3] not in ("Tamil Nadu", "Puducherry")],
    "International": [k for k, v in AREAS.items() if v[2] != "India"],
}

_CUSTOM_AREA = re.compile(r"^\s*(?P<name>[^@]{1,80})@\s*(?P<lat>-?\d{1,2}(\.\d+)?)\s*,\s*(?P<lon>-?\d{1,3}(\.\d+)?)\s*$")


def resolve_area(spec: str) -> tuple[str, float, float, str | None]:
    """Return (name, lat, lon, country). Raises ValueError for unknown areas."""
    if spec in AREAS:
        lat, lon, country, _ = AREAS[spec]
        return spec, lat, lon, country
    for name, (lat, lon, country, _) in AREAS.items():
        if name.lower() == spec.strip().lower():
            return name, lat, lon, country
    m = _CUSTOM_AREA.match(spec)
    if m:
        lat, lon = float(m["lat"]), float(m["lon"])
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return m["name"].strip(), lat, lon, None  # country unknown — never guessed
    raise ValueError(f"Unknown area '{spec}'. Use a listed city or 'Name@lat,lon'.")


# --------------------------------------------------------------------------------------------
# Business types → segment, label, value tier, services
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class BizType:
    segment: str  # small_business | professional | enterprise
    label: str
    tier: int  # 3 high value, 2 medium, 1 low
    services: tuple[str, ...]


_APPT = ("website", "marketing", "crm", "ai")  # appointment / enquiry driven
_RETAIL = ("website", "marketing", "strategy")
_PRO = ("website", "marketing", "crm", "ai")
_ENT = ("erp", "crm", "automation", "integration", "website")

TYPES: dict[str, BizType] = {
    # professionals / independents
    "office=lawyer": BizType("professional", "Lawyer / law firm", 3, _PRO),
    "office=accountant": BizType("professional", "Accountant / auditor", 3, _PRO),
    "office=tax_advisor": BizType("professional", "Tax consultant", 3, _PRO),
    "office=architect": BizType("professional", "Architect", 3, _PRO),
    "office=estate_agent": BizType("professional", "Real-estate agent", 3, _PRO),
    "office=insurance": BizType("professional", "Insurance agent", 2, _PRO),
    "office=financial_advisor": BizType("professional", "Financial advisor", 3, _PRO),
    "office=financial": BizType("professional", "Financial services", 2, _PRO),
    "office=consulting": BizType("professional", "Consultant", 2, _PRO),
    "office=notary": BizType("professional", "Notary", 2, _PRO),
    "office=surveyor": BizType("professional", "Surveyor", 2, _PRO),
    "office=travel_agent": BizType("small_business", "Travel agency", 3, _APPT),
    "office=educational_institution": BizType("small_business", "Coaching / training institute", 3, _APPT),
    "office=company": BizType("small_business", "Company office", 2, ("website", "crm", "automation", "erp")),
    "office=coworking": BizType("small_business", "Co-working space", 2, _APPT),
    "healthcare=doctor": BizType("professional", "Doctor / clinic", 3, _APPT),
    "amenity=doctors": BizType("professional", "Doctor / clinic", 3, _APPT),
    "healthcare=dentist": BizType("professional", "Dentist", 3, _APPT),
    "amenity=dentist": BizType("professional", "Dentist", 3, _APPT),
    "healthcare=clinic": BizType("small_business", "Clinic", 3, _APPT),
    "amenity=clinic": BizType("small_business", "Clinic", 3, _APPT),
    "healthcare=hospital": BizType("small_business", "Hospital", 3, ("website", "crm", "ai", "erp", "marketing")),
    "amenity=hospital": BizType("small_business", "Hospital", 3, ("website", "crm", "ai", "erp", "marketing")),
    "healthcare=physiotherapist": BizType("professional", "Physiotherapist", 3, _APPT),
    "healthcare=optometrist": BizType("professional", "Optometrist", 2, _APPT),
    "healthcare=alternative": BizType("professional", "Ayurveda / alternative medicine", 2, _APPT),
    "healthcare=laboratory": BizType("small_business", "Diagnostic lab", 3, _APPT),
    "amenity=veterinary": BizType("professional", "Veterinary clinic", 2, _APPT),
    "craft=photographer": BizType("professional", "Photographer", 2, _PRO),
    "shop=photo": BizType("professional", "Photo studio", 2, _PRO),
    "craft=tailor": BizType("professional", "Tailor / boutique", 1, _RETAIL),
    "craft=electrician": BizType("professional", "Electrician", 1, ("website", "marketing")),
    "craft=plumber": BizType("professional", "Plumber", 1, ("website", "marketing")),
    "craft=carpenter": BizType("professional", "Carpenter / furniture maker", 2, _RETAIL),
    "craft=caterer": BizType("small_business", "Caterer", 2, _APPT),
    # small businesses
    "amenity=restaurant": BizType("small_business", "Restaurant", 2, ("website", "marketing", "ai")),
    "amenity=cafe": BizType("small_business", "Cafe", 2, ("website", "marketing")),
    "amenity=fast_food": BizType("small_business", "Fast food", 1, ("website", "marketing")),
    "amenity=driving_school": BizType("small_business", "Driving school", 3, _APPT),
    "amenity=language_school": BizType("small_business", "Language school", 3, _APPT),
    "amenity=school": BizType("small_business", "School", 3, ("website", "crm", "erp", "marketing")),
    "amenity=kindergarten": BizType("small_business", "Play school / kindergarten", 3, _APPT),
    "amenity=pharmacy": BizType("small_business", "Pharmacy", 2, ("website", "marketing", "crm")),
    "tourism=hotel": BizType("small_business", "Hotel", 3, ("website", "marketing", "crm", "ai")),
    "tourism=guest_house": BizType("small_business", "Guest house", 3, ("website", "marketing", "ai")),
    "tourism=hostel": BizType("small_business", "Hostel", 2, ("website", "marketing")),
    "tourism=motel": BizType("small_business", "Motel / lodge", 2, ("website", "marketing")),
    "leisure=fitness_centre": BizType("small_business", "Gym / fitness centre", 3, _APPT),
    "leisure=sports_centre": BizType("small_business", "Sports centre / academy", 2, _APPT),
    "leisure=dance": BizType("small_business", "Dance studio", 2, _APPT),
    "shop=hairdresser": BizType("small_business", "Salon", 2, _APPT),
    "shop=beauty": BizType("small_business", "Beauty parlour / spa", 2, _APPT),
    "shop=jewelry": BizType("small_business", "Jewellery shop", 3, ("website", "marketing", "crm")),
    "shop=furniture": BizType("small_business", "Furniture showroom", 3, _RETAIL),
    "shop=car": BizType("small_business", "Car dealer", 3, ("website", "crm", "marketing")),
    "shop=motorcycle": BizType("small_business", "Two-wheeler dealer", 3, ("website", "crm", "marketing")),
    "shop=car_repair": BizType("small_business", "Car service centre", 2, _APPT),
    "shop=optician": BizType("small_business", "Optician", 2, _RETAIL),
    "shop=clothes": BizType("small_business", "Clothing store", 2, ("website", "marketing", "strategy")),
    "shop=boutique": BizType("small_business", "Boutique", 2, ("website", "marketing", "strategy")),
    "shop=fabric": BizType("small_business", "Textiles / silk store", 2, ("website", "marketing", "strategy")),
    "shop=electronics": BizType("small_business", "Electronics store", 2, _RETAIL),
    "shop=mobile_phone": BizType("small_business", "Mobile store", 1, _RETAIL),
    "shop=computer": BizType("small_business", "Computer store", 2, _RETAIL),
    "shop=hardware": BizType("small_business", "Hardware store", 2, ("website", "marketing", "erp")),
    "shop=doityourself": BizType("small_business", "Building materials", 2, ("website", "marketing", "erp")),
    "shop=bakery": BizType("small_business", "Bakery / sweets", 2, _RETAIL),
    "shop=confectionery": BizType("small_business", "Sweets shop", 2, _RETAIL),
    "shop=supermarket": BizType("small_business", "Supermarket", 2, ("website", "marketing", "erp")),
    "shop=interior_decoration": BizType("small_business", "Interior designer", 3, _PRO),
    "shop=wedding": BizType("small_business", "Wedding services", 3, _APPT),
    "shop=travel_agency": BizType("small_business", "Travel agency", 3, _APPT),
    "shop=gift": BizType("small_business", "Gift shop", 1, _RETAIL),
    "shop=shoes": BizType("small_business", "Footwear store", 1, _RETAIL),
    "shop=books": BizType("small_business", "Bookstore", 1, _RETAIL),
    "shop=sports": BizType("small_business", "Sports store", 1, _RETAIL),
    "shop=bicycle": BizType("small_business", "Bicycle store", 1, _RETAIL),
    "shop=pet": BizType("small_business", "Pet store", 1, _RETAIL),
    "shop=florist": BizType("small_business", "Florist", 1, _RETAIL),
    "shop=stationery": BizType("small_business", "Stationery", 1, _RETAIL),
    "shop=medical_supply": BizType("small_business", "Medical supplies", 2, _RETAIL),
    # larger firms (ERP/SAP/CRM potential)
    "industrial=*": BizType("enterprise", "Factory / industrial unit", 3, _ENT),
    "man_made=works": BizType("enterprise", "Factory / works", 3, _ENT),
    "office=logistics": BizType("enterprise", "Logistics company", 3, _ENT),
    "shop=wholesale": BizType("enterprise", "Wholesaler / distributor", 3, _ENT),
}

_ENTERPRISE_NAME = re.compile(
    r"\b(pvt\.?|private|ltd\.?|limited|llp|industries|mills|textiles|manufactur\w*|exports?|enterprises|corporation|group)\b", re.I
)
_SKIP_NAME = re.compile(r"\b(government|govt|municipal|corporation of|panchayat|police|post office|atm|temple|church|mosque)\b", re.I)

# Places that are run by, or tied to, a bigger brand or partner network. They already get their
# website, bookings and marketing from that network, so they don't need us.
_CHAIN_NAMES = re.compile(
    r"\b(oyo|collection o|townhouse|capital o|flagship|silverkey|treebo|fab ?hotels?|zostel|reddoorz|airbnb|"
    r"ginger hotel|lemon tree|vivanta|taj (hotel|coromandel|club house|fisherman)|itc (grand|hotel)|marriott|courtyard by|hyatt|hilton|radisson|novotel|ibis|holiday inn|sterling holidays|"
    r"grt (grand|hotel|jewell\w*)|fortune (park|select|inn)|keys (hotel|select|prima)|"
    r"domino'?s|pizza hut|kfc|mcdonald'?s|subway|burger king|starbucks|cafe coffee day|\bccd\b|baskin|naturals ice|"
    r"adyar ananda bhavan|a2b|saravana bhavan|hotel saravana bhavan|sangeetha veg|haldiram|barbeque nation|wow! momo|"
    r"apollo|fortis|manipal|kauvery|miot|aravind eye|vasan eye|dr\.? agarwal|max hospital|narayana health|kims hospital|sankara nethralaya|"
    r"medplus|netmeds|wellness forever|thyrocare|lal ?path|metropolis|"
    r"sbi|state bank|hdfc|icici|axis bank|canara bank|indian bank|indian overseas|union bank|bank of baroda|kotak|"
    r"lic|muthoot|manappuram|bajaj (finance|finserv|allianz)|shriram (finance|chits|transport|city)|"
    r"reliance|jio|airtel|vodafone|bsnl|tanishq|kalyan jewell\w*|malabar gold|joyalukkas|jos alukkas|lalitha jewell\w*|"
    r"bata|lenskart|titan|poorvika|sangeetha mobiles|croma|vijay sales|big bazaar|more (super|retail)|d-?mart|spencer'?s|"
    r"nilgiris|pothys|the chennai silks|saravana stores|naturals|green trends|lakme|toni ?& ?guy|"
    r"cult\.?fit|gold'?s gym|anytime fitness|snap fitness|"
    r"amazon|flipkart|swiggy|zomato|dunzo|ola cabs|uber|rapido|indian oil|bharat petroleum|hindustan petroleum|hp petrol)\b",
    re.I,
)
# Colleges and universities run their own IT departments and vendor panels.
_COLLEGE_NAMES = re.compile(r"\b(college|university|institute of technology|engineering|polytechnic|iit|nit|iiit|anna university|deemed)\b", re.I)
# IT / software companies are our competitors, not our clients.
_IT_NAMES = re.compile(
    r"\b(infotech|infosys|software|softwares|technologies|technology|techno|tech|it services|it solutions|web ?(design|solutions|services)|"
    r"digital|soft|cyber|cloud|data|systems|solutions pvt|computers? (pvt|private)|apps?|labs|innovations?|analytics|ai)\b",
    re.I,
)


# Independent dealers / resellers (cars, bikes, tyres, electronics, appliances, tractors...). Owner: "dealers are okay".
DEALER_SHOPS = {"car", "motorcycle", "car_repair", "motorcycle_repair", "tyres", "car_parts", "electronics", "mobile_phone",
                "appliance", "hardware", "doityourself", "agrarian", "furniture", "bicycle", "computer", "trade", "wholesale"}


def exclusion_reason(tags: dict[str, str], name: str, type_key: str | None) -> str | None:
    """Why this place does NOT need us (or None). Shown in run logs and on old records."""
    dealer = tags.get("shop") in DEALER_SHOPS
    # A dealer's brand tag is the brand it sells, not its owner: dealers stay if they meet our criteria.
    if not dealer and (tags.get("brand") or tags.get("brand:wikidata") or tags.get("operator:wikidata") or tags.get("franchise")):
        return "part of a chain or brand"
    if _CHAIN_NAMES.search(name) or _CHAIN_NAMES.search(tags.get("operator", "")):
        return "part of a chain or partner network"
    if type_key in ("amenity=college", "office=educational_institution") and _COLLEGE_NAMES.search(name):
        return "college or university"
    if tags.get("amenity") in ("university",) or (_COLLEGE_NAMES.search(name) and (tags.get("amenity") in ("college", "school") or type_key == "amenity=school")):
        return "college or university"
    if type_key in ("office=it", "office=telecommunication") or (type_key or "").startswith("office=") and _IT_NAMES.search(name):
        return "IT / software company"
    if tags.get("office") == "government" or tags.get("government") or tags.get("operator:type") in ("government", "public"):
        return "government"
    if re.search(r"\b(ttdc|tamil nadu tourism|tnstc|aavin|tangedco|corporation|municipal)\b", name, re.I):
        return "government"
    return None


CONTACT_KEYS = ("phone", "contact:phone", "mobile", "contact:mobile", "contact:whatsapp", "email", "contact:email")
WEBSITE_KEYS = ("website", "contact:website", "url")
SOCIAL_KEYS = ("contact:facebook", "facebook", "contact:instagram", "instagram", "contact:youtube", "contact:linkedin")
_SOCIAL_DOMAINS = ("facebook.com", "instagram.com", "fb.com", "youtube.com", "linkedin.com", "wa.me", "linktr.ee", "justdial.com", "indiamart.com", "sulekha.com")


def _type_key(tags: dict[str, str]) -> str | None:
    if "industrial" in tags:
        return "industrial=*"
    for k in ("healthcare", "office", "amenity", "craft", "tourism", "leisure", "shop", "man_made"):
        v = tags.get(k)
        if v and f"{k}={v}" in TYPES:
            return f"{k}={v}"
    # generic shop/craft still counts as a small business
    if tags.get("shop"):
        return "shop=*"
    if tags.get("craft"):
        return "craft=*"
    return None


def classify_tags(tags: dict[str, str], name: str) -> tuple[str, BizType] | None:
    key = _type_key(tags)
    if key is None:
        return None
    if key == "shop=*":
        bt = BizType("small_business", f"Shop ({tags['shop'].replace('_', ' ')})", 1, _RETAIL)
    elif key == "craft=*":
        bt = BizType("professional", f"Craft ({tags['craft'].replace('_', ' ')})", 1, ("website", "marketing"))
    else:
        bt = TYPES[key]
    # A company office whose name says Ltd / Industries / Mills is a larger firm (ERP/SAP potential).
    if bt.segment != "enterprise" and key in ("office=company", "shop=wholesale") and _ENTERPRISE_NAME.search(name):
        bt = BizType("enterprise", bt.label, 3, _ENT)
    return key, bt


def _first(tags: dict[str, str], keys) -> str | None:
    for k in keys:
        v = (tags.get(k) or "").strip()
        if v:
            return v.split(";")[0].strip()
    return None


def _is_social(url: str) -> bool:
    return any(d in url.lower() for d in _SOCIAL_DOMAINS)


def _address(tags: dict[str, str]) -> str | None:
    if tags.get("addr:full"):
        return tags["addr:full"]
    parts = [tags.get(k) for k in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city", "addr:postcode")]
    s = ", ".join(p for p in parts if p)
    return s or None


@dataclass
class ParsedProspect:
    ref: str
    url: str
    name: str
    type_key: str
    biz: BizType
    tags: dict[str, str]
    lat: float | None
    lon: float | None
    phone: str | None
    email: str | None
    website: str | None
    social: list[str] = field(default_factory=list)


def parse_element(el: dict[str, Any]) -> ParsedProspect | None:
    tags: dict[str, str] = el.get("tags") or {}
    name = (tags.get("name:en") or tags.get("name") or "").strip()
    if not name or _SKIP_NAME.search(name):
        return None
    if tags.get("disused") or tags.get("abandoned") or "disused:shop" in tags:
        return None
    c = classify_tags(tags, name)
    if c is None:
        return None
    key, bt = c
    if exclusion_reason(tags, name, key):
        return None
    el_type, el_id = el.get("type"), el.get("id")
    if el_type not in ("node", "way", "relation") or el_id is None:
        return None
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    website = _first(tags, WEBSITE_KEYS)
    social = [tags[k].strip() for k in SOCIAL_KEYS if tags.get(k)]
    if website and _is_social(website):
        social.append(website)  # a Facebook page is not a website
        website = None
    return ParsedProspect(
        ref=f"osm:{el_type}/{el_id}", url=f"https://www.openstreetmap.org/{el_type}/{el_id}", name=name[:300],
        type_key=key, biz=bt, tags=tags, lat=lat, lon=lon,
        phone=_first(tags, ("phone", "contact:phone", "mobile", "contact:mobile", "contact:whatsapp")),
        email=_first(tags, ("email", "contact:email")), website=website, social=social,
    )


# --------------------------------------------------------------------------------------------
# Phone numbers: format check only. "Verified" means a human confirmed it (call / WhatsApp).
# --------------------------------------------------------------------------------------------
def check_phone(raw: str | None, country: str | None) -> tuple[str | None, str | None]:
    """Return (normalized, type). Tries each listed number and keeps the first that looks valid.

    Indian numbers: mobile = 10 digits starting 6-9; landline = STD code + number (10 digits
    after the trunk 0); toll-free = 1800/1860. Never invents digits.
    """
    if not raw:
        return None, None
    candidates = [c for c in re.split(r"[;,/]|\bor\b", raw) if c.strip()]
    india = country in (None, "India")
    for cand in candidates:
        d = re.sub(r"\D", "", cand)
        if not d:
            continue
        if india:
            if d.startswith("1800") or d.startswith("1860"):
                return d, "toll_free"
            national = d
            if national.startswith("91") and len(national) == 12:
                national = national[2:]
            elif national.startswith("0091") and len(national) == 14:
                national = national[4:]
            elif national.startswith("0") and len(national) == 11:
                national = national[1:]
            if len(national) == 10:
                return f"+91{national}", ("mobile" if national[0] in "6789" else "landline")
            if country == "India":
                continue
        if 8 <= len(d) <= 15 and not india:
            return f"+{d}" if cand.strip().startswith("+") else d, "international"
    return None, "invalid"


PHONE_LABEL = {"mobile": "mobile", "landline": "landline", "toll_free": "toll-free", "international": "international", "invalid": "looks wrong"}


# --------------------------------------------------------------------------------------------
# Gaps, services and score (deterministic, explained)
# --------------------------------------------------------------------------------------------
def _gap(key: str, label: str, detail: str) -> dict[str, str]:
    return {"key": key, "label": label, "detail": detail}


def evaluate(p: Prospect) -> None:
    """Recompute gaps, recommended services, score and reasons for a prospect."""
    gaps: list[dict[str, str]] = []
    reasons: list[str] = []
    services: list[str] = []
    score = 0.0
    bt = TYPES.get(p.business_type)
    if p.segment == "enterprise":
        tier, base_services = 3, list(_ENT)
    else:
        tier = bt.tier if bt else 1
        base_services = list(bt.services) if bt else ["website", "marketing"]

    if not p.has_website:
        gaps.append(_gap("no_website", "No website", "No website listed in the public map record."))
        score += 35
        reasons.append("+35 no website listed")
        if p.social_links:
            score += 10
            reasons.append("+10 has social media pages but no own website")
        act = (p.audit or {}).get("social_activity")
        if act == "very_active":
            score += 15
            reasons.append("+15 you checked: very active on social media")
        elif act == "some":
            score += 8
            reasons.append("+8 you checked: some social media activity")
        elif act == "inactive":
            score -= 10
            reasons.append("-10 you checked: social media inactive")
            gaps.append(_gap("social_only", "Only social media", "Relies on social pages: " + ", ".join(p.social_links[:3])))
        services += ["website", "marketing", "strategy"]
    audit_gaps = (p.audit or {}).get("gaps") or []
    if p.has_website and audit_gaps:
        pts = min(30, 6 * len(audit_gaps))
        score += pts
        reasons.append(f"+{pts} website audit found {len(audit_gaps)} gap(s)")
        gaps += audit_gaps
        for g in audit_gaps:
            services += {"unreachable": ["website"], "no_https": ["website"], "not_mobile": ["website"], "outdated": ["website"],
                         "basic_builder": ["website"], "no_title": ["marketing"], "no_description": ["marketing"],
                         "no_analytics": ["marketing"], "no_social_tags": ["marketing"], "no_structured_data": ["marketing"],
                         "no_chat": ["ai", "crm"], "no_form": ["crm"]}.get(g.get("key", ""), [])
    elif p.has_website and not p.audit:
        reasons.append("+0 has a website (run a website check to find gaps)")

    tier_pts = {3: 20, 2: 12, 1: 6}[tier]
    score += tier_pts
    reasons.append(f"+{tier_pts} business type value ({'high' if tier == 3 else 'medium' if tier == 2 else 'low'})")
    if p.segment == "enterprise":
        reasons.append("larger firm: ERP / SAP / CRM / automation potential")
    if p.phone:
        p.phone_normalized, p.phone_type = check_phone(p.phone, p.country)
    else:
        p.phone_normalized, p.phone_type = None, None
    if p.phone_verified:
        score += 20
        reasons.append("+20 phone number confirmed by you")
    elif p.phone_type == "mobile":
        score += 15
        reasons.append("+15 mobile number listed (format checked, not yet confirmed)")
    elif p.phone_type in ("landline", "international"):
        score += 10
        reasons.append(f"+10 {PHONE_LABEL[p.phone_type]} number listed (format checked, not yet confirmed)")
    elif p.phone_type == "toll_free":
        score += 5
        reasons.append("+5 toll-free number only")
    elif p.phone_type == "invalid":
        gaps.append(_gap("bad_phone", "Phone number looks wrong", f"Listed as '{p.phone}' — check before calling."))
        reasons.append("+0 listed phone number looks wrong")
    if p.email:
        score += 5
        reasons.append("+5 email published")
    if not p.phone and not p.email and not p.social_links:
        gaps.append(_gap("no_contact", "No public contact", "Only a map location — visit or find a contact route."))
        reasons.append("+0 no public contact route")
    if p.opening_hours:
        score += 5
        reasons.append("+5 opening hours listed (active business)")
    if p.address:
        score += 5
        reasons.append("+5 full address listed")

    # How sure are we that they need us?
    usable_phone = p.phone_verified or p.phone_type in ("mobile", "landline", "international")
    active = [w for w, ok in (("opening hours listed", p.opening_hours), ("full address", p.address),
                              ("active on social media", p.social_links), ("email listed", p.email)) if ok]
    need: list[str] = []
    if not p.has_website:
        need.append("no website")
    if usable_phone:
        need.append("phone number you can call" + (" (confirmed)" if p.phone_verified else ""))
    need += [a for a in active if not (a == "active on social media" and not p.has_website)]  # said more fully below
    if p.segment == "enterprise":
        need.append("bigger firm (ERP / CRM potential)")
    elif tier >= 2:
        need.append("business type that wins customers online")
    social_activity = (p.audit or {}).get("social_activity")  # set by the owner after looking at their pages
    if p.social_links and not p.has_website:
        need.insert(0, "active on social media but no website: has customers online, likely no team or know-how to grow it")
    if social_activity in ("very_active", "some"):
        need.insert(0, f"owner checked: {'very active' if social_activity == 'very_active' else 'some activity'} on social media")
    if not p.has_website and usable_phone and social_activity != "inactive" and (p.social_links or social_activity in ("very_active", "some")):
        level = "definite"  # they already market themselves online — we can do it properly for them
    elif not p.has_website and usable_phone and active and (tier >= 2 or p.segment == "enterprise"):
        level = "definite"
    elif not p.has_website and usable_phone:
        level = "likely"
    else:
        level = "maybe"
    p.need_level, p.need_reasons = level, need

    # Bigger firms lead with ERP/SAP/CRM; small ones lead with the gap (website, SEO, ...).
    services = base_services + services if p.segment == "enterprise" else services + base_services
    seen: list[str] = []
    for s in services:
        if s in SERVICE_KEYS and s not in seen:
            seen.append(s)
    p.gaps = gaps
    p.recommended_services = seen[:5]
    p.score = round(max(0.0, min(100.0, score)), 1)
    p.score_reasons = reasons


# --------------------------------------------------------------------------------------------
# OpenStreetMap search
# --------------------------------------------------------------------------------------------
_TYPE_FILTERS = [
    '["shop"]',
    '["office"~"^(lawyer|accountant|tax_advisor|architect|estate_agent|insurance|financial_advisor|financial|consulting|notary|surveyor|travel_agent|educational_institution|company|coworking|logistics)$"]',
    '["craft"]',
    '["healthcare"~"^(doctor|dentist|clinic|hospital|physiotherapist|optometrist|alternative|laboratory)$"]',
    '["amenity"~"^(restaurant|cafe|fast_food|clinic|doctors|dentist|hospital|veterinary|driving_school|language_school|kindergarten|school|pharmacy)$"]',
    '["tourism"~"^(hotel|guest_house|hostel|motel)$"]',
    '["leisure"~"^(fitness_centre|sports_centre|dance)$"]',
    '["industrial"]',
    '["man_made"="works"]',
]
_HAS_CONTACT = '[~"^(phone|contact:phone|mobile|contact:mobile|contact:whatsapp|email|contact:email|website|contact:website|url|contact:facebook|facebook|contact:instagram|instagram)$"~"."]'


def build_query(lat: float, lon: float, radius_m: int, *, require_contact: bool = True, no_website: bool = False) -> str:
    around = f"(around:{int(radius_m)},{lat:.5f},{lon:.5f})"
    contact = _HAS_CONTACT if require_contact else ""
    nosite = '[!"website"][!"contact:website"][!"url"]' if no_website else ""
    parts = "".join(f'nwr{around}["name"]{f}[!"brand"]{nosite}{contact};' for f in _TYPE_FILTERS)
    return f"[out:json][timeout:90];({parts});out center tags 1500;"


def fetch_area(http: SafeHttp, lat: float, lon: float, radius_m: int, endpoints=None, log=None, dead: set[str] | None = None,
               no_website: bool = False) -> list[dict[str, Any]]:
    """Query the first working mirror. Mirrors that fail are added to `dead` and skipped for the rest of the run."""
    q = build_query(lat, lon, radius_m, no_website=no_website)
    last: Exception | None = None
    dead = dead if dead is not None else set()
    for ep in endpoints or OVERPASS_ENDPOINTS:
        if ep in dead:
            continue
        try:
            res = http.post_form(ep, {"data": q}, timeout=60)
            data = res.json()
            return list(data.get("elements") or [])
        except (FetchError, ValueError) as exc:
            last = exc
            dead.add(ep)
            if log:
                log(f"map server {ep.split('/')[2]} not responding ({str(exc)[:120]})")
    raise FetchError(f"No map server responded: {last}" if last else "All map servers are down right now")


def upsert(db: Session, pp: ParsedProspect, area: str, country: str | None) -> tuple[Prospect, bool]:
    p = db.scalar(select(Prospect).where(Prospect.source_ref == pp.ref))
    created = p is None
    if p is None:
        p = Prospect(source_ref=pp.ref, status="new", contact_log=[], audit={})
        db.add(p)
    country_tag = pp.tags.get("addr:country")
    p.name, p.segment, p.business_type, p.type_label = pp.name, pp.biz.segment, pp.type_key, pp.biz.label
    p.area = area
    p.country = country or ({"IN": "India"}.get(country_tag or "") if country_tag else None)
    p.address, p.lat, p.lon = _address(pp.tags), pp.lat, pp.lon
    p.phone, p.email, p.website, p.social_links = pp.phone, pp.email, pp.website, pp.social
    p.opening_hours = pp.tags.get("opening_hours")
    if p.has_website != bool(pp.website) or (pp.website and (p.audit or {}).get("url") not in (None, pp.website)):
        keep = {k: v for k, v in (p.audit or {}).items() if k == "social_activity"}
        p.audit, p.audited_at = keep, None  # website changed: old audit no longer applies (owner's social check kept)
    p.has_website = bool(pp.website)
    p.source = "overture" if pp.ref.startswith("overture:") else "openstreetmap"
    p.source_url, p.raw_tags = pp.url, pp.tags
    evaluate(p)
    return p, created


@dataclass
class SearchRules:
    only_no_website: bool = True  # businesses with a website already have a developer
    require_phone: bool = True  # must list a phone number that passes the format check

    def keep(self, pp: ParsedProspect, country: str | None) -> str | None:
        """Return None to keep, or the reason it was dropped."""
        if self.only_no_website and pp.website:
            return "has a website"
        if self.require_phone:
            _, kind = check_phone(pp.phone, country)
            if kind in (None, "invalid", "toll_free"):
                return "no usable phone number"
        return None


def _apply_rules(parsed: list[ParsedProspect], rules: SearchRules, country_of) -> tuple[list[ParsedProspect], dict[str, int]]:
    kept: list[ParsedProspect] = []
    dropped: dict[str, int] = {}
    for pp in parsed:
        why = rules.keep(pp, country_of(pp))
        if why:
            dropped[why] = dropped.get(why, 0) + 1
        else:
            kept.append(pp)
    return kept, dropped


def _dropped_text(dropped: dict[str, int]) -> str:
    return ("; skipped " + ", ".join(f"{n} {why}" for why, n in dropped.items())) if dropped else ""


def run_prospect_search(db: Session, run: ProspectRun, *, radius_m: int, max_per_area: int, http: SafeHttp | None = None,
                        endpoints: list[str] | None = None, rules: SearchRules | None = None) -> ProspectRun:
    """Search each area and store prospects.

    Progress is saved after every city so the UI can show it. The run stops early when the owner
    presses Stop or when every map server has failed (no point waiting hours on dead servers).
    """
    own = http is None
    http = http or SafeHttp(rate_limit_per_minute=6)
    logs: list[str] = list(run.log or [])
    dead: set[str] = set()
    eps = endpoints or OVERPASS_ENDPOINTS
    total = len(run.areas)
    rules = rules or SearchRules()

    def log(msg: str) -> None:
        logs.append(msg[:500])

    def save() -> None:
        run.log = list(logs)
        db.commit()

    ok_areas = 0
    stopped = False
    try:
        for i, spec in enumerate(run.areas, 1):
            db.refresh(run, ["status"])
            if run.status == "stopping":
                log("Stopped by you.")
                stopped = True
                break
            if len(dead) >= len(eps):
                log("All map servers stopped responding, so the search ended early. Try again later with 2–3 cities.")
                break
            try:
                name, lat, lon, country = resolve_area(spec)
            except ValueError as exc:
                log(str(exc))
                continue
            try:
                elements = fetch_area(http, lat, lon, radius_m, endpoints=eps, log=log, dead=dead, no_website=rules.only_no_website)
            except FetchError as exc:
                log(f"✗ {name} ({i}/{total}): {exc}")
                save()
                continue
            parsed = [pp for pp in (parse_element(e) for e in elements) if pp]
            parsed, dropped = _apply_rules(parsed, rules, lambda _pp: country)
            run.skipped += len(elements) - len(parsed)
            # Keep the best candidates per area: no website first, then reachable, then type value.
            parsed.sort(key=lambda pp: (bool(pp.website), not pp.phone, -pp.biz.tier))
            parsed = parsed[:max_per_area]
            for pp in parsed:
                _, created = upsert(db, pp, name, country)
                if created:
                    run.new += 1
                else:
                    run.updated += 1
            run.found += len(parsed)
            ok_areas += 1
            log(f"✓ {name} ({i}/{total}): {len(parsed)} prospects from {len(elements)} map listings{_dropped_text(dropped)}")
            save()
        if stopped:
            run.status = "stopped" if not ok_areas else "partial"
        else:
            run.status = "success" if ok_areas == total else ("partial" if ok_areas else "failed")
    finally:
        run.log = logs
        run.finished_at = utcnow()
        db.commit()
        if own:
            http.close()
    return run


# --------------------------------------------------------------------------------------------
# Offline map file (Geofabrik .osm.pbf downloaded by the owner in a browser)
# --------------------------------------------------------------------------------------------
REGIONS: dict[str, tuple[float, float, float, float] | None] = {
    # (min_lat, min_lon, max_lat, max_lon). The box also touches small parts of Kerala, Karnataka and
    # Andhra Pradesh. Each prospect's area is the nearest listed city, never a guessed state.
    "Tamil Nadu": (8.0, 76.2, 13.6, 80.4),
    "Whole file": None,
}
TYPE_KEYS = ("shop", "office", "craft", "healthcare", "amenity", "tourism", "leisure", "industrial", "man_made")
_REACH_KEYS = set(CONTACT_KEYS) | set(WEBSITE_KEYS) | set(SOCIAL_KEYS)
NEAREST_CITY_KM = 40.0


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(a))


def _place_name(raw: str | None) -> str | None:
    """Tidy a town name from the listing: 'tonk' -> 'Tonk'. Never invents one."""
    if not raw or not raw.strip():
        return None
    v = re.split(r"[,;]", raw.strip())[0].strip()[:100]
    return v.title() if v.islower() or v.isupper() else v


def nearest_city(lat: float | None, lon: float | None) -> tuple[str, str | None]:
    """Nearest listed city within NEAREST_CITY_KM → (area, country). Otherwise ("Other", None)."""
    if lat is None or lon is None:
        return "Other", None
    best, best_d = None, NEAREST_CITY_KM
    for name, (clat, clon, country, _) in AREAS.items():
        d = _km(lat, lon, clat, clon)
        if d <= best_d:
            best, best_d = (name, country), d
    return best or ("Other", None)


def iter_map_file(path: str, bbox: tuple[float, float, float, float] | None, log=None):
    """Yield Overpass-style element dicts for named, reachable businesses in an .osm.pbf file."""
    import osmium

    import os
    import tempfile

    # Big files (a whole country): keep the node-location index on disk, not in RAM.
    idx_dir = None
    storage = "flex_mem"
    if os.path.getsize(path) > 300_000_000:
        idx_dir = tempfile.mkdtemp(prefix="ioi-osm-", dir=os.path.dirname(path))
        storage = f"sparse_file_array,{os.path.join(idx_dir, 'nodes.idx')}"
    fp = (
        osmium.FileProcessor(path, osmium.osm.NODE | osmium.osm.WAY)
        .with_locations(storage)
        .with_filter(osmium.filter.KeyFilter(*TYPE_KEYS))
        .with_filter(osmium.filter.KeyFilter("name"))
    )
    try:
        yield from _iter_objects(fp, bbox, log)
    finally:
        if idx_dir:
            import shutil

            shutil.rmtree(idx_dir, ignore_errors=True)


def _iter_objects(fp, bbox, log):
    seen = 0
    for obj in fp:
        tags = {t.k: t.v for t in obj.tags}
        if not _REACH_KEYS.intersection(tags):
            continue
        if obj.is_node():
            if not obj.location.valid():
                continue
            lat, lon, typ = obj.location.lat, obj.location.lon, "node"
        else:
            pts = [(n.lat, n.lon) for n in obj.nodes if n.location.valid()]
            if not pts:
                continue
            lat, lon, typ = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), "way"
        if bbox and not (bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]):
            continue
        seen += 1
        if log and seen % 5000 == 0:
            log(f"…{seen} reachable businesses read so far")
        yield {"type": typ, "id": obj.id, "lat": lat, "lon": lon, "tags": tags}


def run_map_file_scan(db: Session, run: ProspectRun, path: str, *, region: str, max_keep: int,
                      cities: list[str] | None = None, radius_km: float = 15.0, rules: SearchRules | None = None) -> ProspectRun:
    """Scan a local map file. No network. Keeps the best `max_keep` candidates."""
    logs: list[str] = list(run.log or [])

    def log(msg: str) -> None:
        logs.append(msg[:500])
        run.log = list(logs)
        db.commit()

    centres = [resolve_area(c) for c in (cities or [])]
    bbox = REGIONS.get(region)
    rules = rules or SearchRules()
    try:
        log(f"Reading {path.rsplit('/', 1)[-1]} ({region if not centres else ', '.join(c[0] for c in centres)}). This usually takes 2–10 minutes…")
        parsed: list[ParsedProspect] = []
        total = 0
        for el in iter_map_file(path, bbox, log=log):
            if centres and not any(_km(el["lat"], el["lon"], c[1], c[2]) <= radius_km for c in centres):
                continue
            total += 1
            pp = parse_element(el)
            if pp:
                parsed.append(pp)
            if total % 1000 == 0:
                db.refresh(run, ["status"])  # lets Stop work mid-scan
                if run.status == "stopping":
                    break
        if run.status == "stopping":
            logs.append("Stopped by you.")
            run.status = "stopped"
            return run
        parsed, dropped = _apply_rules(parsed, rules, lambda pp: nearest_city(pp.lat, pp.lon)[1])
        run.skipped = total - len(parsed)
        parsed.sort(key=lambda pp: (bool(pp.website), not pp.phone, -pp.biz.tier))
        keep = parsed[:max_keep]
        for i, pp in enumerate(keep, 1):
            area, country = nearest_city(pp.lat, pp.lon)
            if area == "Other":  # far from listed cities: use the listing's own city/district tag if it has one
                area = _place_name(pp.tags.get("addr:city") or pp.tags.get("addr:district")) or "Other"
            _, created = upsert(db, pp, area, country)
            run.new += int(created)
            run.updated += int(not created)
            if i % 500 == 0:
                db.commit()
        run.found = len(keep)
        logs.append(f"✓ Done: {len(parsed)} possible prospects in the map file, kept the best {len(keep)} ({run.new} new){_dropped_text(dropped)}.")
        run.status = "success"
    except Exception as exc:  # noqa: BLE001 - corrupt/unsupported file must end the run cleanly
        db.rollback()
        logs.append(f"✗ Could not read the map file: {str(exc)[:300]}")
        run.status = "failed"
    finally:
        run.log = logs
        run.finished_at = utcnow()
        db.commit()
    return run


# --------------------------------------------------------------------------------------------
# Website audit (homepage only, robots.txt respected)
# --------------------------------------------------------------------------------------------
_CHAT = re.compile(r"tawk\.to|crisp\.chat|intercom|wa\.me/|api\.whatsapp\.com|salesiq|livechat|tidio|freshchat|chatbot|botpress|wati\.io", re.I)
_ANALYTICS = re.compile(r"googletagmanager|google-analytics|gtag\(|fbq\(|clarity\.ms|plausible|matomo", re.I)
_BUILDER = re.compile(r"wix\.com|blogspot\.|sites\.google\.com|weebly|godaddysites|webnode|business\.site", re.I)
_YEAR = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d\d)", re.I)


def audit_html(final_url: str, html: str, now_year: int) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    low = html.lower()
    if not final_url.lower().startswith("https://"):
        gaps.append(_gap("no_https", "Not secure (no HTTPS)", f"Site served over http: {final_url}"))
    if 'name="viewport"' not in low and "name='viewport'" not in low:
        gaps.append(_gap("not_mobile", "Not mobile-friendly", "No viewport meta tag; likely broken on phones."))
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = unescape(m.group(1)).strip() if m else ""
    if len(title) < 5:
        gaps.append(_gap("no_title", "Missing page title", "Homepage has no usable <title> — hurts Google ranking."))
    if not re.search(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'][^\"']{20,}", html, re.I):
        gaps.append(_gap("no_description", "No meta description", "Search results show no summary for this site."))
    if not _ANALYTICS.search(html):
        gaps.append(_gap("no_analytics", "No analytics / tracking", "No Google Analytics, Tag Manager or Meta pixel found."))
    if "og:title" not in low and "og:image" not in low:
        gaps.append(_gap("no_social_tags", "No social sharing tags", "Links shared on WhatsApp/Facebook show no preview."))
    if "application/ld+json" not in low:
        gaps.append(_gap("no_structured_data", "No structured data", "No schema.org data for Google local results."))
    if not _CHAT.search(html):
        gaps.append(_gap("no_chat", "No chat / WhatsApp button", "Visitors cannot message instantly — AI chatbot or WhatsApp opportunity."))
    if "<form" not in low:
        gaps.append(_gap("no_form", "No enquiry form", "No contact/enquiry form on the homepage — leads are not captured."))
    if _BUILDER.search(final_url) or _BUILDER.search(html[:20000]):
        gaps.append(_gap("basic_builder", "Basic site builder", "Built on a free/basic builder — limited SEO and branding."))
    years = [int(y) for y in _YEAR.findall(html)]
    if years and max(years) <= now_year - 3:
        gaps.append(_gap("outdated", "Outdated website", f"Copyright year {max(years)} — site looks unmaintained."))
    return gaps


def audit_website(db: Session, p: Prospect, http: SafeHttp | None = None) -> Prospect:
    if not p.website:
        raise ValueError("Prospect has no website to check")
    url = p.website.strip() if re.match(r"^https?://", p.website.strip(), re.I) else f"http://{p.website.strip()}"
    if re.match(r"^https?://[^/]+$", url, re.I):
        url += "/"
    own = http is None
    http = http or SafeHttp(rate_limit_per_minute=10)
    now = utcnow()
    try:
        res = http.get(url)
        if "html" not in (res.content_type or "html").lower():
            gaps = [_gap("unreachable", "Website not working", f"Homepage returned {res.content_type}, not a web page.")]
        else:
            gaps = audit_html(res.url, res.text, now.year)
        p.audit = {"url": p.website, "final_url": res.url, "status": res.status_code, "gaps": gaps, "checked_at": now.isoformat()}
    except FetchError as exc:
        p.audit = {"url": p.website, "error": str(exc)[:300], "checked_at": now.isoformat(),
                   "gaps": [_gap("unreachable", "Website not working", f"Could not load the site: {str(exc)[:200]}")]}
    finally:
        if own:
            http.close()
    p.audited_at = now
    evaluate(p)
    db.commit()
    return p


# --------------------------------------------------------------------------------------------
# Pitch draft + contact log (nothing is sent automatically)
# --------------------------------------------------------------------------------------------
PITCH_LINES = {
    "website": "a professional, mobile-friendly website so customers can find you on Google",
    "marketing": "local SEO and a Google Business Profile setup to bring in more enquiries",
    "crm": "a simple CRM to track enquiries, customers and follow-ups",
    "ai": "an AI / WhatsApp assistant that answers customer questions and takes bookings 24x7",
    "erp": "ERP / SAP integration to connect billing, stock and accounts",
    "automation": "automation of repetitive work like invoices, reminders and reports",
    "integration": "connecting your existing software so data is not typed twice",
    "strategy": "a clear plan to grow your business online",
    "backend": "custom software built for how you work",
    "api": "integrations with payment, delivery and other platforms",
    "internal_apps": "an internal app or dashboard for your team",
}


def digits(phone: str | None) -> str | None:
    if not phone:
        return None
    d = re.sub(r"\D", "", phone.split(";")[0])
    return d or None


def pitch(p: Prospect) -> dict[str, Any]:
    gaps = [g["label"].lower() for g in (p.gaps or []) if g.get("key") not in ("no_contact",)]
    services = [PITCH_LINES[s] for s in (p.recommended_services or []) if s in PITCH_LINES][:3]
    noticed = (
        "I noticed your business does not have a website yet" if not p.has_website
        else f"I had a quick look at your website and noticed a few things that may be costing you customers ({', '.join(gaps[:3])})"
        if gaps else "I had a quick look at your online presence"
    )
    body = (
        f"Hello {p.name} team,\n\n"
        f"I'm from Inferago Tech Services, Tamil Nadu. {noticed}.\n\n"
        "We help businesses like yours with:\n"
        + "".join(f"• {s}\n" for s in services)
        + "\nCould I share a few ideas in a short call this week? No obligation.\n\n"
        "Thank you,\nInferago Tech Services"
    )
    norm, ptype = (p.phone_normalized, p.phone_type) if p.phone_type else check_phone(p.phone, p.country)
    d = norm.lstrip("+") if norm else None
    wa = f"https://wa.me/{d}?text={quote(body)}" if d and ptype in ("mobile", "international") else None
    return {
        "subject": f"Helping {p.name} get more customers online",
        "message": body,
        "call_script": f"Hi, is this {p.name}? I'm calling from Inferago Tech Services. {noticed}. "
        "We help local businesses get more enquiries online. Would you be open to a 10-minute chat?",
        "links": {
            "call": f"tel:{norm}" if norm else None,
            "whatsapp": wa,
            "email": f"mailto:{p.email}?subject={quote('Helping ' + p.name + ' get more customers online')}&body={quote(body)}" if p.email else None,
            "map": p.source_url,
        },
        "note": "Draft only. Nothing is sent by IOI — you send it yourself after reviewing.",
    }


STATUSES = ("new", "shortlisted", "contacted", "interested", "not_interested", "won", "rejected")
FOLLOW_UP_DAYS = {"contacted": 3, "interested": 2}


def record_contact(p: Prospect, channel: str, outcome: str, note: str | None, actor: str) -> None:
    now = utcnow()
    p.contact_log = [*(p.contact_log or []), {"at": now.isoformat(), "channel": channel, "outcome": outcome, "note": note, "by": actor}]
    p.last_contacted_at = now
    if channel in ("call", "whatsapp") and outcome in ("interested", "not_interested", "won") and p.phone_normalized:
        p.phone_verified, p.phone_verified_at = True, now  # they answered on this number
    if outcome in STATUSES:
        p.status = outcome
    days = FOLLOW_UP_DAYS.get(p.status)
    p.next_follow_up = now + timedelta(days=days) if days else None
