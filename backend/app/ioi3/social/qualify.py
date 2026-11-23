"""Social-commerce qualification: gates → category (S0-S3) → score (/100) → maturity → solution.

Separate from the B2B engine on purpose: a social seller with no website, no registered entity and no
office is not disqualified, while a B2B company with those gaps would need explaining.

The rules that matter most:
- Gates are mandatory. No score ever bypasses a gate.
- S0 needs a human-confirmed explicit request or a buyer-confirmed problem. A keyword match that
  looks like "I can't manage my orders" is a hypothesis until a person checks the post.
- Unknown is never "pass": a gate with no evidence is None (needs verification), not True.
- Follower counts, likes and comment volume are never inputs. Popularity is not revenue, budget or
  buying intent, and this module has no access to them by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.ioi3.social import categories as cat
from app.ioi3.social import geo
from app.ioi3.social.platforms import PLATFORM_LABEL

# A dated public signal this recent counts as a current trigger.
TRIGGER_DAYS = 180
# Activity older than this, with nothing newer, means we cannot call the seller active.
STALE_DAYS = 365

S0, S1, S2, S3 = "S0", "S1", "S2", "S3"
CATEGORY_LABEL = {
    S0: "Confirmed opportunity",
    S1: "High-fit social seller",
    S2: "Watchlist",
    S3: "Excluded",
}

GROWING = "growing_operational"
ESTABLISHED = "established_social"
EARLY = "early_stage"
UNCLEAR_ACT = "activity_unclear"
INACTIVE = "inactive_unverified"
MATURITY_LABEL = {
    GROWING: "Growing operational seller",
    ESTABLISHED: "Established social-first business",
    EARLY: "Early-stage seller",
    UNCLEAR_ACT: "Activity unclear",
    INACTIVE: "Inactive / unverified",
}
# These are operational categories from public evidence. They say nothing about revenue or budget.
MATURITY_NOTE = "An operational description from public evidence only — not a financial assessment."


@dataclass
class ActivityView:
    key: str
    indicator_class: str  # activity | demand_indicator
    published_at: datetime | None
    url: str | None
    review_status: str  # hypothesis | confirmed | rejected
    statement: str = ""


@dataclass
class Snapshot:
    name: str
    category: str | None
    geo_confidence: str
    platforms: set[str] = field(default_factory=set)
    activity: list[ActivityView] = field(default_factory=list)
    complexity_keys: set[str] = field(default_factory=set)
    confirmed_problems: list[str] = field(default_factory=list)  # buyer told the owner
    official_contacts: int = 0  # published on their own profile/site
    other_contacts: int = 0
    sales_setup: str = cat.SETUP_UNKNOWN
    order_channels: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    workflow_gaps: list[str] = field(default_factory=list)
    research_level: str = "profile"  # profile | public | deep
    review_status: str = "new"
    disqualifier: str | None = None
    accounts: int = 0
    business_account: bool = False
    weak_geo_only: list[str] = field(default_factory=list)


def _age(dt: datetime | None, now: datetime) -> int | None:
    return None if dt is None else (now - dt).days


def live(s: Snapshot) -> list[ActivityView]:
    return [a for a in s.activity if a.review_status != "rejected"]


def dated(s: Snapshot, now: datetime, within: int = TRIGGER_DAYS) -> list[ActivityView]:
    out = []
    for a in live(s):
        age = _age(a.published_at, now)
        if a.url and age is not None and 0 <= age <= within:
            out.append(a)
    return sorted(out, key=lambda a: a.published_at or now, reverse=True)


def newest_age(s: Snapshot, now: datetime) -> int | None:
    ages = [a for a in (_age(x.published_at, now) for x in live(s)) if a is not None and a >= 0]
    return min(ages) if ages else None


def confirmed_intent(s: Snapshot) -> list[ActivityView]:
    """A public request for help that a human has opened and confirmed."""
    return [a for a in s.activity if a.key in cat.INTENT_SIGNALS and a.review_status == "confirmed" and a.url]


# ------------------------------------------------------------------------------------------------
# Mandatory gates (§13)
# ------------------------------------------------------------------------------------------------
def gates(s: Snapshot, now: datetime | None = None) -> list[dict]:
    from app.db import utcnow

    now = now or utcnow()
    g: list[dict] = []

    loc = {
        geo.VERIFIED: (True, "Chennai operations confirmed from the business itself"),
        geo.OUTSIDE: (False, "Operates outside Chennai city"),
        geo.PROBABLE: (None, "Probably Chennai — needs one more independent source"),
        geo.UNCLEAR: (None, "Location not established from the business itself"),
    }[s.geo_confidence]
    detail = loc[1]
    if s.geo_confidence == geo.UNCLEAR and s.weak_geo_only:
        detail += f" (only {', '.join(s.weak_geo_only[:3])} — these never count)"
    g.append({"key": "chennai", "label": "Credible Chennai operations", "passed": loc[0], "detail": detail})

    if s.category is None:
        c = (None, "Not yet matched to a social-commerce category") if s.research_level == "profile" else \
            (False, "Does not sell in a category Inferago targets")
    else:
        c = (True, cat.CATEGORY_LABEL[s.category])
    g.append({"key": "category", "label": "Relevant social-commerce category", "passed": c[0], "detail": c[1]})

    if s.disqualifier:
        act = (False, s.disqualifier)
    else:
        age = newest_age(s, now)
        if age is not None and age <= TRIGGER_DAYS:
            act = (True, f"Public business activity {age} days ago")
        elif age is not None and age > STALE_DAYS:
            act = (False, f"Nothing published for {age} days — cannot be called active")
        elif age is not None:
            act = (None, f"Latest dated activity is {age} days old — check they are still trading")
        elif live(s):
            seen = live(s)
            kinds = []
            n_act = sum(1 for a in seen if a.indicator_class == "activity")
            n_dem = len(seen) - n_act
            if n_act:
                kinds.append(f"{n_act} activity signal(s)")
            if n_dem:
                kinds.append(f"{n_dem} demand indicator(s)")
            act = (None, f"{' and '.join(kinds)} found, but none carried a date — "
                         "check their latest post or confirm by phone")
        else:
            act = (None, "No public business activity checked yet")
    g.append({"key": "activity", "label": "Current commercial activity", "passed": act[0], "detail": act[1]})

    if s.confirmed_problems:
        cx = (True, f"Buyer confirmed: {s.confirmed_problems[0][:120]}")
    elif s.complexity_keys:
        labels = [cat.COMPLEXITY[k][0].lower() for k in sorted(s.complexity_keys) if k in cat.COMPLEXITY]
        cx = (True, f"{len(labels)} order-complexity indicator(s): {', '.join(labels[:3])}")
    elif s.research_level == "profile":
        cx = (None, "Their public pages have not been checked for order complexity yet")
    else:
        cx = (None, "No order complexity found on the pages checked (absence is not proof)")
    g.append({"key": "complexity", "label": "Relevant operational complexity", "passed": cx[0], "detail": cx[1]})

    if s.official_contacts:
        ct = (True, "Business contact published on their own profile or site")
    elif s.other_contacts:
        ct = (True, "Business contact from a public listing (not yet seen on their own profile)")
    else:
        ct = (None, "No public business contact route found yet")
    g.append({"key": "contact", "label": "Legitimate public contact route", "passed": ct[0], "detail": ct[1]})

    if s.disqualifier:
        fit = (False, s.disqualifier)
    elif s.sales_setup == cat.MARKETPLACE_LED:
        fit = (None, "Sells mainly through a marketplace — check whether a separate tool would help at all")
    elif s.tools and not s.workflow_gaps:
        fit = (None, f"Already uses {', '.join(sorted(s.tools))} with no gap visible — check before offering anything")
    else:
        fit = (True, "A small workflow tool is a practical fit for how they sell")
    g.append({"key": "fit", "label": "Practical service fit", "passed": fit[0], "detail": fit[1]})
    return g


def ready(gs: list[dict]) -> bool:
    """Every mandatory gate passed: only then can a seller enter the outreach queue."""
    return all(x["passed"] is True for x in gs)


# ------------------------------------------------------------------------------------------------
# Category S0-S3
# ------------------------------------------------------------------------------------------------
def categorise(s: Snapshot, gs: list[dict], now: datetime) -> tuple[str, list[str]]:
    if s.review_status == "duplicate":
        return S3, ["Duplicate of another seller"]
    if s.review_status == "rejected":
        return S3, ["Rejected by you"]
    failed = [x for x in gs if x["passed"] is False]
    if failed:
        return S3, [f"{x['label']}: {x['detail']}" for x in failed]
    open_gates = [x for x in gs if x["passed"] is None]
    if open_gates:
        return S2, ["Needs verification: " + "; ".join(f"{x['label'].lower()} ({x['detail']})" for x in open_gates)]
    if s.confirmed_problems:
        return S0, ["Passes every check", f"Buyer-confirmed problem: {s.confirmed_problems[0][:160]}"]
    intent = confirmed_intent(s)
    if intent:
        return S0, ["Passes every check",
                    f"Confirmed public request for help: {cat.ACTIVITY_SIGNALS[intent[0].key][0]} — {intent[0].url}"]
    trig = dated(s, now)
    if trig:
        a = trig[0]
        return S1, ["Passes every check",
                    f"Recent activity ({_age(a.published_at, now)} days): {cat.ACTIVITY_SIGNALS.get(a.key, (a.key,))[0]}",
                    "They have not asked for help — buying intent is not confirmed"]
    return S2, ["Passes every check, but no recent dated activity and no confirmed need yet"]


# ------------------------------------------------------------------------------------------------
# Score (/100) — ranks within a category, never a win probability (§13)
# ------------------------------------------------------------------------------------------------
def score(s: Snapshot, now: datetime, solution_level: int | None = None) -> tuple[int, list[dict]]:
    parts: list[dict] = []

    def add(key: str, label: str, pts: int, max_pts: int, why: str) -> None:
        parts.append({"key": key, "label": label, "points": pts, "max": max_pts, "why": why})

    # 1. Confirmed need or credible operational pain — 30
    if s.confirmed_problems:
        add("need", "Confirmed need or credible pain", 30, 30, "The buyer described the problem themselves")
    elif confirmed_intent(s):
        add("need", "Confirmed need or credible pain", 30, 30, "A public request for help, checked by you")
    elif any(a.key in cat.INTENT_SIGNALS and a.review_status == "hypothesis" for a in s.activity):
        add("need", "Confirmed need or credible pain", 12, 30,
            "A post looks like a complaint about managing orders — not confirmed yet")
    else:
        add("need", "Confirmed need or credible pain", 0, 30, "No evidence they want help")

    # 2. Order / process complexity — 25
    n = len(s.complexity_keys)
    pts = {0: 0, 1: 8, 2: 15, 3: 20}.get(n, 25)
    add("complexity", "Order and process complexity", pts, 25,
        f"{n} complexity indicator(s) in their own posts" if n else "No order complexity visible yet")

    # 3. Public business activity — 15
    age = newest_age(s, now)
    n_act = len([a for a in live(s) if a.indicator_class == "activity"])
    if age is None:
        act_pts, why = (4, f"{n_act} activity signal(s) but none dated") if n_act else (0, "No public activity found")
    elif age <= 30:
        act_pts, why = 15, f"Active {age} days ago"
    elif age <= 90:
        act_pts, why = 12, f"Active {age} days ago"
    elif age <= TRIGGER_DAYS:
        act_pts, why = 8, f"Latest activity {age} days ago"
    elif age <= STALE_DAYS:
        act_pts, why = 3, f"Latest activity {age} days ago — getting stale"
    else:
        act_pts, why = 0, f"Nothing published for {age} days"
    add("activity", "Public business activity", act_pts, 15, why)

    # 4. Contact accessibility — 10
    if s.official_contacts >= 2:
        add("contact", "Business contact accessibility", 10, 10, "More than one contact route they published themselves")
    elif s.official_contacts == 1:
        add("contact", "Business contact accessibility", 8, 10, "One contact route they published themselves")
    elif s.other_contacts:
        add("contact", "Business contact accessibility", 4, 10, "Contact from a public listing only")
    else:
        add("contact", "Business contact accessibility", 0, 10, "No public business contact found")

    # 5. Implementation simplicity — 10 (a cheaper, smaller job scores higher)
    simp = {1: 10, 2: 9, 3: 8, 4: 5, 5: 4}.get(solution_level or 0, 5)
    if s.sales_setup == cat.MARKETPLACE_LED:
        simp = min(simp, 3)
    add("simplicity", "Implementation simplicity", simp, 10,
        "Marketplace-led: less room for a separate tool" if s.sales_setup == cat.MARKETPLACE_LED
        else "Small, well-scoped job" if simp >= 8 else "Larger or less certain scope")

    # 6. Source quality — 10
    strong_geo = s.geo_confidence == geo.VERIFIED
    if strong_geo and s.research_level == "deep":
        sq, why = 10, "Location verified and their public pages were read"
    elif strong_geo:
        sq, why = 8, "Location verified from the business itself"
    elif s.research_level != "profile":
        sq, why = 5, "Public pages read, location not yet verified"
    else:
        sq, why = 2, "Only the profile link so far"
    add("source", "Source quality", sq, 10, why)
    return sum(p["points"] for p in parts), parts


# ------------------------------------------------------------------------------------------------
# Business maturity (§11) — evidence-based operational categories, never financial
# ------------------------------------------------------------------------------------------------
def maturity(s: Snapshot, now: datetime) -> tuple[str, list[str]]:
    reasons: list[str] = []
    acts = live(s)
    age = newest_age(s, now)
    dated_count = len([a for a in acts if a.published_at is not None])
    demand = len([a for a in acts if a.indicator_class == "demand_indicator"])
    recurring = bool({"recurring", "order_volume_text"} & s.complexity_keys)
    channels = len({c for c in s.order_channels})

    if not acts:
        return INACTIVE, ["No public business activity has been found yet"]
    if age is not None and age > STALE_DAYS:
        return INACTIVE, [f"Latest dated activity is {age} days old"]
    if age is None:
        reasons.append(f"{len(acts)} activity signal(s) found, none with a date")
        return UNCLEAR_ACT, reasons

    reasons.append(f"Last published activity {age} days ago")
    if dated_count >= 3:
        reasons.append(f"{dated_count} dated signals — activity looks consistent, not a one-off")
    if demand:
        reasons.append(f"{demand} demand indicator(s) they published (sold out, dispatches, repeat customers)")
    if s.complexity_keys:
        reasons.append(f"{len(s.complexity_keys)} order-complexity indicator(s)")
    if channels >= 2:
        reasons.append(f"Takes orders through {channels} channels")
    if recurring:
        reasons.append("Signs of repeat or higher-volume operations")
    if s.official_contacts:
        reasons.append("Publishes a business contact route")

    strong = age <= 90 and len(s.complexity_keys) >= 3 and dated_count >= 3 and (recurring or demand >= 2)
    growing = age <= TRIGGER_DAYS and len(s.complexity_keys) >= 2 and (s.official_contacts or channels >= 2)
    if strong:
        return ESTABLISHED, reasons
    if growing:
        return GROWING, reasons
    if age <= TRIGGER_DAYS:
        return EARLY, reasons + ["Limited order complexity visible so far"]
    return UNCLEAR_ACT, reasons


# ------------------------------------------------------------------------------------------------
# Separate classifications (never combined into a win probability)
# ------------------------------------------------------------------------------------------------
def buying_intent(s: Snapshot) -> str:
    if s.confirmed_problems:
        return "confirmed"
    if confirmed_intent(s):
        return "explicit_public"
    if any(a.key in cat.INTENT_SIGNALS for a in live(s)):
        return "indirect"
    return "unknown"


def operational_fit(s: Snapshot) -> str:
    if s.category is None:
        return "weak" if s.research_level != "profile" else "unknown"
    n = len(s.complexity_keys)
    if s.research_level == "profile" and not n:
        return "unknown"
    return "strong" if n >= 3 else "moderate" if n >= 1 else "weak"


def commercial_readiness(s: Snapshot, now: datetime) -> str:
    if s.confirmed_problems:
        return "buyer_confirmed"
    if s.complexity_keys and dated(s, now):
        return "limited_public"
    return "unknown"


def evidence_quality(s: Snapshot) -> str:
    researched = s.research_level != "profile"
    if s.geo_confidence == geo.VERIFIED and researched and s.complexity_keys and s.official_contacts:
        return "strong"
    if researched or s.geo_confidence == geo.VERIFIED:
        return "partial"
    return "weak"


def friction(s: Snapshot) -> tuple[str, list[str]]:
    """How hard this seller is likely to be to sell to and deliver for. Separate from the score."""
    reasons: list[str] = []
    up = down = known = 0
    if s.official_contacts:
        down += 1; known += 1; reasons.append("Easier: they publish a way to contact the business")
    else:
        up += 1; reasons.append("Harder: no public business contact found")
    if s.confirmed_problems or confirmed_intent(s):
        down += 1; known += 1; reasons.append("Easier: a current need is confirmed")
    if s.business_account:
        down += 1; known += 1; reasons.append("Easier: uses a business account, so they treat this as a business")
    if s.tools:
        up += 1; known += 1; reasons.append("Harder: already pays for " + ", ".join(sorted(s.tools)) + " — may not want another tool")
    if s.sales_setup == cat.MARKETPLACE_LED:
        up += 1; known += 1; reasons.append("Harder: the marketplace controls their order flow")
    if len(s.complexity_keys) <= 1:
        up += 1; known += 1; reasons.append("Harder: little visible complexity, so the value may be small")
    if s.disqualifier:
        return "high", reasons + [f"Blocker: {s.disqualifier}"]
    if known < 2:
        return "unknown", reasons + ["Too little known to judge"]
    net = up - down
    return ("low" if net <= -1 else "moderate" if net <= 1 else "high"), reasons


def next_action(category: str, gs: list[dict], s: Snapshot) -> str:
    if category == S3:
        return "No action."
    if s.review_status == "approved":
        return "Message them using the approved draft, then log it in Outreach."
    pending = [a for a in s.activity if a.key in cat.INTENT_SIGNALS and a.review_status == "hypothesis"]
    if pending:
        return "Open the post that looks like a request for help, then confirm or reject it."
    for x in gs:
        if x["passed"] is None:
            return {
                "chennai": "Confirm where they operate: look for a Chennai address, delivery area or pickup point they published.",
                "category": "Open their profile and record what they actually sell.",
                "activity": "Check their latest post and record the date, or confirm by phone that they are still trading.",
                "complexity": "Read their profile and catalogue for sizes, custom orders, advances and delivery promises.",
                "contact": "Find the business phone, email or order link they published.",
                "fit": "Check what they already use for orders before offering anything.",
            }.get(x["key"], "Research further.")
    if category in (S0, S1):
        return "Review and approve for outreach."
    return "Look for a current need, or approve a low-pressure introduction."
