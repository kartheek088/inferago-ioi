"""Manual URL import and procurement document import workflows."""

import hashlib
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.extraction import ai_document_fields, ai_requirement_clauses
from app.ai.openrouter import AISummary, AIUnavailable, get_ai
from app.config import get_settings
from app.connectors.base import CollectedItem
from app.documents import ExtractedField, analyse_document, extract_html, parse_date
from app.eligibility import extract_requirements
from app.enums import Category
from app.evaluation import evaluate_opportunity
from app.http_client import SafeHttp
from app.models import EligibilityRequirement, Evidence, Opportunity, Source
from app.settings_store import get_setting
from app.normalize import canonical_url, truncate
from app.pipeline import IngestOutcome, ingest_item


def _source(db: Session, key: str) -> Source:
    src = db.scalar(select(Source).where(Source.key == key))
    if not src:
        raise LookupError(f"Source '{key}' missing — run seeding")
    return src


def import_url(db: Session, url: str, *, org_name: str | None = None, note: str | None = None, http_client: httpx.Client | None = None, resolver=None, actor: str = "owner") -> IngestOutcome:
    kwargs = {"rate_limit_per_minute": 30}
    if resolver:
        kwargs["resolver"] = resolver
    http = SafeHttp(http_client, **kwargs)
    try:
        res = http.get(url)
    finally:
        if http_client is None:
            http.close()
    if "html" not in res.content_type and not res.content.lstrip()[:1] == b"<":
        raise ValueError(f"Unsupported content type '{res.content_type}'. Use document import for PDF/DOCX.")
    title, text = extract_html(res.content)
    if note:
        text = f"{text}\n\nOwner note: {note}"
    canon = canonical_url(res.url) or res.url
    item = CollectedItem(
        external_id=f"url:{hashlib.sha256(canon.encode()).hexdigest()[:32]}",
        url=res.url, title=title or canon, content=text or (title or canon), raw={"requested_url": url, "final_url": res.url},
        org_name=org_name, org_website=res.url if org_name else None, evidence_type="page",
    )
    outcome = ingest_item(db, _source(db, "manual_url"), None, item, actor=actor)
    db.commit()
    return outcome


def _add_ai_requirements(db: Session, opp: Opportunity, ai, pages) -> int:
    """AI locates requirement clauses (verified verbatim); the deterministic rules classify them.

    Only clauses that produce a requirement type not already extracted for the same page are added
    (origin="ai_located"). Eligibility is then re-evaluated by the rule engine.
    """
    existing = {(r.requirement_key, r.page_reference) for r in db.query(EligibilityRequirement).filter_by(opportunity_id=opp.id)}
    evidence = db.query(Evidence).filter_by(opportunity_id=opp.id).order_by(Evidence.id).first()
    added = 0
    for r in extract_requirements(ai_requirement_clauses(ai, pages)):
        if (r.key.value, r.page_reference) in existing:
            continue
        existing.add((r.key.value, r.page_reference))
        db.add(EligibilityRequirement(
            opportunity_id=opp.id, scope=r.scope.value, requirement_key=r.key.value, mandatory=r.mandatory,
            text=r.text, parameters=r.parameters, origin="ai_located", evidence_id=evidence.id if evidence else None,
            page_reference=r.page_reference,
        ))
        added += 1
    if added:
        db.flush()
        evaluate_opportunity(db, opp)
    return added


def import_document(db: Session, file_name: str, data: bytes, *, buyer: str | None = None, source_url: str | None = None, actor: str = "owner") -> tuple[IngestOutcome, dict]:
    s = get_settings()
    if len(data) > s.upload_max_bytes:
        raise ValueError("File too large")
    safe_name = Path(file_name).name[:200]
    analysis = analyse_document(safe_name, data)
    digest = hashlib.sha256(data).hexdigest()
    up = Path(s.upload_dir)
    up.mkdir(parents=True, exist_ok=True)
    (up / f"{digest[:16]}_{safe_name}").write_bytes(data)

    f = analysis.fields
    ai = get_ai(db) if get_setting(db, "ai_document_extraction") and analysis.full_text else None
    if ai is not None:
        missing = [k for k, v in f.items() if v is None]
        for name, (value, ref, quote) in ai_document_fields(ai, analysis.pages, missing).items():
            f[name] = ExtractedField(value[:600], ref, quote[:400], method="ai")
    title = (f.get("tender_title").value if f.get("tender_title") else None) or safe_name
    buyer_name = buyer or (f["buyer"].value if f.get("buyer") else None)
    text = analysis.full_text or f"[No extractable text in {safe_name}]"
    item = CollectedItem(
        external_id=f"doc:{digest}",
        url=source_url, title=f"Tender: {title}"[:500], content=text,
        raw={"file_name": safe_name, "sha256": digest, "fields": {k: (v.__dict__ if v else None) for k, v in f.items()}},
        org_name=buyer_name, evidence_type="document", pages=analysis.pages, document_name=safe_name,
        needs_manual_review=analysis.needs_manual_review,
    )
    outcome = ingest_item(db, _source(db, "procurement_documents"), None, item, actor=actor)
    if outcome.opportunity_id:
        opp = db.get(Opportunity, outcome.opportunity_id)
        if outcome.status == "new":
            if analysis.needs_manual_review and opp.category in (Category.UNKNOWN.value, Category.IRRELEVANT.value):
                opp.category, opp.pipeline = Category.GOVERNMENT_TENDER.value, "B_vendor"
                opp.classification_evidence = [analysis.review_reason or "Manual review required"]
            if f.get("submission_deadline"):
                opp.deadline = parse_date(f["submission_deadline"].value)
            if f.get("publication_date"):
                opp.published_at = parse_date(f["publication_date"].value)
            if f.get("budget") and not opp.budget_text:
                opp.budget_text = f["budget"].value[:300]
            if ai is not None:
                _add_ai_requirements(db, opp, ai, analysis.pages)
                try:
                    summ = ai.complete_json("document_summary", "Summarise this tender document for a small software vendor. Only state what the text says.", truncate(analysis.full_text, 20000), AISummary)
                    opp.summary = summ.summary
                except AIUnavailable:
                    pass
        db.flush()
    db.commit()
    return outcome, {
        "file_name": safe_name,
        "file_type": analysis.file_type,
        "pages": len(analysis.pages),
        "needs_manual_review": analysis.needs_manual_review,
        "review_reason": analysis.review_reason,
        "fields": {k: (v.__dict__ if v else None) for k, v in f.items()},
    }
