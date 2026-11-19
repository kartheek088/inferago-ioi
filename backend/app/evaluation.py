"""Re-runs eligibility + scoring for an opportunity from its stored data."""

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.eligibility import ENGINE_VERSION, assess
from app.enums import EligibilityScope, OppRelationshipType, VerificationStatus
from app.models import (
    BuyingSignal,
    Contact,
    EligibilityAssessment,
    EligibilityRequirement,
    Evidence,
    Opportunity,
    OpportunityRelationship,
    OpportunityScore,
    Organisation,
    ResearchTask,
)
from app.relationships import confirmed_counts
from app.scoring import ScoringInput, compute_priority, score_all
from app.settings_store import get_profile, get_setting

REPEAT_TERMS = re.compile(r"\b(ongoing|long[- ]term|retainer|maintenance|phase\s*(2|ii|two)|multiple projects|recurring|support contract)\b", re.I)
SCOPE_TERMS = re.compile(r"\b(deadline|timeline|deliverables?|milestones?|weeks?|months?|by (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|scope)\b", re.I)


def requirement_dicts(db: Session, opp_id: int) -> list[dict]:
    reqs = db.scalars(select(EligibilityRequirement).where(EligibilityRequirement.opportunity_id == opp_id)).all()
    return [
        {"key": r.requirement_key, "text": r.text, "mandatory": r.mandatory, "parameters": r.parameters,
         "page_reference": r.page_reference, "scope": r.scope, "evidence_id": r.evidence_id}
        for r in reqs
    ]


def run_eligibility(db: Session, opp: Opportunity) -> dict[str, EligibilityAssessment]:
    profile = get_profile(db)
    reqs = requirement_dicts(db, opp.id)
    out = {}
    for scope in EligibilityScope:
        res = assess(reqs, profile, scope)
        a = EligibilityAssessment(
            opportunity_id=opp.id, scope=scope.value, outcome=res.outcome.value, reason=res.reason,
            evidence=res.evidence, satisfied=res.satisfied, missing=res.missing,
            mandatory_failures=res.mandatory_failures, clarifications=res.clarifications,
            next_action=res.next_action, engine_version=ENGINE_VERSION,
        )
        db.add(a)
        out[scope.value] = a
    opp.eligibility_outcome = out[EligibilityScope.PROJECT.value].outcome
    db.flush()
    return out


def build_scoring_input(db: Session, opp: Opportunity) -> ScoringInput:
    text = f"{opp.title}\n{opp.description or ''}"
    signals = db.execute(select(BuyingSignal.signal_type, BuyingSignal.strength).where(BuyingSignal.opportunity_id == opp.id)).all()
    contacts = db.scalars(select(Contact).where(
        (Contact.opportunity_id == opp.id) | ((Contact.organisation_id == opp.organisation_id) & (Contact.organisation_id.is_not(None)))
    )).all()
    evidence_count = db.scalar(select(func.count()).select_from(Evidence).where(Evidence.opportunity_id == opp.id)) or 0
    org = db.get(Organisation, opp.organisation_id) if opp.organisation_id else None
    confirmed, hyp = confirmed_counts(db, opp.organisation_id)
    org_opps = 1
    if opp.organisation_id:
        org_opps = db.scalar(select(func.count()).select_from(Opportunity).where(
            Opportunity.organisation_id == opp.organisation_id, Opportunity.merged_into_id.is_(None))) or 1
    repeat_links = db.scalar(select(func.count()).select_from(OpportunityRelationship).where(
        (OpportunityRelationship.source_opportunity_id == opp.id) | (OpportunityRelationship.target_opportunity_id == opp.id),
        OpportunityRelationship.relationship_type.in_([OppRelationshipType.REPEAT_PROJECT.value, OppRelationshipType.RELATED_REQUIREMENT.value]),
        OpportunityRelationship.verification_status == VerificationStatus.CONFIRMED.value,
    )) or 0
    research_done = db.scalar(select(func.count()).select_from(ResearchTask).where(
        ResearchTask.opportunity_id == opp.id, ResearchTask.status == "done")) or 0
    vendor_reg = db.scalar(select(EligibilityAssessment.outcome).where(
        EligibilityAssessment.opportunity_id == opp.id, EligibilityAssessment.scope == EligibilityScope.VENDOR_REGISTRATION.value
    ).order_by(EligibilityAssessment.id.desc()).limit(1))
    from app.classification import EXTERNAL_VENDOR_NEGATIVE, EXTERNAL_VENDOR_POSITIVE, _find

    return ScoringInput(
        category=opp.category,
        services=list(opp.services_matched or []),
        signals=[(t, s) for t, s in signals],
        has_text=bool(text.strip()),
        description_length=len(opp.description or ""),
        budget_text=opp.budget_text,
        deadline=opp.deadline,
        scope_detail_terms=len(SCOPE_TERMS.findall(text)),
        contacts_verified=sum(1 for c in contacts if c.verified),
        contacts_unverified=sum(1 for c in contacts if not c.verified),
        vendor_portal_found=any(c.contact_type == "vendor_onboarding_page" for c in contacts),
        research_done=bool(research_done),
        vendor_positive=[m.group(0) for m in _find(EXTERNAL_VENDOR_POSITIVE, text)],
        vendor_negative=[m.group(0) for m in _find(EXTERNAL_VENDOR_NEGATIVE, text)],
        evidence_count=evidence_count,
        published_at=opp.published_at,
        classification_confidence=opp.classification_confidence,
        eligibility_outcome=opp.eligibility_outcome,
        vendor_registration_outcome=vendor_reg,
        accepts_external_vendors=org.accepts_external_vendors if org else None,
        country=opp.country,
        remote_ok=opp.remote_ok,
        confirmed_relationships=confirmed,
        hypothesis_relationships=hyp,
        org_opportunity_count=org_opps,
        repeat_terms=list(dict.fromkeys(m.group(0).lower() for m in REPEAT_TERMS.finditer(text))),
        confirmed_repeat_links=repeat_links,
        now=utcnow(),
    )


def run_scoring(db: Session, opp: Opportunity) -> list[OpportunityScore]:
    inp = build_scoring_input(db, opp)
    results = score_all(inp)
    db.execute(delete(OpportunityScore).where(OpportunityScore.opportunity_id == opp.id))
    rows = []
    for r in results:
        row = OpportunityScore(
            opportunity_id=opp.id, score_type=r.score_type.value, raw_total=r.raw_total,
            effective_total=r.effective_total, disqualified=r.disqualified,
            unknown_components=r.unknown_components, components=r.components_dict(), explanation=r.explanation,
        )
        db.add(row)
        rows.append(row)
    opp.priority = compute_priority(opp.pipeline, opp.category, results, opp.country, opp.region, get_setting(db, "country_priorities"))
    db.flush()
    return rows


def evaluate_opportunity(db: Session, opp: Opportunity) -> None:
    run_eligibility(db, opp)
    run_scoring(db, opp)
