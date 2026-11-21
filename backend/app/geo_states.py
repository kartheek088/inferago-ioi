"""Indian states: ISO 3166-2 codes, and place names that point to a state when they appear in text.

Only explicit evidence is used: a region code in the listing, a city within 40 km (via
prospects.AREAS), or a place named in a news headline/summary. Unknown stays None.
"""

import re

ISO_STATE = {
    "IN-AN": "Andaman and Nicobar Islands", "IN-AP": "Andhra Pradesh", "IN-AR": "Arunachal Pradesh", "IN-AS": "Assam",
    "IN-BR": "Bihar", "IN-CH": "Chandigarh", "IN-CT": "Chhattisgarh", "IN-CG": "Chhattisgarh", "IN-DH": "Dadra and Nagar Haveli and Daman and Diu",
    "IN-DN": "Dadra and Nagar Haveli and Daman and Diu", "IN-DD": "Dadra and Nagar Haveli and Daman and Diu", "IN-DL": "Delhi", "IN-GA": "Goa",
    "IN-GJ": "Gujarat", "IN-HR": "Haryana", "IN-HP": "Himachal Pradesh", "IN-JK": "Jammu and Kashmir", "IN-JH": "Jharkhand",
    "IN-KA": "Karnataka", "IN-KL": "Kerala", "IN-LA": "Ladakh", "IN-LD": "Lakshadweep", "IN-MP": "Madhya Pradesh", "IN-MH": "Maharashtra",
    "IN-MN": "Manipur", "IN-ML": "Meghalaya", "IN-MZ": "Mizoram", "IN-NL": "Nagaland", "IN-OR": "Odisha", "IN-OD": "Odisha",
    "IN-PY": "Puducherry", "IN-PB": "Punjab", "IN-RJ": "Rajasthan", "IN-SK": "Sikkim", "IN-TN": "Tamil Nadu", "IN-TG": "Telangana",
    "IN-TS": "Telangana", "IN-TR": "Tripura", "IN-UP": "Uttar Pradesh", "IN-UT": "Uttarakhand", "IN-UK": "Uttarakhand", "IN-WB": "West Bengal",
}
STATES = sorted(set(ISO_STATE.values()))

# Words in news text → state. State names first, then distinctive cities/industrial hubs.
_TEXT_PLACES: dict[str, str] = {s.lower(): s for s in STATES}
_TEXT_PLACES.update({
    "t.n.": "Tamil Nadu", "tn govt": "Tamil Nadu", "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu", "madurai": "Tamil Nadu",
    "tiruchirappalli": "Tamil Nadu", "tiruchi": "Tamil Nadu", "trichy": "Tamil Nadu", "salem": "Tamil Nadu", "tirunelveli": "Tamil Nadu",
    "erode": "Tamil Nadu", "vellore": "Tamil Nadu", "hosur": "Tamil Nadu", "tiruppur": "Tamil Nadu", "thanjavur": "Tamil Nadu",
    "kanchipuram": "Tamil Nadu", "sriperumbudur": "Tamil Nadu", "oragadam": "Tamil Nadu", "thoothukudi": "Tamil Nadu", "tuticorin": "Tamil Nadu",
    "krishnagiri": "Tamil Nadu", "ranipet": "Tamil Nadu", "chengalpattu": "Tamil Nadu", "karur": "Tamil Nadu", "dindigul": "Tamil Nadu",
    "nagercoil": "Tamil Nadu", "cuddalore": "Tamil Nadu", "namakkal": "Tamil Nadu", "kumbakonam": "Tamil Nadu", "ooty": "Tamil Nadu",
    "pondicherry": "Puducherry", "bengaluru": "Karnataka", "bangalore": "Karnataka", "mysuru": "Karnataka", "mysore": "Karnataka",
    "mangaluru": "Karnataka", "mangalore": "Karnataka", "hubballi": "Karnataka", "belagavi": "Karnataka", "kochi": "Kerala", "cochin": "Kerala",
    "thiruvananthapuram": "Kerala", "kozhikode": "Kerala", "thrissur": "Kerala", "kollam": "Kerala", "hyderabad": "Telangana",
    "warangal": "Telangana", "visakhapatnam": "Andhra Pradesh", "vizag": "Andhra Pradesh", "vijayawada": "Andhra Pradesh",
    "tirupati": "Andhra Pradesh", "guntur": "Andhra Pradesh", "nellore": "Andhra Pradesh", "sri city": "Andhra Pradesh", "mumbai": "Maharashtra",
    "pune": "Maharashtra", "nagpur": "Maharashtra", "nashik": "Maharashtra", "aurangabad": "Maharashtra", "thane": "Maharashtra",
    "navi mumbai": "Maharashtra", "ahmedabad": "Gujarat", "surat": "Gujarat", "vadodara": "Gujarat", "rajkot": "Gujarat", "gift city": "Gujarat",
    "dholera": "Gujarat", "sanand": "Gujarat", "new delhi": "Delhi", "noida": "Uttar Pradesh", "greater noida": "Uttar Pradesh",
    "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh", "gurugram": "Haryana", "gurgaon": "Haryana", "faridabad": "Haryana",
    "jaipur": "Rajasthan", "jodhpur": "Rajasthan", "udaipur": "Rajasthan", "indore": "Madhya Pradesh", "bhopal": "Madhya Pradesh",
    "kolkata": "West Bengal", "singur": "West Bengal", "bhubaneswar": "Odisha", "patna": "Bihar", "ranchi": "Jharkhand",
    "jamshedpur": "Jharkhand", "raipur": "Chhattisgarh", "dehradun": "Uttarakhand", "chandigarh": "Chandigarh", "ludhiana": "Punjab",
    "guwahati": "Assam", "panaji": "Goa", "srinagar": "Jammu and Kashmir",
})
_TEXT_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(k) for k in _TEXT_PLACES), key=len, reverse=True)) + r")\b", re.I)


def state_from_code(code: str | None) -> str | None:
    if not code:
        return None
    code = code.strip().upper()
    if code in ISO_STATE:
        return ISO_STATE[code]
    if len(code) == 2 and f"IN-{code}" in ISO_STATE:
        return ISO_STATE[f"IN-{code}"]
    return next((s for s in STATES if s.lower() == code.lower()), None)


def state_from_text(text: str) -> tuple[str | None, str | None]:
    """First Indian place named in the text → (place as written, state)."""
    m = _TEXT_RE.search(text or "")
    if not m:
        return None, None
    return m.group(0), _TEXT_PLACES[m.group(0).lower()]


def state_from_area(area: str | None) -> str | None:
    from app.prospects import AREAS

    if area and area in AREAS and AREAS[area][2] == "India":
        st = AREAS[area][3]
        return "Delhi" if st == "Delhi" else st
    return None
