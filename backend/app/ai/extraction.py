"""AI-assisted extraction with verbatim-evidence verification.

AI is used only to LOCATE information in collected text. Every value it returns must come with a
verbatim quote that is found in the source text (after whitespace normalisation); anything that
cannot be verified is discarded. Eligibility is still decided by the deterministic rules in
`app.eligibility`: AI-located requirement clauses are passed through `extract_requirements`, so the
rule engine — not the model — decides what each clause means.

Every function returns an empty result when AI is unavailable or fails (deterministic fallback).
"""

import re

from pydantic import BaseModel, Field

from app.ai.openrouter import AIUnavailable, OpenRouterClient  # ClaudeClient has the same interface
from app.classification import ClassificationResult
from app.enums import CATEGORY_PIPELINE, Category
from app.profile import SERVICE_KEYS

# --- Verification helpers -----------------------------------------------------------------------


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def quote_in(quote: str, text: str) -> bool:
    q = _norm(quote)
    return len(q) >= 8 and q in _norm(text)


def locate_quote(quote: str, pages: list[tuple[str | None, str]], hint: str | None = None) -> str | None | bool:
    """Return the page reference containing `quote` (hint page first), or False if not found."""
    ordered = sorted(pages, key=lambda p: p[0] != hint)
    for ref, text in ordered:
        if quote_in(quote, text):
            return ref
    return False


def _pages_for_prompt(pages: list[tuple[str | None, str]], limit: int = 22000) -> str:
    out, used = [], 0
    for ref, text in pages:
        chunk = f"[page {ref or '-'}]\n{text}\n"
        if used + len(chunk) > limit:
            out.append(chunk[: max(0, limit - used)])
            break
        out.append(chunk)
        used += len(chunk)
    return "\n".join(out)


# --- Document fields ----------------------------------------------------------------------------


class AIField(BaseModel):
    name: str
    value: str = Field(max_length=600)
    page_reference: str | None = None
    quote: str = Field(max_length=800)


class AIDocumentFields(BaseModel):
    fields: list[AIField] = Field(default_factory=list, max_length=30)


def ai_document_fields(ai: OpenRouterClient, pages: list[tuple[str | None, str]], wanted: list[str]) -> dict[str, tuple[str, str | None, str]]:
    """Find `wanted` tender fields. Returns {name: (value, page_reference, verified_quote)}."""
    if not wanted or not pages:
        return {}
    instruction = (
        "Extract these fields from the tender/RFP document if, and only if, the text states them: "
        + ", ".join(wanted)
        + ". For each field found return name (exactly one of the listed names), value (short), page_reference "
        "(the [page …] label it is on) and quote (an exact, verbatim sentence or line from the document that "
        "contains the value — copy it character for character). Omit fields that are not stated. Dates as written."
    )
    try:
        res = ai.complete_json("document_fields", instruction, _pages_for_prompt(pages), AIDocumentFields, max_tokens=1500)
    except AIUnavailable:
        return {}
    out: dict[str, tuple[str, str | None, str]] = {}
    for f in res.fields:
        if f.name not in wanted or f.name in out:
            continue
        ref = locate_quote(f.quote, pages, f.page_reference)
        if ref is False:
            continue  # quote not in the document → discard (possible hallucination)
        value_ok = _norm(f.value) in _norm(f.quote) or all(tok in _norm(f.quote) for tok in re.findall(r"[\w₹]+", _norm(f.value))[:6])
        if not value_ok:
            continue
        out[f.name] = (f.value.strip(), ref, re.sub(r"\s+", " ", f.quote).strip())
    return out


# --- Requirement clauses ------------------------------------------------------------------------


class AIClause(BaseModel):
    quote: str = Field(max_length=800)
    page_reference: str | None = None


class AIRequirementClauses(BaseModel):
    clauses: list[AIClause] = Field(default_factory=list, max_length=40)


def ai_requirement_clauses(ai: OpenRouterClient, pages: list[tuple[str | None, str]]) -> list[tuple[str | None, str]]:
    """Return verified (page_reference, clause) pairs stating bidder/vendor eligibility conditions."""
    if not pages:
        return []
    instruction = (
        "List every clause that states a condition a bidder/vendor must meet to be eligible or to submit: "
        "legal entity type, registration (GST, PAN, MSME/Udyam, portal), turnover, prior/similar experience, "
        "certificates, staff/workforce, insurance, EMD/bid security, fees, digital signature, country/location "
        "restrictions, consortium or subcontracting rules, exemptions. Return each as quote (exact verbatim text "
        "from the document, one sentence) and page_reference. Do not paraphrase. Do not include general policy "
        "text that does not impose a condition on the bidder."
    )
    try:
        res = ai.complete_json("requirement_clauses", instruction, _pages_for_prompt(pages), AIRequirementClauses, max_tokens=2500)
    except AIUnavailable:
        return []
    out: list[tuple[str | None, str]] = []
    for c in res.clauses:
        ref = locate_quote(c.quote, pages, c.page_reference)
        if ref is False:
            continue
        out.append((ref, re.sub(r"\s+", " ", c.quote).strip()))
    return out


# --- Classification refinement ------------------------------------------------------------------

REFINABLE = {Category.UNKNOWN, Category.WEAK_BUYING_SIGNAL}
AI_CATEGORIES = [c.value for c in Category]


class AIClassificationRefinement(BaseModel):
    category: str
    confidence: float = Field(ge=0, le=1)
    services: list[str] = Field(default_factory=list, max_length=5)
    evidence_quote: str = Field(max_length=500)
    rationale: str = Field(max_length=600)


def should_refine(cls: ClassificationResult) -> bool:
    return cls.method == "rules" and (cls.category in REFINABLE or (cls.category == Category.DIRECT_SOFTWARE_PROJECT and not cls.services))


def ai_refine_classification(ai: OpenRouterClient, title: str | None, text: str, cls: ClassificationResult) -> bool:
    """Refine an uncertain rule classification in place. Returns True if changed.

    Constraints: category must be a known value; services only from the approved list; the
    evidence quote must appear verbatim in the text; confidence capped at 0.65. Geography,
    restrictions and signals stay rule-derived.
    """
    full = f"{title or ''}\n{text}"
    instruction = (
        "Classify this post for a small Indian software services firm (services: "
        + "; ".join(f"{k} = {v}" for k, v in SERVICE_KEYS.items())
        + "). category must be one of: " + ", ".join(AI_CATEGORIES)
        + ". 'direct_software_project' = someone wants to pay an external developer/agency for work in those services; "
        "'irrelevant' = job seekers, self-promotion, unpaid, or out-of-scope work; 'unknown' if unclear. "
        "services: keys from the list that the request actually needs. evidence_quote: exact verbatim text from "
        "the post supporting the category."
    )
    try:
        res = ai.complete_json("classification_refine", instruction, full[:12000], AIClassificationRefinement, max_tokens=500)
    except AIUnavailable:
        return False
    if res.category not in AI_CATEGORIES or not quote_in(res.evidence_quote, full):
        return False
    new_cat = Category(res.category)
    services = [s for s in res.services if s in SERVICE_KEYS]
    changed = False
    if cls.category in REFINABLE and new_cat not in (Category.UNKNOWN, cls.category):
        cls.category = new_cat
        cls.pipeline = CATEGORY_PIPELINE[new_cat]
        cls.confidence = round(min(0.65, res.confidence), 2)
        changed = True
    new_services = [s for s in services if s not in cls.services]
    if new_services and cls.category not in (Category.IRRELEVANT, Category.UNKNOWN):
        cls.services = cls.services + new_services
        changed = True
    if changed:
        cls.method = "ai"
        cls.evidence = cls.evidence + [f"AI refinement ({ai.model_name}): {res.rationale[:300]} — quote: \"{res.evidence_quote[:200]}\""]
    return changed


class AIBudget:
    """Caps AI calls per source run so collection cost stays bounded."""

    def __init__(self, ai: OpenRouterClient | None, max_calls: int) -> None:
        self.ai = ai
        self.remaining = max_calls if ai else 0

    def take(self) -> OpenRouterClient | None:
        if self.ai is None or self.remaining <= 0:
            return None
        self.remaining -= 1
        return self.ai
