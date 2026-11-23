"""What a social seller sells, how complicated their orders are, and what their setup looks like.

Every rule here is a keyword rule over text the seller published (profile bio, catalogue page, their
own website, a public market listing). Each match keeps the words that triggered it, so a person can
check it. Nothing here concludes that a problem exists: order complexity is an *indicator* that a
workflow tool might be relevant, which a human still has to confirm with the seller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ------------------------------------------------------------------------------------------------
# Product categories (§6)
# ------------------------------------------------------------------------------------------------
FASHION = "fashion_boutique"
GIFTS = "custom_gifts"
BAKERY = "home_bakery"
MEALS = "meal_subscription"
OTHER = "other_social"
CATEGORIES = (FASHION, GIFTS, BAKERY, MEALS, OTHER)

CATEGORY_LABEL = {
    FASHION: "Instagram fashion boutique",
    GIFTS: "Personalised gifts & custom products",
    BAKERY: "Home bakery / food pre-orders",
    MEALS: "Meal subscription / tiffin service",
    OTHER: "Other social seller",
}
CATEGORY_BLURB = {
    FASHION: "Clothing, ethnic wear, custom apparel and small fashion labels selling through social posts.",
    GIFTS: "Custom gifts, printed and personalised products made to a customer's specification.",
    BAKERY: "Custom cakes, desserts and pre-order food made to order for a date.",
    MEALS: "Daily meals, tiffin and subscription food with repeat deliveries.",
    OTHER: "Jewellery, accessories, handmade, beauty and home products.",
}

# Ordered: the first category with a match wins, so a "cake" seller is a bakery even if it says "gift".
_CATEGORY_RX: list[tuple[str, str, re.Pattern[str]]] = [
    (BAKERY, "bakery / pre-order food", re.compile(
        r"\b(home\s?bak(?:er|ery|ing)|bakes?\b|baker\b|custom(?:ised|ized)?\s+cakes?|cakes?\b|cupcakes?|brownies?|"
        r"cookies?|desserts?|patisserie|pastr(?:y|ies)|macarons?|chocolates?\s+(?:hamper|box)|tea\s?cakes?|"
        r"pre.?order\s+(?:food|cakes?|desserts?)|hampers?\s+bak)", re.I)),
    (MEALS, "meal subscription / tiffin", re.compile(
        r"\b(tiffin|mess\s+service|meal\s+(?:subscription|plan|box|service)|lunch\s+(?:box|delivery|service)|"
        r"daily\s+(?:meals?|lunch|dinner)|subscription\s+(?:meals?|food)|home\s?food\s+delivery|"
        r"monthly\s+(?:meal|tiffin)|curated\s+meals?|diet\s+(?:food|meals?))", re.I)),
    (FASHION, "fashion / apparel", re.compile(
        r"\b(boutique|clothing|apparel|ethnic\s?wear|saree?s?|sarees|kurtis?|kurtas?|lehenga|salwar|blouse|"
        r"fashion\s+label|custom\s+(?:stitch|tailor)|tailoring|dress(?:es|ing)?\b|western\s?wear|"
        r"kids\s?wear|men'?s\s?wear|women'?s\s?wear|readymade|outfits?)", re.I)),
    (GIFTS, "personalised gifts / custom products", re.compile(
        r"\b(personal(?:ised|ized)|customi[sz]ed\s+(?:gifts?|products?|mugs?|frames?)|custom\s+gifts?|gift\s+(?:hampers?|box|shop|store)|"
        r"hampers?\b|printed\s+(?:mugs?|t-?shirts?|frames?)|engrav(?:ed|ing)|resin\s+art|photo\s+frames?|"
        r"name\s?plates?|return\s+gifts?|wedding\s+favou?rs?)", re.I)),
    (OTHER, "jewellery / accessories / handmade / beauty", re.compile(
        r"\b(jewell?ery|jewel|earrings?|necklaces?|bangles?|anklets?|accessor(?:y|ies)|handmade|handcrafted|"
        r"crochet|macrame|candles?|soaps?|skin\s?care|cosmetics?|beauty\s+products?|home\s?decor|planters?|"
        r"terrarium|stationery|scrunchies?)", re.I)),
]


@dataclass
class CategoryMatch:
    category: str | None
    reasons: list[str] = field(default_factory=list)
    excerpt: str | None = None

    @property
    def label(self) -> str | None:
        return CATEGORY_LABEL.get(self.category or "")


def _excerpt(text: str, m: re.Match, width: int = 90) -> str:
    a = max(0, m.start() - width // 2)
    return re.sub(r"\s+", " ", text[a: m.end() + width]).strip()[:300]


def classify_category(*texts: str | None) -> CategoryMatch:
    """Which social-commerce category the seller's own words put them in."""
    blob = "\n".join(t for t in texts if t)
    if not blob.strip():
        return CategoryMatch(None, ["No description to classify yet"])
    for cat, label, rx in _CATEGORY_RX:
        m = rx.search(blob)
        if m:
            return CategoryMatch(cat, [f"Describes itself with '{m.group(0).strip()}' ({label})"], _excerpt(blob, m))
    return CategoryMatch(None, ["Nothing in their description matches a target social-commerce category"])


# ------------------------------------------------------------------------------------------------
# Operational complexity (§10) — indicators, never proof of a problem
# ------------------------------------------------------------------------------------------------
# key -> (plain label, pattern, which categories it matters most for)
COMPLEXITY: dict[str, tuple[str, re.Pattern[str]]] = {
    "variants": ("Product sizes / colours / variants", re.compile(
        r"\b(sizes?\s+(?:available|from|s-?m-?l|xs|s|m|l|xl)|all\s+sizes|size\s?chart|colou?rs?\s+available|"
        r"available\s+in\s+\d+\s+colou?rs?|shades?\s+available|variants?)\b", re.I)),
    "custom_orders": ("Made-to-order / customisation", re.compile(
        r"\b(custom(?:is|iz)(?:ed|ation)?\s+orders?|made\s+to\s+order|customi[sz]e\s+your|your\s+(?:design|name|photo)|"
        r"personali[sz]ation|as\s+per\s+your\s+requirement|bespoke|tailor\s?made|"
        # "Custom cakes", "customised hampers": naming a custom product is itself customisation work.
        r"custom(?:is|iz)?(?:ed)?\s+(?:cakes?|cookies?|cupcakes?|hampers?|gifts?|frames?|mugs?|outfits?|"
        r"dress(?:es)?|blouses?|sarees?|jewell?ery|products?|designs?|flavou?rs?))\b", re.I)),
    "advance_payment": ("Advance / part payment before work starts", re.compile(
        r"\b(advance\s+(?:payment|amount|of)?|50%\s+advance|part\s+payment|token\s+amount|"
        r"booking\s+amount|pay\s+to\s+confirm|confirm(?:ed)?\s+(?:on|after)\s+payment)\b", re.I)),
    "deadlines": ("Delivery dates / lead times", re.compile(
        r"\b(\d+\s*(?:-\s*\d+)?\s*(?:days?|weeks?)\s+(?:for\s+)?(?:delivery|dispatch|to\s+make|prior)|"
        r"order\s+(?:\d+\s*days?\s+)?in\s+advance|delivery\s+(?:date|time|slot)|same\s?day\s+delivery|"
        r"lead\s?time|pre.?book|book\s+(?:\d+\s*days?\s+)?(?:in\s+)?advance)\b", re.I)),
    "recurring": ("Repeat / subscription orders", re.compile(
        r"\b(monthly\s+(?:plan|subscription|pack)|weekly\s+(?:plan|menu|pack)|subscription|daily\s+delivery|"
        r"pause\s+(?:and|or|/)?\s*resume|renew(?:al)?|repeat\s+orders?|regular\s+customers?)\b", re.I)),
    "delivery": ("Delivery / dispatch and courier coordination", re.compile(
        r"\b(pan.?india\s+(?:delivery|shipping)|ship(?:ping|ped)?\s+(?:all\s+over|across|pan)|courier|"
        r"delivery\s+(?:charges?|available|across)|free\s+(?:shipping|delivery)|dispatch(?:ed)?|"
        r"pickup\s+(?:available|from)|door\s+delivery|"
        # Verb forms: "we deliver across Chennai", "we deliver to all areas".
        r"deliver(?:s|ing)?\s+(?:across|all\s+over|to|within|anywhere\s+in))\b", re.I)),
    "order_volume_text": ("Says it handles many orders", re.compile(
        r"\b(bulk\s+orders?|wholesale\s+(?:enquir|order)|corporate\s+orders?|\d{2,}\+?\s+orders?|"
        r"orders?\s+(?:pouring|flowing)|limited\s+slots?|slots?\s+(?:full|open))\b", re.I)),
    "returns": ("Returns / exchanges policy", re.compile(
        r"\b(returns?\s+(?:policy|accepted|within)|exchange\s+(?:policy|only|within)|no\s+returns?|"
        r"refund\s+policy|replacement\s+(?:only|within))\b", re.I)),
    "multi_channel_orders": ("Orders arrive through more than one channel", re.compile(
        r"\b(dm\s+(?:to\s+order|for\s+(?:order|price|details))|whatsapp\s+(?:to\s+order|only|for\s+orders?)|"
        r"order\s+(?:on|via|through)\s+(?:whatsapp|dm|call)|call\s+(?:or|/)\s*whatsapp)\b", re.I)),
}

# Complexity that matters most per category, used to explain relevance (not to change the score).
CATEGORY_COMPLEXITY = {
    FASHION: ("variants", "deadlines", "delivery", "returns"),
    GIFTS: ("custom_orders", "advance_payment", "deadlines", "delivery"),
    BAKERY: ("custom_orders", "deadlines", "advance_payment", "order_volume_text"),
    MEALS: ("recurring", "delivery", "advance_payment", "order_volume_text"),
    OTHER: ("variants", "custom_orders", "delivery"),
}


@dataclass
class ComplexityFinding:
    key: str
    label: str
    excerpt: str
    url: str | None = None


def detect_complexity(text: str, url: str | None = None) -> list[ComplexityFinding]:
    """Operational-complexity indicators stated in the seller's own public text."""
    out: list[ComplexityFinding] = []
    for key, (label, rx) in COMPLEXITY.items():
        m = rx.search(text or "")
        if m:
            out.append(ComplexityFinding(key, label, _excerpt(text, m), url))
    return out


def complexity_level(keys: set[str]) -> str:
    """high (3+ indicators) | moderate (2) | low (1) | unknown (none seen yet)."""
    n = len(keys)
    return "high" if n >= 3 else "moderate" if n == 2 else "low" if n == 1 else "unknown"


# ------------------------------------------------------------------------------------------------
# Public activity signals and demand indicators (§10)
# ------------------------------------------------------------------------------------------------
# key -> (label, pattern, indicator_class)
ACTIVITY_SIGNALS: dict[str, tuple[str, re.Pattern[str], str]] = {
    "product_launch": ("New product or collection launched", re.compile(
        r"\b(new\s+(?:collection|arrival|launch|drop|range|design)|just\s+launched|now\s+available|"
        r"introducing|newly\s+added|fresh\s+(?:stock|arrivals?))\b", re.I), "activity"),
    "restock": ("Restock announced", re.compile(
        r"\b(back\s+in\s+stock|restock(?:ed|ing)?|available\s+again|refilled)\b", re.I), "activity"),
    "preorder_open": ("Pre-orders opened", re.compile(
        r"\b(pre.?orders?\s+(?:open|started|now|live)|booking\s+(?:open|started)|slots?\s+open|"
        r"orders?\s+open\s+for)\b", re.I), "activity"),
    "seasonal_campaign": ("Seasonal / festival campaign", re.compile(
        r"\b(diwali|deepavali|pongal|christmas|new\s+year|valentine|raksha\s?bandhan|navratri|onam|"
        r"festive\s+(?:collection|offer|special)|summer\s+collection|wedding\s+season)\b", re.I), "activity"),
    "expansion": ("Business expansion", re.compile(
        r"\b(new\s+(?:studio|store|outlet|kitchen|branch)|moved\s+to|now\s+(?:also\s+)?in|expanding|"
        r"opening\s+(?:soon|our))\b", re.I), "activity"),
    # Demand indicators: what the seller says about demand. Not proof of sales, volume or revenue.
    "sold_out": ("Says items sold out", re.compile(
        r"\b(sold\s?out|out\s+of\s+stock|fully\s+booked|slots?\s+(?:full|closed)|all\s+orders?\s+closed)\b",
        re.I), "demand_indicator"),
    "order_announcement": ("Announces orders being made / dispatched", re.compile(
        r"\b(order(?:s)?\s+(?:dispatched|shipped|delivered|ready|packed)|today'?s\s+orders?|"
        r"happy\s+customer|delivered\s+to)\b", re.I), "demand_indicator"),
    "repeat_order": ("Mentions repeat customers", re.compile(
        r"\b(repeat\s+(?:order|customer)|regular\s+customers?|ordered\s+again|loyal\s+customers?)\b",
        re.I), "demand_indicator"),
    "testimonial": ("Customer feedback published by the seller", re.compile(
        r"\b(customer\s+(?:review|feedback|love)|testimonial|what\s+our\s+customers|review\s+from|"
        r"thank\s+you\s+for\s+(?:your\s+)?(?:order|the\s+review))\b", re.I), "demand_indicator"),
    "enquiry_volume": ("Mentions enquiries received", re.compile(
        r"\b(many\s+enquir|lots\s+of\s+(?:dms?|messages?|enquir)|flooded\s+with|"
        r"reply(?:ing)?\s+to\s+(?:all\s+)?(?:dms?|messages?))\b", re.I), "demand_indicator"),
    "explicit_software_need": ("Explicitly mentions needing a system / struggling to manage orders", re.compile(
        r"\b(need\s+(?:an?\s+)?(?:app|software|system|website|order\s+form)|looking\s+for\s+(?:an?\s+)?(?:app|developer|software)|"
        r"(?:can'?t|cannot|hard\s+to|difficult\s+to|struggling\s+to)\s+(?:keep\s+track|track|manage|handle)\s+"
        r"(?:of\s+)?(?:all\s+)?(?:the\s+)?(?:orders?|dms?|messages?)|lost\s+(?:an?\s+)?orders?|"
        r"missed\s+(?:an?\s+)?orders?|orders?\s+(?:are\s+)?(?:getting\s+)?(?:mixed\s+up|confus))\b", re.I), "demand_indicator"),
}

# Signal types that can support S0 (a confirmed opportunity) when a human confirms them.
INTENT_SIGNALS = {"explicit_software_need"}


@dataclass
class SignalFinding:
    key: str
    label: str
    indicator_class: str
    excerpt: str
    url: str | None = None


def detect_signals(text: str, url: str | None = None) -> list[SignalFinding]:
    out: list[SignalFinding] = []
    for key, (label, rx, cls) in ACTIVITY_SIGNALS.items():
        m = rx.search(text or "")
        if m:
            out.append(SignalFinding(key, label, cls, _excerpt(text, m), url))
    return out


# ------------------------------------------------------------------------------------------------
# Current sales setup (§12) — a website is never a disqualifier
# ------------------------------------------------------------------------------------------------
SOCIAL_ONLY = "social_only"
SOCIAL_WHATSAPP = "social_whatsapp"
SOCIAL_SIMPLE_SITE = "social_simple_site"
SOCIAL_FULL_ECOM = "social_full_ecommerce"
MARKETPLACE_LED = "marketplace_led"
MULTI_CHANNEL = "multi_channel"
SETUP_UNKNOWN = "unknown"

SETUP_LABEL = {
    SOCIAL_ONLY: "Social only",
    SOCIAL_WHATSAPP: "Social + WhatsApp orders",
    SOCIAL_SIMPLE_SITE: "Social + simple website",
    SOCIAL_FULL_ECOM: "Social + full online checkout",
    MARKETPLACE_LED: "Sells mainly through a marketplace",
    MULTI_CHANNEL: "Several channels at once",
    SETUP_UNKNOWN: "Not known yet",
}

_CART_RX = re.compile(r"\b(add\s+to\s+(?:cart|bag)|checkout|my\s+cart|buy\s+now|place\s+order|payment\s+gateway|"
                      r"razorpay|stripe|payu|ccavenue|cashfree)\b", re.I)
_MARKETPLACE_RX = re.compile(r"\b(amazon\.in|flipkart|meesho|myntra|ajio|etsy|nykaa|swiggy|zomato|dunzo)\b", re.I)
# Order/inventory software a seller might already run (then a new system may be the wrong advice).
EXISTING_TOOLS_RX = re.compile(
    r"\b(shopify|woocommerce|wix|dukaan|instamojo|razorpay|zoho\s+(?:inventory|books|commerce)|vyapar|"
    r"khatabook|myBillBook|bill\s?book|tally|petpooja|posist|dotpe|bikayi|magicpin)\b", re.I)


@dataclass
class SetupFinding:
    setup: str
    reason: str
    order_channels: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return SETUP_LABEL[self.setup]


def classify_setup(*, platforms: set[str], website_text: str | None, website: str | None,
                   catalogue_url: str | None, bio_text: str | None) -> SetupFinding:
    """How the seller takes orders today, and which workflow step looks unsupported."""
    text = "\n".join(t for t in (bio_text, website_text) if t)
    tools = sorted({m.group(0).lower() for m in EXISTING_TOOLS_RX.finditer(text)})
    channels: list[str] = []
    if {"instagram", "facebook"} & platforms:
        channels.append("dm")
    if "whatsapp" in platforms or re.search(r"\bwhatsapp|wa\.me\b", text, re.I):
        channels.append("whatsapp")
    if re.search(r"\b(call\s+(?:us|now)|phone\s+orders?|\+91[\s-]?\d)", text or "", re.I):
        channels.append("phone")
    has_cart = bool(website_text and _CART_RX.search(website_text))
    if has_cart:
        channels.append("website_cart")
    if re.search(r"\b(order\s+form|google\s+form|forms\.gle|enquiry\s+form)\b", text or "", re.I):
        channels.append("form")
    marketplace = _MARKETPLACE_RX.search(text or "")
    if marketplace:
        channels.append("marketplace")

    gaps: list[str] = []
    if "dm" in channels or "whatsapp" in channels:
        gaps.append("Orders arrive as chat messages, so there is no single list of what is pending")
    if len([c for c in channels if c in ("dm", "whatsapp", "phone", "form", "website_cart", "marketplace")]) >= 2:
        gaps.append("Orders come from more than one place and have to be combined by hand")
    if has_cart and not tools:
        gaps.append("Has online checkout but no named system for tracking custom or made-to-order work")

    if marketplace and not has_cart:
        return SetupFinding(MARKETPLACE_LED, f"Mentions selling on {marketplace.group(0)}", channels, gaps, tools)
    if has_cart:
        setup = SOCIAL_FULL_ECOM
        reason = "Their website takes orders and payment online"
    elif website:
        setup = SOCIAL_SIMPLE_SITE
        reason = "Has a website, but no online checkout was found on the pages checked"
    elif "whatsapp" in channels:
        setup = SOCIAL_WHATSAPP
        reason = "Published a WhatsApp number for orders, with no website"
    elif platforms:
        setup = SOCIAL_ONLY
        reason = "Sells through social posts only; no website or order form found"
    else:
        return SetupFinding(SETUP_UNKNOWN, "Not enough public information yet", channels, gaps, tools)
    if len({c for c in channels if c in ("dm", "whatsapp", "phone", "form", "website_cart", "marketplace")}) >= 3:
        setup, reason = MULTI_CHANNEL, f"Takes orders through {len(set(channels))} different channels"
    return SetupFinding(setup, reason, channels, gaps, tools)
