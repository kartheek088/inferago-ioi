"""Deterministic lead qualification: gates → category (P0–P3) → score (/100) → friction → solution.

Pure functions over a `Snapshot`, so every rule is unit-testable. Every output carries reasons.

Rules that matter most:
- Gates are mandatory. A score never bypasses a gate.
- P0 needs a *human-confirmed* explicit requirement or a *buyer-confirmed* problem. Model or keyword
  confidence never promotes anything to P0.
- Unknown is not "pass": a gate with no evidence is `None` (needs verification), not True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.lead_rules import EQUIPMENT, INTENT_TYPES, SIGNAL_LABEL, WHOLESALE

INDUSTRY_LABEL = {EQUIPMENT: "Equipment Sales & Service", WHOLESALE: "Wholesale Distribution"}
P1_TRIGGER_DAYS = 180

WORKFLOW_KEYS = {
    EQUIPMENT: {"service_ops", "amc_warranty", "technicians", "installation", "service_request"},
    WHOLESALE: {"dealer_network", "warehouse", "dispatch_delivery", "multi_branch", "b2b_orders"},
}
COMPLEX_TOOLS = {"sap", "oracle", "salesforce", "microsoft dynamics"}


@dataclass
class SignalView:
    key: str  # signal type
    review_status: str  # hypothesis | confirmed | rejected
    published_at: datetime | None
    url: str | None
    statement: str = ""


@dataclass
class Snapshot:
    name: str
    industry: str | None
    industry_strength: str  # strong | candidate | none
    location_confidence: str  # verified | partial | unknown | outside
    activity: str  # active | likely_active | unknown | inactive
    official_contacts: int = 0
    directory_contacts: int = 0
    workflow_keys: set[str] = field(default_factory=set)  # source-verified workflow facts
    signals: list[SignalView] = field(default_factory=list)
    buyer_confirmed_problems: list[str] = field(default_factory=list)
    tools: set[str] = field(default_factory=set)  # existing software mentioned in sources (lower case)
    disqualifier: str | None = None
    review_status: str = "new"
    research_level: str = "directory"
    legal_form: str | None = None  # limited | private_limited | small_firm | None
    branch_count: int | None = None
    scope_confirmed: bool = False  # owner checked it isn't a large-enterprise procurement target
    official_facts: int = 0  # source-verified facts from the official website


def _age(dt: datetime | None, now: datetime) -> int | None:
    return None if dt is None else (now - dt).days


# ------------------------------------------------------------------------------------------------
# Gates
# ------------------------------------------------------------------------------------------------
def gates(s: Snapshot) -> list[dict]:
    """Mandatory checks before a company can enter the sales-ready queue. passed: True | False | None (unverified)."""
    g = []
    loc = {"verified": (True, "Chennai-city address confirmed on an official source"),
           "outside": (False, "Outside Chennai city"),
           "partial": (None, "Directory says Chennai city; not yet confirmed on the official website"),
           "unknown": (None, "Location not confirmed")}[s.location_confidence]
    g.append({"key": "chennai", "label": "Verified Chennai operation", "passed": loc[0], "detail": loc[1]})

    if s.industry is None:
        ind = (False, "Not one of the two target industries")
    elif s.industry_strength == "strong":
        ind = (True, f"{INDUSTRY_LABEL[s.industry]} — confirmed by operations on their website")
    else:
        ind = (None, f"{INDUSTRY_LABEL[s.industry]} according to the directory; operations not yet checked")
    g.append({"key": "industry", "label": "Approved industry", "passed": ind[0], "detail": ind[1]})

    rel = WORKFLOW_KEYS.get(s.industry or "", set()) & s.workflow_keys
    if rel:
        wf = (True, f"{len(rel)} relevant workflow(s) seen in sources")
    elif s.research_level == "directory":
        wf = (None, "Website not researched yet")
    else:
        wf = (None, "No relevant workflow found on the pages checked (absence is not proof)")
    g.append({"key": "workflow", "label": "Relevant operational workflow", "passed": wf[0], "detail": wf[1]})

    act = {"active": (True, "Recent activity on their website"), "inactive": (False, "Appears inactive"),
           "likely_active": (None, "Website is live but no dated recent activity found"),
           "unknown": (None, "Activity not checked")}[s.activity]
    g.append({"key": "active", "label": "Current business activity", "passed": act[0], "detail": act[1]})

    if s.official_contacts:
        ct = (True, "Contact published on their own website")
    elif s.directory_contacts:
        ct = (True, "Contact from a public directory listing (not yet seen on their website)")
    else:
        ct = (None, "No public business contact found yet")
    g.append({"key": "contact", "label": "Legitimate public contact route", "passed": ct[0], "detail": ct[1]})

    if s.disqualifier:
        sc = (False, s.disqualifier)
    elif s.scope_confirmed:
        sc = (True, "Confirmed by you as a realistic size for Inferago")
    elif s.legal_form == "limited":
        sc = (None, "Public limited company — check it isn't a large enterprise with formal procurement")
    elif s.branch_count and s.branch_count >= 20:
        sc = (None, f"{s.branch_count} branches — check it isn't a large enterprise")
    else:
        sc = (True, "No sign of enterprise-scale procurement or a known blocker")
    g.append({"key": "scope", "label": "Practical delivery scope", "passed": sc[0], "detail": sc[1]})
    return g


def sales_ready(gs: list[dict]) -> bool:
    return all(x["passed"] is True for x in gs)


# ------------------------------------------------------------------------------------------------
# Category
# ------------------------------------------------------------------------------------------------
def intent_evidence(s: Snapshot) -> list[SignalView]:
    return [x for x in s.signals if x.key in INTENT_TYPES and x.review_status == "confirmed" and x.url]


def recent_triggers(s: Snapshot, now: datetime) -> list[SignalView]:
    out = []
    for x in s.signals:
        a = _age(x.published_at, now)
        if x.review_status != "rejected" and x.url and a is not None and 0 <= a <= P1_TRIGGER_DAYS:
            out.append(x)
    return out


def buying_intent(s: Snapshot, now: datetime) -> str:
    """confirmed (buyer told you) | explicit_public (a confirmed public request) | indirect | unknown."""
    if s.buyer_confirmed_problems:
        return "confirmed"
    if intent_evidence(s):
        return "explicit_public"
    if any(x.review_status != "rejected" for x in s.signals):
        return "indirect"
    return "unknown"


def categorise(s: Snapshot, gs: list[dict], now: datetime) -> tuple[str, list[str]]:
    if s.review_status == "duplicate":
        return "P3", ["Duplicate of another business"]
    if s.review_status == "rejected":
        return "P3", ["Rejected by you"]
    failed = [x for x in gs if x["passed"] is False]
    if failed:
        return "P3", [f"{x['label']}: {x['detail']}" for x in failed]
    open_gates = [x for x in gs if x["passed"] is None]
    if not open_gates:
        if s.buyer_confirmed_problems:
            return "P0", ["Passes every gate", f"Buyer-confirmed problem: {s.buyer_confirmed_problems[0]}"]
        intent = intent_evidence(s)
        if intent:
            x = intent[0]
            return "P0", ["Passes every gate", f"Confirmed explicit need: {SIGNAL_LABEL.get(x.key, x.key)} — {x.url}"]
        trig = recent_triggers(s, now)
        if trig:
            x = trig[0]
            return "P1", ["Passes every gate",
                          f"Recent trigger ({_age(x.published_at, now)} days): {SIGNAL_LABEL.get(x.key, x.key)} — {x.url}",
                          "Buying intention not confirmed yet"]
        return "P2", ["Passes every gate, but no recent trigger or confirmed need yet"]
    return "P2", ["Needs verification: " + "; ".join(f"{x['label'].lower()} ({x['detail']})" for x in open_gates)]


# ------------------------------------------------------------------------------------------------
# Score (/100) — ranks within a category only
# ------------------------------------------------------------------------------------------------
def score(s: Snapshot, solution_level: int | None, now: datetime) -> tuple[int, list[dict]]:
    parts: list[dict] = []

    def add(key: str, label: str, pts: int, max_pts: int, why: str) -> None:
        parts.append({"key": key, "label": label, "points": pts, "max": max_pts, "why": why})

    if s.buyer_confirmed_problems or intent_evidence(s):
        add("intent", "Buying intent / documented pain", 30, 30, "Confirmed need")
    elif any(x.key in INTENT_TYPES and x.review_status == "hypothesis" for x in s.signals):
        add("intent", "Buying intent / documented pain", 12, 30, "Possible need detected, not yet confirmed")
    else:
        add("intent", "Buying intent / documented pain", 0, 30, "No evidence of a need yet")

    rel = WORKFLOW_KEYS.get(s.industry or "", set()) & s.workflow_keys
    wf = {0: 0, 1: 8, 2: 14}.get(len(rel), 20)
    if not rel and s.industry and s.industry_strength == "candidate":
        wf = 4
    add("workflow", "Workflow fit", wf, 20, f"{len(rel)} relevant workflow(s) in sources" if rel else "Industry from directory only")

    if s.official_contacts >= 2:
        add("contact", "Contact accessibility", 15, 15, "Phone and/or email on their own website")
    elif s.official_contacts == 1:
        add("contact", "Contact accessibility", 12, 15, "One contact on their own website")
    elif s.directory_contacts:
        add("contact", "Contact accessibility", 6, 15, "Directory contact only")
    else:
        add("contact", "Contact accessibility", 0, 15, "No contact found")

    ages = [a for a in (_age(x.published_at, now) for x in s.signals if x.review_status != "rejected") if a is not None and a >= 0]
    best = min(ages) if ages else None
    rec = 10 if best is not None and best <= 30 else 7 if best is not None and best <= 90 else 4 if best is not None and best <= 180 else 0
    add("recency", "Recent operational signal", rec, 10, f"Latest dated signal {best} days old" if best is not None else "No dated signal")

    feas = {"small_firm": 10, "private_limited": 7, "limited": 2}.get(s.legal_form or "", 5)
    if s.branch_count and s.branch_count >= 10:
        feas = min(feas, 4)
    add("feasibility", "Commercial feasibility", feas, 10,
        {"small_firm": "Owner-run firm", "private_limited": "Private limited company", "limited": "Public limited: formal procurement likely"}
        .get(s.legal_form or "", "Company size unknown"))

    simp = {3: 10, 4: 9, 5: 7, 6: 3}.get(solution_level or 0, 5)
    if s.tools & COMPLEX_TOOLS:
        simp = min(simp, 4)
    add("simplicity", "Implementation simplicity", simp, 10,
        "Uses a large ERP (integration harder)" if s.tools & COMPLEX_TOOLS else "Small, well-scoped setup" if simp >= 7 else "Scope unclear")

    eq = 5 if s.location_confidence == "verified" and s.research_level != "directory" else 3 if s.research_level != "directory" else 1
    add("evidence", "Evidence quality", eq, 5, {5: "Verified on official website", 3: "Website checked", 1: "Directory only"}[eq])
    return sum(p["points"] for p in parts), parts


# ------------------------------------------------------------------------------------------------
# Sales friction (separate from score)
# ------------------------------------------------------------------------------------------------
def friction(s: Snapshot) -> tuple[str, list[str]]:
    reasons: list[str] = []
    up = down = known = 0
    if s.official_contacts:
        down += 1; known += 1; reasons.append("Easier: they publish a business contact")
    elif not s.directory_contacts:
        up += 1; reasons.append("Harder: no public contact found")
    if s.legal_form == "limited":
        up += 2; known += 1; reasons.append("Harder: public limited company — formal procurement likely")
    elif s.legal_form == "small_firm":
        down += 1; known += 1; reasons.append("Easier: owner-run firm — decision-maker likely reachable")
    elif s.legal_form == "private_limited":
        known += 1; reasons.append("Neutral: private limited — vendor onboarding may apply")
    if s.tools & COMPLEX_TOOLS:
        up += 1; known += 1; reasons.append("Harder: mentions " + ", ".join(sorted(s.tools & COMPLEX_TOOLS)).upper() + " — third-party integration risk")
    elif s.tools:
        known += 1; reasons.append("Neutral: mentions " + ", ".join(sorted(s.tools)) + " — may need integration")
    if s.branch_count and s.branch_count >= 10:
        up += 1; known += 1; reasons.append(f"Harder: {s.branch_count} branches — more stakeholders")
    if s.buyer_confirmed_problems or intent_evidence(s):
        down += 1; known += 1; reasons.append("Easier: a current need is confirmed")
    if s.disqualifier:
        return "high", reasons + [f"Blocker: {s.disqualifier}"]
    if known < 2:
        return "unknown", reasons + ["Too little known to judge"]
    net = up - down
    return ("low" if net <= -1 else "moderate" if net <= 1 else "high"), reasons


# ------------------------------------------------------------------------------------------------
# Solution recommendation (smallest practical step first)
# ------------------------------------------------------------------------------------------------
HIERARCHY = {1: "Improve the existing process", 2: "Configure existing software", 3: "Automate a repetitive task",
             4: "Integrate existing systems", 5: "Build a small custom module", 6: "Build a larger application"}

_OPS_TEXT = {
    "service_ops": "after-sales service / repairs", "amc_warranty": "AMC / warranty contracts", "technicians": "field technicians",
    "installation": "installation & commissioning", "service_request": "online service requests", "dealer_network": "a dealer/retailer network",
    "warehouse": "warehouse / godown", "dispatch_delivery": "dispatch & delivery", "multi_branch": "several branches",
    "b2b_orders": "bulk / B2B orders",
}


def recommend(s: Snapshot) -> dict:
    from app.ioi3.solutions import alternatives

    out = _recommend(s)
    out["existing_software"] = alternatives(s.industry, s.tools)
    return out


def _recommend(s: Snapshot) -> dict:
    known = [_OPS_TEXT[k] for k in sorted(s.workflow_keys) if k in _OPS_TEXT]
    known_text = ("Seen in sources: " + ", ".join(known)) if known else "Not known yet — only directory information so far"
    tools_note = f" They mention {', '.join(sorted(s.tools))}." if s.tools else ""
    integration = any(x.key == "integration_need" and x.review_status != "rejected" for x in s.signals)

    if s.buyer_confirmed_problems and len(s.buyer_confirmed_problems) == 1 and not integration:
        return {
            "offer": "Small Automation", "level": 3, "level_label": HIERARCHY[3], "known_workflow": known_text,
            "improvement": f"Automate the one task the buyer described: {s.buyer_confirmed_problems[0]}",
            "scope": ["Map the current steps with the person who does them", "Automate that single task", "One week of support"],
            "why": "One confirmed problem: the smallest fix is the right first project.",
            "confirm_with_buyer": ["How often does this task happen, and how long does it take?", "What tools are used today?"],
        }
    if integration or (s.tools and not s.tools & COMPLEX_TOOLS and s.industry):
        return {
            "offer": "Integration Fix", "level": 4, "level_label": HIERARCHY[4], "known_workflow": known_text + "." + tools_note,
            "improvement": "Connect the tools they already use so orders/service data are entered once.",
            "scope": ["List the systems and the data that is re-typed", "Build one integration (e.g. to Tally/Zoho)", "Test with real records"],
            "why": "Works with existing software instead of replacing it.",
            "confirm_with_buyer": ["Which systems do you use today, and where is data typed twice?", "Can we get API/export access?"],
        }
    if s.industry == EQUIPMENT:
        return {
            "offer": "ServiceFlow Setup", "level": 5, "level_label": HIERARCHY[5], "known_workflow": known_text + "." + tools_note,
            "improvement": "One place to log service requests, assign technicians, and get AMC/warranty renewal reminders.",
            "scope": ["Service request log (phone/WhatsApp entries)", "Technician assignment and job status",
                      "Customer & equipment records", "AMC/warranty reminders", "Pending-jobs report"],
            "why": "Their business depends on coordinating service work" + (" (seen: " + ", ".join(known[:3]) + ")" if known else "") + ".",
            "confirm_with_buyer": ["How are service requests recorded and assigned today?", "How many technicians and jobs a month?",
                                   "How are AMC renewals tracked?", "Do you already use any software for this?"],
        }
    if s.industry == WHOLESALE:
        return {
            "offer": "OrderFlow Setup", "level": 5, "level_label": HIERARCHY[5], "known_workflow": known_text + "." + tools_note,
            "improvement": "One place to take dealer orders, track dispatch status and see pending actions.",
            "scope": ["Order intake (phone/WhatsApp orders entered once)", "Order & dispatch status",
                      "Customer order history", "Pending-action reminders", "Basic daily report"],
            "why": "Distribution runs on repeat orders and dispatch coordination" + (" (seen: " + ", ".join(known[:3]) + ")" if known else "") + ".",
            "confirm_with_buyer": ["How do dealers place orders today?", "How many orders a day?", "How is dispatch tracked?",
                                   "Which accounting software do you use?"],
        }
    return {"offer": None, "level": None, "level_label": None, "known_workflow": known_text, "improvement": None, "scope": [],
            "why": "Not in a target industry.", "confirm_with_buyer": []}


def next_action(category: str, gs: list[dict], s: Snapshot) -> str:
    if category == "P3":
        return "No action."
    if s.review_status == "approved":
        return "Contact them using the approved draft, then log it in Outreach."
    pending_signals = [x for x in s.signals if x.review_status == "hypothesis"]
    if pending_signals:
        return "Check the detected signal: open the source, then confirm or reject it."
    for x in gs:
        if x["passed"] is None:
            return {
                "chennai": "Research further: confirm the Chennai address on their website.",
                "industry": "Research further: check their website for service or distribution operations.",
                "workflow": "Research further: look for service/distribution workflow on their website.",
                "active": "Check for recent activity (news, updates, dated posts).",
                "contact": "Find a public business phone or email on their website.",
                "scope": "Check the company's size: if it's a realistic client (not a large enterprise), mark it so in Correct details.",
            }.get(x["key"], "Research further.")
    if category in ("P0", "P1"):
        return "Review and approve for outreach."
    return "Look for a current need, or approve for a low-pressure introduction."


# ------------------------------------------------------------------------------------------------
# Separate classifications (never combined into a win probability)
# ------------------------------------------------------------------------------------------------
def operational_fit(s: Snapshot) -> str:
    rel = WORKFLOW_KEYS.get(s.industry or "", set()) & s.workflow_keys
    if s.industry is None:
        return "weak"
    if s.research_level == "directory" and not rel:
        return "unknown"
    return "strong" if len(rel) >= 3 else "moderate" if rel else "weak"


def commercial_readiness(s: Snapshot, now: datetime) -> str:
    """buyer_confirmed | limited_public (public signals + relevant operations) | unknown. Never inferred from popularity."""
    if s.buyer_confirmed_problems:
        return "buyer_confirmed"
    rel = WORKFLOW_KEYS.get(s.industry or "", set()) & s.workflow_keys
    if rel and recent_triggers(s, now):
        return "limited_public"
    return "unknown"


def evidence_quality(s: Snapshot) -> str:
    researched = s.research_level != "directory"
    if s.location_confidence == "verified" and researched and s.official_facts >= 3 and s.activity == "active":
        return "strong"
    if researched or s.location_confidence == "verified":
        return "partial"
    return "weak"
