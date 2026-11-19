"""Opportunity-chain intelligence: evidence-backed relationships stored as an SQL graph.

Rule-extracted relationships are always stored as HYPOTHESES with the exact evidence URL and
excerpt. Only a human (or a verified structural fact) promotes them to CONFIRMED. A
relationship never implies a downstream project is guaranteed.
"""

import re
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.enums import OppRelationshipType, OrgRelationshipType as R, VerificationStatus as V
from app.models import Opportunity, OpportunityRelationship, Organisation, OrganisationRelationship

NAME = r"([A-Z][A-Za-z0-9&.+-]*(?:\s+[A-Z][A-Za-z0-9&.+-]*){0,3})"

PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"\b(?:we are|we're|is|an?)\s+(?:an?\s+)?(?:certified|official|authori[sz]ed|registered|premier|gold|silver)?\s*" + NAME + r"\s+(?:implementation\s+)?partner\b"), R.PARTNER_PROGRAMME, 0.6),
    (re.compile(NAME + r"\s+(?:partner program(?:me)?|partner network|partner portal)\b"), R.PARTNER_PROGRAMME, 0.5),
    (re.compile(r"\bimplementation partner (?:for|of)\s+" + NAME), R.IMPLEMENTATION_PARTNER, 0.55),
    (re.compile(r"\b(?:awarded|granted)\s+(?:to\s+)?" + NAME, re.I), R.AWARDED_CONTRACT, 0.5),
    (re.compile(r"\b(?:clients?|customers?)\s+(?:include|such as|like)\s+" + NAME), R.CUSTOMER_OF, 0.45),
    (re.compile(r"\bin partnership with\s+" + NAME), R.REFERRAL_ROUTE, 0.4),
    (re.compile(r"\b(?:powered by|built on|technology partner)\s+" + NAME), R.TECHNOLOGY_PROVIDER, 0.4),
]
STOP_TARGETS = {"We", "Our", "The", "A", "An", "This", "Partner", "Partners", "Program", "Certified", "Official", "I"}


@dataclass
class FoundRelationship:
    relationship_type: str
    target_label: str
    excerpt: str
    confidence: float


def find_relationships(text: str) -> list[FoundRelationship]:
    out: list[FoundRelationship] = []
    seen: set[tuple[str, str]] = set()
    for pat, rtype, conf in PATTERNS:
        for m in pat.finditer(text or ""):
            label = m.group(1).strip(" .,")
            if not label or label in STOP_TARGETS or len(label) < 2:
                continue
            key = (str(rtype), label.lower())
            if key in seen:
                continue
            seen.add(key)
            s, e = max(0, m.start() - 80), min(len(text), m.end() + 80)
            out.append(FoundRelationship(str(rtype), label, re.sub(r"\s+", " ", text[s:e]).strip(), conf))
    return out


def record_found(db: Session, org: Organisation, evidence_url: str, found: list[FoundRelationship]) -> int:
    n = 0
    for f in found:
        exists = db.scalar(
            select(OrganisationRelationship.id).where(
                OrganisationRelationship.source_org_id == org.id,
                OrganisationRelationship.relationship_type == f.relationship_type,
                OrganisationRelationship.target_label == f.target_label,
                OrganisationRelationship.evidence_url == evidence_url,
            )
        )
        if exists:
            continue
        db.add(OrganisationRelationship(
            source_org_id=org.id, target_label=f.target_label, relationship_type=f.relationship_type,
            evidence_url=evidence_url, evidence_excerpt=f.excerpt, confidence=f.confidence,
            verification_status=V.HYPOTHESIS.value, origin="rules",
        ))
        n += 1
    db.flush()
    return n


def link_same_buyer(db: Session, opp: Opportunity) -> int:
    """Link opportunities attributed to the same organisation.

    Confirmed only when the organisation's domain is verified; otherwise a hypothesis.
    """
    if not opp.organisation_id:
        return 0
    org = db.get(Organisation, opp.organisation_id)
    others = db.scalars(
        select(Opportunity).where(
            Opportunity.organisation_id == opp.organisation_id,
            Opportunity.id != opp.id,
            Opportunity.merged_into_id.is_(None),
        )
    ).all()
    n = 0
    for other in others:
        a, b = sorted([opp.id, other.id])
        exists = db.scalar(select(OpportunityRelationship.id).where(
            OpportunityRelationship.source_opportunity_id == a,
            OpportunityRelationship.target_opportunity_id == b,
            OpportunityRelationship.relationship_type == OppRelationshipType.SAME_BUYER.value,
        ))
        if exists:
            continue
        target = opp if b == opp.id else other
        db.add(OpportunityRelationship(
            source_opportunity_id=a, target_opportunity_id=b, source_org_id=opp.organisation_id,
            relationship_type=OppRelationshipType.SAME_BUYER.value,
            evidence_url=target.canonical_url or "",
            evidence_excerpt=f"Both opportunities are attributed to '{org.name}' in their source records.",
            confidence=0.85 if org.domain_verified else 0.6,
            verification_status=(V.CONFIRMED if org.domain_verified else V.HYPOTHESIS).value,
        ))
        n += 1
    db.flush()
    return n


def confirmed_counts(db: Session, org_id: int | None) -> tuple[dict[str, int], int]:
    if not org_id:
        return {}, 0
    rows = db.execute(
        select(OrganisationRelationship.relationship_type, OrganisationRelationship.verification_status, func.count())
        .where(or_(OrganisationRelationship.source_org_id == org_id, OrganisationRelationship.target_org_id == org_id))
        .group_by(OrganisationRelationship.relationship_type, OrganisationRelationship.verification_status)
    ).all()
    confirmed: dict[str, int] = {}
    hyp = 0
    for rtype, status, cnt in rows:
        if status == V.CONFIRMED.value:
            confirmed[rtype] = confirmed.get(rtype, 0) + cnt
        elif status == V.HYPOTHESIS.value:
            hyp += cnt
    return confirmed, hyp


def set_verification(rel: OrganisationRelationship | OpportunityRelationship, status: str) -> None:
    rel.verification_status = V(status).value
    if isinstance(rel, OrganisationRelationship):
        rel.verified_at = utcnow() if status == V.CONFIRMED.value else None
