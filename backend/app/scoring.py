"""Three separate, explainable scoring algorithms (each out of 100).

Every component reports value, max, whether the underlying data is KNOWN, and an explanation.
Unknown data scores 0 but is flagged `known=False` — distinct from a negative finding
(`known=True`, value 0). Mandatory eligibility failures override all three scores.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.enums import Category, EligibilityOutcome, Pipeline, ScoreType


@dataclass
class Component:
    name: str
    max: int
    value: float
    known: bool
    explanation: str

    def __post_init__(self) -> None:
        self.value = round(max(0.0, min(float(self.max), float(self.value))), 1)


@dataclass
class ScoreResult:
    score_type: ScoreType
    components: list[Component]
    disqualified: bool
    raw_total: float = 0.0
    effective_total: float = 0.0
    unknown_components: int = 0
    explanation: str = ""

    def __post_init__(self) -> None:
        self.raw_total = round(sum(c.value for c in self.components), 1)
        self.effective_total = 0.0 if self.disqualified else self.raw_total
        self.unknown_components = sum(1 for c in self.components if not c.known)

    def components_dict(self) -> list[dict[str, Any]]:
        return [asdict(c) for c in self.components]


@dataclass
class ScoringInput:
    category: str
    services: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    signals: list[tuple[str, str]] = field(default_factory=list)  # (type, strength)
    has_text: bool = True
    description_length: int = 0
    budget_text: str | None = None
    deadline: datetime | None = None
    scope_detail_terms: int = 0
    contacts_verified: int = 0
    contacts_unverified: int = 0
    vendor_portal_found: bool = False
    research_done: bool = False
    vendor_positive: list[str] = field(default_factory=list)
    vendor_negative: list[str] = field(default_factory=list)
    evidence_count: int = 0
    published_at: datetime | None = None
    classification_confidence: float = 0.0
    eligibility_outcome: str | None = None
    vendor_registration_outcome: str | None = None
    accepts_external_vendors: bool | None = None
    country: str | None = None
    remote_ok: bool | None = None
    confirmed_relationships: dict[str, int] = field(default_factory=dict)
    hypothesis_relationships: int = 0
    org_opportunity_count: int = 1
    repeat_terms: list[str] = field(default_factory=list)
    confirmed_repeat_links: int = 0
    now: datetime | None = None


def _service_points(n: int, top: int) -> float:
    if n <= 0:
        return 0
    return {1: top * 0.6, 2: top * 0.8}.get(n, top)


def _is_disqualified(inp: ScoringInput) -> bool:
    return inp.eligibility_outcome == EligibilityOutcome.NOT_ELIGIBLE.value


def _dq_note(inp: ScoringInput) -> str:
    return " DISQUALIFIED: a mandatory eligibility requirement is not met, so the effective score is 0." if _is_disqualified(inp) else ""


def score_direct(inp: ScoringInput) -> ScoreResult:
    c: list[Component] = []
    n = len(inp.services)
    c.append(Component("service_fit", 25, _service_points(n, 25), inp.has_text,
                       f"Matches {n} approved service area(s): {', '.join(inp.services) or 'none'}." if inp.has_text else "No text to assess."))

    strong = [t for t, s in inp.signals if s == "strong"]
    moderate = [t for t, s in inp.signals if s == "moderate"]
    weak = [t for t, s in inp.signals if s == "weak"]
    if len(strong) >= 2:
        v, e = 30, f"Multiple explicit buying signals: {', '.join(strong)}."
    elif strong:
        v, e = 24 + min(6, 3 * len(moderate)), f"Explicit buying signal: {strong[0]}" + (f" plus {', '.join(moderate)}" if moderate else "") + "."
    elif moderate:
        v, e = 15, f"Moderate signal(s): {', '.join(moderate)}."
    elif weak:
        v, e = 6, f"Only weak signal(s): {', '.join(weak)} (e.g. employee hiring, not an external project)."
    else:
        v, e = 0, "No buying signal found in the evidence (negative finding)."
    c.append(Component("buying_signal", 30, v, inp.has_text, e if inp.has_text else "No text to assess."))

    pts, notes = 0.0, []
    if inp.budget_text:
        pts += 6
        notes.append(f"budget stated ({inp.budget_text})")
    if inp.description_length > 300:
        pts += 4
        notes.append("detailed description")
    if inp.scope_detail_terms or inp.deadline:
        pts += 5
        notes.append("timeline/deliverables mentioned")
    c.append(Component("business_scope", 15, pts, inp.has_text, ("Scope evidence: " + ", ".join(notes) + ".") if notes else "Scope, budget and timeline not stated."))

    if inp.contacts_verified:
        c.append(Component("verified_contact_route", 10, 10, True, f"{inp.contacts_verified} verified public contact route(s)."))
    elif inp.contacts_unverified:
        c.append(Component("verified_contact_route", 10, 4, True, "Only unverified/platform contact route (e.g. reply on the public thread)."))
    elif inp.research_done:
        c.append(Component("verified_contact_route", 10, 0, True, "Research found no public contact route (negative finding)."))
    else:
        c.append(Component("verified_contact_route", 10, 0, False, "Contact route not researched yet (unknown)."))

    if inp.vendor_negative and not inp.vendor_positive:
        c.append(Component("external_vendor_likelihood", 10, 2, True, f"Indicators against external vendors: {', '.join(inp.vendor_negative)}."))
    elif inp.vendor_positive:
        v = 10 if len(inp.vendor_positive) >= 2 else 6
        if inp.vendor_negative:
            v -= 3
        c.append(Component("external_vendor_likelihood", 10, v, True, f"External-vendor indicators: {', '.join(inp.vendor_positive)}" + (f"; against: {', '.join(inp.vendor_negative)}" if inp.vendor_negative else "") + "."))
    else:
        c.append(Component("external_vendor_likelihood", 10, 0, False, "No evidence either way about engaging external vendors (unknown)."))

    c.append(_evidence_component(inp))
    return ScoreResult(ScoreType.DIRECT, c, _is_disqualified(inp), explanation=_summary("Direct client", c) + _dq_note(inp))


def _evidence_component(inp: ScoringInput) -> Component:
    if inp.evidence_count == 0:
        return Component("evidence_confidence", 10, 0, True, "No preserved evidence (negative finding).")
    pts = 4 if inp.evidence_count == 1 else 6
    notes = [f"{inp.evidence_count} evidence item(s)"]
    if inp.published_at and inp.now:
        age = (inp.now - inp.published_at).days
        if age <= 30:
            pts += 3
            notes.append(f"published {age} day(s) ago")
        elif age <= 90:
            pts += 1
            notes.append(f"published {age} days ago")
        else:
            notes.append(f"stale ({age} days old)")
    else:
        notes.append("publication date unknown")
    if inp.classification_confidence >= 0.7:
        pts += 1
        notes.append("high classification confidence")
    return Component("evidence_confidence", 10, pts, True, ", ".join(notes) + ".")


ELIGIBILITY_POINTS = {
    EligibilityOutcome.ELIGIBLE.value: 25,
    EligibilityOutcome.POTENTIALLY_ELIGIBLE.value: 15,
    EligibilityOutcome.PARTNER_ROUTE.value: 10,
    EligibilityOutcome.UNCLEAR.value: 5,
    EligibilityOutcome.NOT_ELIGIBLE.value: 0,
}


def score_vendor(inp: ScoringInput) -> ScoreResult:
    c: list[Component] = []
    vendor_cats = {Category.VENDOR_ONBOARDING.value, Category.SUBCONTRACTING.value, Category.IMPLEMENTATION_PARTNERSHIP.value}
    public_cats = {Category.GOVERNMENT_TENDER.value, Category.PRIVATE_PROCUREMENT.value}
    if inp.accepts_external_vendors is True or inp.category in vendor_cats:
        c.append(Component("external_partner_acceptance", 20, 20, True, "Evidence that external vendors/partners are accepted."))
    elif inp.category in public_cats:
        c.append(Component("external_partner_acceptance", 20, 15, True, "Open public procurement accepts external bidders (subject to eligibility)."))
    elif inp.accepts_external_vendors is False:
        c.append(Component("external_partner_acceptance", 20, 0, True, "Evidence that external vendors are NOT accepted."))
    else:
        c.append(Component("external_partner_acceptance", 20, 0, False, "Unknown whether external vendors are accepted."))

    n = len(inp.services)
    c.append(Component("technical_fit", 20, _service_points(n, 20), inp.has_text, f"Matches {n} approved service area(s)."))

    outcome = inp.eligibility_outcome
    if outcome in ELIGIBILITY_POINTS:
        c.append(Component("eligibility", 25, ELIGIBILITY_POINTS[outcome], True, f"Project eligibility outcome: {outcome}."))
    else:
        c.append(Component("eligibility", 25, 0, False, "Eligibility unknown — no requirements identified (not treated as satisfied)."))

    explicit_request = any(st in ("strong", "moderate") for _, st in inp.signals)
    active = (
        inp.category in public_cats
        or (inp.category in (Category.SUBCONTRACTING.value, Category.DIRECT_SOFTWARE_PROJECT.value) and explicit_request)
        or (inp.deadline is not None and (inp.now is None or inp.deadline >= inp.now))
    )
    if active:
        c.append(Component("active_project_evidence", 15, 15, True, "Evidence of a currently active project/requirement."))
    elif inp.category in vendor_cats:
        c.append(Component("active_project_evidence", 15, 5, True, "Programme/registration only; no specific active project evidenced."))
    else:
        c.append(Component("active_project_evidence", 15, 0, False, "No active project evidence (unknown)."))

    if inp.vendor_portal_found:
        c.append(Component("onboarding_accessibility", 10, 10, True, "Public vendor onboarding/registration route found."))
    elif inp.contacts_verified:
        c.append(Component("onboarding_accessibility", 10, 5, True, "Verified contact route, but no self-serve onboarding page."))
    else:
        c.append(Component("onboarding_accessibility", 10, 0, inp.research_done, "No onboarding route found." if inp.research_done else "Onboarding route not researched yet."))

    pts, notes, known = 0.0, [], False
    if inp.budget_text:
        pts += 4; notes.append(f"budget stated ({inp.budget_text})"); known = True
    if inp.country == "India":
        pts += 3; notes.append("domestic (India) engagement"); known = True
    if inp.remote_ok:
        pts += 3; notes.append("remote delivery possible"); known = True
    c.append(Component("commercial_suitability", 10, pts, known, ("; ".join(notes) + ".") if notes else "Commercial terms unknown."))
    return ScoreResult(ScoreType.VENDOR, c, _is_disqualified(inp), explanation=_summary("Vendor/subcontracting", c) + _dq_note(inp))


def score_chain(inp: ScoringInput) -> ScoreResult:
    c: list[Component] = []
    rel = inp.confirmed_relationships
    partner = rel.get("partner_programme", 0) + rel.get("implementation_partner", 0)
    if partner:
        c.append(Component("verified_partner_programme", 30, 30, True, f"{partner} confirmed partner programme relationship(s)."))
    elif inp.hypothesis_relationships:
        c.append(Component("verified_partner_programme", 30, 0, False, f"{inp.hypothesis_relationships} unconfirmed hypothesis/hypotheses — not scored until verified."))
    else:
        c.append(Component("verified_partner_programme", 30, 0, False, "No partner programme evidence (unknown)."))

    k = inp.org_opportunity_count
    if k >= 3:
        c.append(Component("recurring_project_demand", 25, 25, True, f"Organisation has {k} distinct opportunities on record."))
    elif k == 2:
        c.append(Component("recurring_project_demand", 25, 15, True, "Organisation has 2 distinct opportunities on record."))
    else:
        c.append(Component("recurring_project_demand", 25, 0, False, "Only one opportunity on record; recurrence unknown."))

    cust = sum(rel.get(t, 0) for t in ("customer_of", "vendor_of", "contractor_for", "awarded_contract", "announced_project"))
    if cust:
        c.append(Component("relevant_customer_relationships", 20, {1: 10, 2: 15}.get(cust, 20), True, f"{cust} confirmed customer/contract relationship(s)."))
    else:
        c.append(Component("relevant_customer_relationships", 20, 0, False, "No confirmed customer relationships (unknown)."))

    if inp.confirmed_repeat_links:
        c.append(Component("repeat_work_potential", 15, 15, True, "Confirmed repeat/related project link."))
    elif inp.repeat_terms:
        c.append(Component("repeat_work_potential", 15, 8, True, f"Ongoing-work indicators: {', '.join(inp.repeat_terms)}."))
    else:
        c.append(Component("repeat_work_potential", 15, 0, False, "No repeat-work indicators (unknown)."))

    if rel.get("referral_route", 0):
        c.append(Component("authorised_introduction_route", 10, 10, True, "Confirmed authorised introduction/referral route."))
    else:
        c.append(Component("authorised_introduction_route", 10, 0, False, "No authorised introduction route recorded (unknown)."))
    return ScoreResult(ScoreType.CHAIN, c, _is_disqualified(inp), explanation=_summary("Opportunity chain", c) + _dq_note(inp))


def _summary(label: str, comps: list[Component]) -> str:
    total = round(sum(x.value for x in comps), 1)
    unknown = [x.name for x in comps if not x.known]
    s = f"{label} score {total}/100 from " + ", ".join(f"{x.name} {x.value}/{x.max}" for x in comps) + "."
    if unknown:
        s += f" Unknown (scored 0, not negative): {', '.join(unknown)}."
    return s


def score_all(inp: ScoringInput) -> list[ScoreResult]:
    return [score_direct(inp), score_vendor(inp), score_chain(inp)]


PIPELINE_PRIMARY = {Pipeline.DIRECT.value: ScoreType.DIRECT, Pipeline.VENDOR.value: ScoreType.VENDOR, Pipeline.CHAIN.value: ScoreType.CHAIN}


def compute_priority(pipeline: str, category: str, results: list[ScoreResult], country: str | None, region: str | None, priorities: list[dict[str, Any]]) -> float:
    """Ranking priority: the pipeline's primary effective score plus an explicit-geography bonus."""
    if category in (Category.IRRELEVANT.value,) or any(r.disqualified for r in results):
        return 0.0
    by_type = {r.score_type: r.effective_total for r in results}
    primary = PIPELINE_PRIMARY.get(pipeline)
    base = by_type[primary] if primary else max(by_type.values())
    bonus = 0
    for p in priorities or []:
        if p.get("level") == "region" and region and p.get("match", "").lower() == region.lower():
            bonus = max(bonus, int(p.get("bonus", 0)))
        elif p.get("level") == "country" and country and p.get("match", "").lower() == country.lower():
            bonus = max(bonus, int(p.get("bonus", 0)))
    return round(base + bonus, 1)
