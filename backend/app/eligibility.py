"""Deterministic eligibility engine.

- Requirements are extracted by rules (or entered manually / from documents) and evaluated
  against the REAL business profile.
- Unknown is never treated as satisfied.
- Mandatory failures override scores (see scoring.py).
- Vendor-registration eligibility and project eligibility are assessed separately.
- AI never decides mandatory legal eligibility.
- Output is decision support, not legal or tax advice.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.enums import EligibilityOutcome as O
from app.enums import EligibilityScope, RequirementKey as K, RequirementStatus as S
from app.profile import BusinessProfile

ENGINE_VERSION = "1.0.0"
DISCLAIMER = "Decision support only — not legal or tax advice. Confirm with the buyer and a qualified adviser."

# Requirements whose failure a larger prime/partner could cover.
CAPACITY_KEYS = {
    K.MIN_TURNOVER, K.PRIOR_EXPERIENCE, K.SIMILAR_WORK_CERTIFICATES, K.WORKFORCE,
    K.TECHNICAL_CERTIFICATIONS, K.SECURITY_CERTIFICATIONS, K.GST, K.TAX_INVOICING,
    K.LEGAL_ENTITY, K.PROPRIETORSHIP_ACCEPTANCE, K.INSURANCE,
}
# Failures no partner arrangement can fix for Inferago.
ABSOLUTE_KEYS = {K.COUNTRY_RESTRICTION, K.INDIA_PROVIDERS_ACCEPTED, K.PROJECT_RESTRICTION}


@dataclass
class ExtractedRequirement:
    key: K
    text: str
    mandatory: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    page_reference: str | None = None
    scope: EligibilityScope = EligibilityScope.PROJECT


@dataclass
class RequirementEvaluation:
    key: str
    status: S
    reason: str
    mandatory: bool
    text: str
    page_reference: str | None = None
    clarification: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "status": self.status.value, "reason": self.reason, "mandatory": self.mandatory,
            "text": self.text, "page_reference": self.page_reference,
        }


@dataclass
class AssessmentResult:
    scope: EligibilityScope
    outcome: O
    reason: str
    satisfied: list[dict[str, Any]]
    missing: list[dict[str, Any]]
    mandatory_failures: list[dict[str, Any]]
    clarifications: list[str]
    next_action: str
    evidence: list[dict[str, Any]]


# ---------------------------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------------------------

_OPTIONAL_WORDS = re.compile(r"\b(preferred|desirable|advantage|nice to have|bonus|optional|plus)\b", re.I)
_CERT_CONTEXT = re.compile(r"\b(must|shall|required|mandatory|should (have|hold|possess)|certified|accredited|holds?|valid)\b", re.I)
_EXEMPT_RE = re.compile(r"exempt(ed|ion)?[^.\n]{0,120}\b(MSEs?|MSMEs?|micro and small|start-?ups?|udyam|nsic)\b|\b(MSEs?|MSMEs?|start-?ups?)\b[^.\n]{0,80}exempt", re.I)


def parse_inr_amount(s: str) -> float | None:
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|cr\b|l\b)?", s, re.I)
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    if unit.startswith(("lakh", "lac", "l")):
        num *= 100_000
    elif unit.startswith(("crore", "cr")):
        num *= 10_000_000
    return num


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;:])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


RULES: list[tuple[K, re.Pattern]] = [
    (K.MIN_TURNOVER, re.compile(r"\bturnover\b", re.I)),
    (K.PRIOR_EXPERIENCE, re.compile(r"(prior|past|previous|minimum)\s+(\d+\s+)?(years?\s+of\s+)?experience|experience\s+(of|in)\s+(executing|completing|similar)|(\d+)\+?\s+years?\s+(of\s+)?experience|have\s+(successfully\s+)?(executed|completed)\s+(at least\s+)?(\w+\s+)?similar", re.I)),
    (K.SIMILAR_WORK_CERTIFICATES, re.compile(r"(work\s+(order|completion)\s+certificates?|completion\s+certificates?|similar\s+work\s+certificates?|client\s+certificates?)", re.I)),
    (K.WORKFORCE, re.compile(r"(minimum|at least)\s+(of\s+)?(\d+)\s+(full[- ]time\s+)?(employees|staff|engineers|developers|technical\s+(staff|resources|personnel)|resources|manpower)|(\d+)\+?\s+(employees|staff)\s+on\s+(its\s+)?(payroll|rolls?)", re.I)),
    (K.TECHNICAL_CERTIFICATIONS, re.compile(r"\b(CMMI(\s+level\s+\d)?|ISO\s*9001|ISO\s*20000)\b", re.I)),
    (K.SECURITY_CERTIFICATIONS, re.compile(r"\b(ISO(/IEC)?\s*27001|SOC\s*2|CERT-In\s+empanel+ed|PCI[- ]DSS)\b", re.I)),
    (K.INSURANCE, re.compile(r"(professional\s+indemnity|liability\s+insurance|insurance\s+(cover|policy))", re.I)),
    (K.EMD, re.compile(r"\b(EMD|earnest\s+money(\s+deposit)?|bid\s+security)\b", re.I)),
    (K.DIGITAL_SIGNATURE, re.compile(r"(digital\s+signature|\bDSC\b|class\s*(II|III|2|3)\s+(digital\s+)?certificate)", re.I)),
    (K.REGISTRATION_FEE, re.compile(r"(registration\s+fee|tender\s+fee|document\s+fee|cost\s+of\s+(the\s+)?tender\s+document)", re.I)),
    (K.GST, re.compile(r"\b(GSTIN|GST\s+(registration|number|certificate|registered))\b", re.I)),
    (K.PAN, re.compile(r"\bPAN\s+(card|number|no\.?|details)\b", re.I)),
    (K.UDYAM_MSME, re.compile(r"\b(udyam|MSME\s+(certificate|registration)|NSIC)\b", re.I)),
    (K.TAX_INVOICING, re.compile(r"\b(GST\s+invoice|tax\s+invoice|invoices?\s+with\s+GST)\b", re.I)),
    (K.LEGAL_ENTITY, re.compile(r"(registered|incorporated)\s+(company|firm)\s+(in|under)|companies\s+act|private\s+limited\s+compan|public\s+limited\s+compan|\bLLP\b|registered\s+legal\s+entity|must\s+be\s+a\s+(registered\s+)?(company|corporation|legal\s+entity)", re.I)),
    (K.PROPRIETORSHIP_ACCEPTANCE, re.compile(r"proprietor(ship)?", re.I)),
    (K.SUBCONTRACTING_PERMISSION, re.compile(r"sub-?contract(ing)?\s+(is\s+|shall\s+be\s+|will\s+be\s+)?(not\s+)?(permitted|allowed|prohibited)", re.I)),
    (K.CONSORTIUM_PERMISSION, re.compile(r"(consortium|joint\s+venture|\bJV\b)[^.\n]{0,40}(not\s+)?(permitted|allowed|prohibited|eligible)", re.I)),
    (K.VENDOR_REGISTRATION, re.compile(r"(registered\s+(vendor|supplier|on\s+GeM)|vendor\s+registration\s+(is\s+)?(mandatory|required)|must\s+be\s+registered\s+(on|with)\s+(the\s+)?(portal|GeM|CPPP))", re.I)),
    (K.COUNTRY_RESTRICTION, re.compile(r"(indian\s+(bidders|firms|companies|vendors)\s+only|only\s+indian\s+(bidders|firms|companies)|foreign\s+(bidders|firms|companies)\s+(are\s+)?not\s+(allowed|eligible|permitted)|bidders?\s+(must|should)\s+be\s+(registered|based|located)\s+in\s+([A-Z][a-zA-Z ]+))", re.I)),
    (K.INDIA_PROVIDERS_ACCEPTED, re.compile(r"(no\s+offshore|offshore\s+(teams?\s+)?(welcome|accepted|ok)|india[- ]based\s+(teams?|developers?|vendors?)\s+(welcome|accepted|not\s+accepted))", re.I)),
]


def _params_for(key: K, sentence: str) -> dict[str, Any]:
    p: dict[str, Any] = {}
    if _EXEMPT_RE.search(sentence):
        p["msme_exemption_mentioned"] = True
    if key == K.MIN_TURNOVER:
        m = re.search(r"((?:Rs\.?|INR|₹)\s?[\d,]+(?:\.\d+)?\s*(?:lakhs?|lacs?|crores?|cr|l)?\b|[\d,]+(?:\.\d+)?\s*(?:lakhs?|lacs?|crores?))", sentence, re.I)
        if m:
            p["amount_text"] = m.group(0).strip()
            p["amount_inr"] = parse_inr_amount(m.group(0))
    elif key == K.WORKFORCE:
        m = re.search(r"(\d+)", sentence)
        if m:
            p["min_count"] = int(m.group(1))
    elif key in (K.EMD, K.REGISTRATION_FEE):
        m = re.search(r"((?:Rs\.?|INR|₹)\s?[\d,]+(?:\.\d+)?\s*(?:lakhs?|crores?)?)", sentence, re.I)
        if m:
            p["amount_text"] = m.group(0).strip()
    elif key == K.PROPRIETORSHIP_ACCEPTANCE:
        if re.search(r"proprietor(ship)?\s+(firms?\s+|concerns?\s+)?(are\s+|is\s+)?not\s+(eligible|allowed|permitted)|excluding\s+proprietor|other\s+than\s+(sole\s+)?proprietor", sentence, re.I):
            p["accepted"] = False
        elif re.search(r"proprietor(ship)?\s+(firms?\s+|concerns?\s+)?(are\s+|is\s+)?(also\s+)?(eligible|allowed|permitted|may\s+(apply|bid))|(company|firm|llp|partnership)[^.]{0,40}proprietor", sentence, re.I):
            p["accepted"] = True
    elif key == K.LEGAL_ENTITY:
        types = []
        for label, pat in [("company", r"compan(y|ies)|corporation|companies\s+act"), ("llp", r"\bLLP\b"), ("partnership", r"partnership"), ("proprietorship", r"proprietor")]:
            if re.search(pat, sentence, re.I):
                types.append(label)
        p["accepted_types"] = types
    elif key in (K.SUBCONTRACTING_PERMISSION, K.CONSORTIUM_PERMISSION):
        neg = re.search(r"\bnot\s+(permitted|allowed|eligible)|prohibited", sentence, re.I)
        p["allowed"] = not neg
    elif key == K.COUNTRY_RESTRICTION:
        if re.search(r"indian|foreign\s+(bidders|firms|companies)\s+(are\s+)?not", sentence, re.I):
            p["allowed_countries"] = ["India"]
        else:
            m = re.search(r"in\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)", sentence)
            if m:
                p["allowed_countries"] = [m.group(1).strip()]
    elif key == K.INDIA_PROVIDERS_ACCEPTED:
        p["accepted"] = not re.search(r"no\s+offshore|not\s+accepted", sentence, re.I)
    elif key in (K.TECHNICAL_CERTIFICATIONS, K.SECURITY_CERTIFICATIONS):
        p["names"] = list({m.group(0).strip() for m in RULES_DICT[key].finditer(sentence)})
    return p


RULES_DICT = dict(RULES)


def extract_requirements(pages: list[tuple[str | None, str]], *, default_scope=EligibilityScope.PROJECT) -> list[ExtractedRequirement]:
    """Extract eligibility requirements from (page_reference, text) chunks.

    Each requirement keeps the sentence it came from and its page reference. Nothing is
    invented: if no sentence matches, no requirement is produced.
    """
    out: list[ExtractedRequirement] = []
    seen: set[tuple[str, str]] = set()
    for page_ref, text in pages:
        for sentence in _sentences(text or ""):
            for key, pat in RULES:
                if not pat.search(sentence):
                    continue
                if key in (K.TECHNICAL_CERTIFICATIONS, K.SECURITY_CERTIFICATIONS) and not _CERT_CONTEXT.search(sentence):
                    continue  # e.g. "help us achieve SOC2" is work, not a vendor requirement
                if key == K.PROPRIETORSHIP_ACCEPTANCE and not re.search(r"eligible|allowed|permitted|apply|bid|excluding|other than", sentence, re.I):
                    continue
                sig = (key.value, sentence[:160].lower())
                if sig in seen:
                    continue
                seen.add(sig)
                scope = EligibilityScope.VENDOR_REGISTRATION if key == K.VENDOR_REGISTRATION else default_scope
                out.append(
                    ExtractedRequirement(
                        key=key,
                        text=sentence[:600],
                        mandatory=not _OPTIONAL_WORDS.search(sentence),
                        parameters=_params_for(key, sentence),
                        page_reference=page_ref,
                        scope=scope,
                    )
                )
    return out


def requirements_from_classification(restrictions: list[tuple[str, str, bool]], worldwide: bool) -> list[ExtractedRequirement]:
    """Turn explicit geography restrictions found by the classifier into requirements."""
    reqs = []
    for country, excerpt, hard in restrictions:
        reqs.append(ExtractedRequirement(K.COUNTRY_RESTRICTION, excerpt, hard, {"allowed_countries": country.split("|")}))
    if worldwide and not restrictions:
        reqs.append(ExtractedRequirement(K.INDIA_PROVIDERS_ACCEPTED, "Post states worldwide/anywhere eligibility", True, {"accepted": True}))
    return reqs


# ---------------------------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------------------------


def evaluate_requirement(key: str, text: str, mandatory: bool, params: dict[str, Any], profile: BusinessProfile, page_reference: str | None = None) -> RequirementEvaluation:
    def ev(status: S, reason: str, clarification: str | None = None) -> RequirementEvaluation:
        return RequirementEvaluation(key, status, reason, mandatory, text, page_reference, clarification)

    exempt = bool(params.get("msme_exemption_mentioned"))
    try:
        k = K(key)
    except ValueError:
        return ev(S.UNKNOWN, f"Unrecognised requirement type '{key}'", "Review this requirement manually.")

    if k == K.COUNTRY_RESTRICTION:
        allowed = params.get("allowed_countries")
        if not allowed:
            return ev(S.CLARIFY, "Country restriction present but allowed countries unclear", "Which countries may bidders/providers be based in?")
        if profile.country in allowed:
            return ev(S.SATISFIED, f"{profile.country} is within the allowed countries {allowed}")
        return ev(S.FAILED, f"Restricted to {allowed}; Inferago is based in {profile.country}")
    if k == K.INDIA_PROVIDERS_ACCEPTED:
        acc = params.get("accepted")
        if acc is True:
            return ev(S.SATISFIED, "India-based / offshore providers accepted")
        if acc is False:
            return ev(S.FAILED, "India-based / offshore providers not accepted")
        return ev(S.CLARIFY, "Acceptance of India-based providers not stated", "Do you accept India-based delivery teams?")
    if k == K.LEGAL_ENTITY:
        types = params.get("accepted_types") or []
        if "proprietorship" in types:
            return ev(S.SATISFIED, "Sole proprietorships are among accepted entity types")
        if types:
            return ev(S.FAILED, f"Requires entity type {types}; Inferago is a sole proprietorship")
        return ev(S.CLARIFY, "Legal entity requirement unclear", "Are sole proprietorships eligible?")
    if k == K.PROPRIETORSHIP_ACCEPTANCE:
        acc = params.get("accepted")
        if acc is True:
            return ev(S.SATISFIED, "Proprietorship firms explicitly accepted")
        if acc is False:
            return ev(S.FAILED, "Proprietorship firms explicitly excluded")
        return ev(S.CLARIFY, "Proprietorship acceptance not clear", "Are sole proprietorship firms eligible to bid?")
    if k == K.GST:
        if profile.gst_registered:
            return ev(S.SATISFIED, "GST registered")
        return ev(S.FAILED, "GST registration required; Inferago is not GST registered", "Is GST registration mandatory at bid stage or only at invoicing?")
    if k == K.TAX_INVOICING:
        if profile.gst_registered:
            return ev(S.SATISFIED, "Can issue GST invoices")
        if re.search(r"gst", text, re.I):
            return ev(S.FAILED, "GST invoices required; Inferago is not GST registered")
        return ev(S.CLARIFY, "Tax invoicing requirements need confirmation", "What invoicing format is required?")
    if k == K.PAN:
        if profile.pan_available:
            return ev(S.SATISFIED, "PAN available (proprietor-linked)", "Confirm a proprietor-linked PAN is acceptable.")
        return ev(S.FAILED, "PAN not available")
    if k == K.UDYAM_MSME:
        if profile.udyam_msme_registered:
            return ev(S.SATISFIED, "Udyam/MSME registered")
        return ev(S.FAILED, "Udyam/MSME registration required")
    if k == K.MIN_TURNOVER:
        amount = params.get("amount_inr")
        if profile.annual_turnover_inr is not None and amount is not None:
            if profile.annual_turnover_inr >= amount:
                return ev(S.SATISFIED, f"Documented turnover ≥ {params.get('amount_text')}")
            return ev(S.FAILED, f"Requires turnover {params.get('amount_text')}; documented turnover is lower")
        if exempt:
            return ev(S.CLARIFY, "Turnover requirement with an MSME/startup exemption mentioned", "Does the MSME exemption apply to this turnover criterion for services?")
        if amount is None and not re.search(r"\d", text):
            return ev(S.CLARIFY, "Turnover requirement mentioned without a clear threshold", "What is the minimum turnover threshold?")
        return ev(S.FAILED, f"Requires minimum turnover {params.get('amount_text') or ''}; no turnover is documented in the profile".strip())
    if k == K.PRIOR_EXPERIENCE:
        if not re.search(r"similar (projects?|works?|assignments?)|executed|completed|work orders?|credentials|client references|past performance", text, re.I):
            return ev(S.CLARIFY, "Individual skill/experience requirement; not a corporate track-record criterion", "Owner to confirm whether the team's individual experience meets this.")
        if profile.corporate_project_credentials or profile.completed_projects_documented > 0:
            return ev(S.CLARIFY, "Some project history documented; confirm it meets the criterion", "Does our documented work qualify as similar experience?")
        if exempt:
            return ev(S.CLARIFY, "Experience requirement with MSME/startup exemption mentioned", "Does the exemption apply to prior experience?")
        return ev(S.FAILED, "Prior project experience required; no corporate project credentials established")
    if k == K.SIMILAR_WORK_CERTIFICATES:
        if profile.similar_work_certificates:
            return ev(S.SATISFIED, "Similar work certificates available")
        return ev(S.FAILED, "Similar-work/completion certificates required; none held")
    if k == K.WORKFORCE:
        n = params.get("min_count")
        if n is None:
            return ev(S.CLARIFY, "Workforce requirement unclear", "What minimum team size is required?")
        if profile.dedicated_employees >= n:
            return ev(S.SATISFIED, f"Workforce ≥ {n}")
        return ev(S.FAILED, f"Requires {n} staff; Inferago has {profile.dedicated_employees} dedicated employees (founder-led)")
    if k in (K.TECHNICAL_CERTIFICATIONS, K.SECURITY_CERTIFICATIONS):
        held = profile.technical_certifications if k == K.TECHNICAL_CERTIFICATIONS else profile.security_certifications
        names = params.get("names") or []
        if names and all(any(n.lower() in h.lower() for h in held) for n in names):
            return ev(S.SATISFIED, f"Holds {names}")
        return ev(S.FAILED, f"Requires certification {names or ''}; none held".strip())
    if k == K.INSURANCE:
        if profile.insurance:
            return ev(S.CLARIFY, "Some insurance held; confirm cover type", "What insurance cover and amount is required, and at which stage?")
        return ev(S.CLARIFY, "Insurance cover required; none currently held", "Is insurance needed at bid stage or only on award?")
    if k == K.EMD:
        if exempt and profile.udyam_msme_registered:
            return ev(S.CLARIFY, "EMD with MSME exemption mentioned; Inferago is Udyam registered", "Confirm the MSE EMD exemption applies to this tender category.")
        return ev(S.CLARIFY, f"EMD / bid security payable {params.get('amount_text') or ''}".strip(), "Confirm EMD amount, mode and refund terms.")
    if k == K.DIGITAL_SIGNATURE:
        if profile.digital_signature_certificate:
            return ev(S.SATISFIED, "Digital signature certificate available")
        return ev(S.CLARIFY, "Digital signature certificate (DSC) required; not recorded in profile", "Obtain a Class 3 DSC before the bid deadline?")
    if k == K.REGISTRATION_FEE:
        return ev(S.CLARIFY, f"Registration/tender fee {params.get('amount_text') or ''}".strip(), "Confirm fee amount and whether MSMEs are exempt.")
    if k == K.SUBCONTRACTING_PERMISSION:
        if params.get("allowed") is True:
            return ev(S.SATISFIED, "Subcontracting permitted (enables partner route)")
        if params.get("allowed") is False:
            return ev(S.CLARIFY, "Subcontracting prohibited — no partner route via subcontract", None)
        return ev(S.CLARIFY, "Subcontracting rules not stated", "Is subcontracting permitted?")
    if k == K.CONSORTIUM_PERMISSION:
        if params.get("allowed") is True:
            return ev(S.SATISFIED, "Consortium/JV bids permitted (enables partner route)")
        if params.get("allowed") is False:
            return ev(S.CLARIFY, "Consortium/JV bids not permitted", None)
        return ev(S.CLARIFY, "Consortium rules not stated", "Are consortium bids permitted?")
    if k == K.VENDOR_REGISTRATION:
        if params.get("registered") is True:
            return ev(S.SATISFIED, "Already registered as vendor")
        return ev(S.CLARIFY, "Vendor/portal registration required before participation", "What documents are needed for vendor registration?")
    if k == K.PROJECT_RESTRICTION:
        if params.get("satisfied") is True:
            return ev(S.SATISFIED, "Project restriction reviewed and satisfied by owner")
        if params.get("satisfied") is False:
            return ev(S.FAILED, "Project-specific restriction not met")
        return ev(S.CLARIFY, "Project-specific restriction needs review", "Review this restriction manually.")
    return ev(S.UNKNOWN, "No evaluation rule", "Review manually.")


NEXT_ACTIONS = {
    O.ELIGIBLE: "Proceed to research and outreach preparation (human approval required before contact).",
    O.POTENTIALLY_ELIGIBLE: "Resolve the clarification questions with the buyer before investing in a bid.",
    O.NOT_ELIGIBLE: "Do not pursue directly. Archive, or look for an opportunity chain via the winning vendor.",
    O.PARTNER_ROUTE: "Look for an eligible prime vendor/partner and propose a subcontract or consortium role.",
    O.UNCLEAR: "Gather the missing requirement details (tender document, buyer clarification) and re-assess.",
    O.UNKNOWN: "No requirements identified yet. Import the tender/vendor document or add requirements manually.",
}


def assess(requirements: list[dict[str, Any]], profile: BusinessProfile, scope: EligibilityScope) -> AssessmentResult:
    """Assess a list of requirement dicts (key, text, mandatory, parameters, page_reference, scope, evidence_id)."""
    reqs = [r for r in requirements if r.get("scope", "project") == scope.value]
    if not reqs:
        return AssessmentResult(
            scope, O.UNKNOWN,
            "No eligibility requirements identified for this scope. Unknown requirements are not treated as satisfied. " + DISCLAIMER,
            [], [], [], [], NEXT_ACTIONS[O.UNKNOWN], [],
        )

    evals = [
        evaluate_requirement(r["key"], r.get("text", ""), bool(r.get("mandatory", True)), r.get("parameters") or {}, profile, r.get("page_reference"))
        for r in reqs
    ]
    satisfied = [e.as_dict() for e in evals if e.status == S.SATISFIED]
    failures = [e for e in evals if e.status == S.FAILED and e.mandatory]
    soft_failures = [e for e in evals if e.status == S.FAILED and not e.mandatory]
    missing = [e.as_dict() for e in evals if e.status in (S.UNKNOWN, S.CLARIFY)] + [e.as_dict() for e in soft_failures]
    clarifications = [e.clarification for e in evals if e.clarification]
    evidence = [
        {"key": r["key"], "text": r.get("text", ""), "page_reference": r.get("page_reference"), "evidence_id": r.get("evidence_id")}
        for r in reqs
    ]

    params_by_key = {r["key"]: (r.get("parameters") or {}) for r in reqs}
    sub_allowed = params_by_key.get(K.SUBCONTRACTING_PERMISSION.value, {}).get("allowed")
    cons_allowed = params_by_key.get(K.CONSORTIUM_PERMISSION.value, {}).get("allowed")

    if failures:
        fail_keys = {K(e.key) for e in failures}
        partner_blocked = (sub_allowed is False and cons_allowed is not True) or bool(fail_keys & ABSOLUTE_KEYS)
        if not partner_blocked and fail_keys <= CAPACITY_KEYS:
            outcome = O.PARTNER_ROUTE
            reason = "Mandatory capacity requirements are not met for a direct bid (" + ", ".join(sorted(k.value for k in fail_keys)) + "); a partner/prime arrangement may be possible."
        else:
            outcome = O.NOT_ELIGIBLE
            reason = "Mandatory requirement(s) not met: " + "; ".join(e.reason for e in failures)
    elif any(e.status in (S.CLARIFY, S.UNKNOWN) for e in evals) or soft_failures:
        outcome = O.POTENTIALLY_ELIGIBLE if satisfied else O.UNCLEAR
        reason = (
            f"{len(satisfied)} requirement(s) satisfied; {len(missing)} need clarification or are unknown. No mandatory failure identified."
            if satisfied else "Requirements identified but none could be confirmed as satisfied."
        )
    else:
        outcome = O.ELIGIBLE
        reason = f"All {len(satisfied)} identified requirement(s) are satisfied. Requirements not stated in the evidence remain unverified."

    return AssessmentResult(
        scope=scope,
        outcome=outcome,
        reason=reason + " " + DISCLAIMER,
        satisfied=satisfied,
        missing=missing,
        mandatory_failures=[e.as_dict() for e in failures],
        clarifications=list(dict.fromkeys(clarifications)),
        next_action=NEXT_ACTIONS[outcome],
        evidence=evidence,
    )
