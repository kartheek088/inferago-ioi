"""Organisations, opportunities, evidence, eligibility, scoring, research, relationships, contacts."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import jobs
from app.api.deps import DB, Paging, actor, paginate
from app.classification import classify
from app.config import get_settings
from app.db import utcnow
from app.enums import EligibilityScope, OpportunityStatus
from app.evaluation import evaluate_opportunity, run_scoring
from app.models import (
    BuyingSignal,
    Contact,
    AIReview,
    EligibilityAssessment,
    EligibilityRequirement,
    Evidence,
    Opportunity,
    OpportunityRelationship,
    OpportunityScore,
    Organisation,
    OrganisationRelationship,
    ResearchTask,
    Source,
)
from app.normalize import domain_of, normalize_org_name
from app.pipeline import _apply_classification
from app.relationships import set_verification
from app.research import research_opportunity, run_research_batch
from app.schemas import (
    AIReviewOut,
    AssessmentOut,
    BuyingSignalOut,
    ContactIn,
    ContactOut,
    EvidenceOut,
    OpportunityDetail,
    OpportunityOut,
    OpportunityUpdate,
    OppRelationshipIn,
    OppRelationshipOut,
    OrganisationOut,
    OrganisationUpdate,
    OrgRelationshipIn,
    OrgRelationshipOut,
    Page,
    RequirementIn,
    RequirementOut,
    ResearchTaskOut,
    ScoreOut,
    VerificationIn,
)
from app.settings_store import log_activity

router = APIRouter()

SORTS = {
    "priority": Opportunity.priority.desc().nulls_last(),
    "newest": Opportunity.published_at.desc().nulls_last(),
    "collected": Opportunity.created_at.desc(),
    "deadline": Opportunity.deadline.asc().nulls_last(),
}


def _opp_or_404(db: Session, opp_id: int) -> Opportunity:
    o = db.get(Opportunity, opp_id)
    if not o:
        raise HTTPException(404, "Opportunity not found")
    return o


def _decorate(db: Session, opps: list[Opportunity]) -> list[OpportunityOut]:
    org_ids = {o.organisation_id for o in opps if o.organisation_id}
    src_ids = {o.source_id for o in opps if o.source_id}
    orgs = dict(db.execute(select(Organisation.id, Organisation.name).where(Organisation.id.in_(org_ids))).all()) if org_ids else {}
    srcs = dict(db.execute(select(Source.id, Source.key).where(Source.id.in_(src_ids))).all()) if src_ids else {}
    out = []
    for o in opps:
        m = OpportunityOut.model_validate(o)
        m.organisation_name = orgs.get(o.organisation_id)
        m.source_key = srcs.get(o.source_id)
        out.append(m)
    return out


@router.get("/opportunities", response_model=Page[OpportunityOut], tags=["opportunities"])
def list_opportunities(
    q: str | None = None,
    pipeline: str | None = None,
    category: str | None = None,
    status: str | None = None,
    country: str | None = Query(None, description="Country name, or 'unknown'"),
    eligibility: str | None = None,
    organisation_id: int | None = None,
    min_priority: float | None = None,
    include_demo: bool = True,
    include_merged: bool = False,
    sort: str = Query("priority", pattern="^(priority|newest|collected|deadline)$"),
    paging: Paging = Depends(),
    db: Session = DB,
):
    stmt = select(Opportunity).options(selectinload(Opportunity.scores))
    if not include_merged:
        stmt = stmt.where(Opportunity.merged_into_id.is_(None))
    if not include_demo:
        stmt = stmt.where(Opportunity.is_demo.is_(False))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Opportunity.title.ilike(like), Opportunity.description.ilike(like)))
    for col, val in ((Opportunity.pipeline, pipeline), (Opportunity.category, category), (Opportunity.status, status), (Opportunity.eligibility_outcome, eligibility), (Opportunity.organisation_id, organisation_id)):
        if val is not None:
            stmt = stmt.where(col == val)
    if country:
        stmt = stmt.where(Opportunity.country.is_(None) if country.lower() == "unknown" else Opportunity.country == country)
    if min_priority is not None:
        stmt = stmt.where(Opportunity.priority >= min_priority)
    stmt = stmt.order_by(SORTS[sort], Opportunity.id.desc())
    items, total = paginate(db, stmt, paging)
    return Page(items=_decorate(db, items), total=total, limit=paging.limit, offset=paging.offset)


@router.get("/opportunities/{opp_id}", response_model=OpportunityDetail, tags=["opportunities"])
def get_opportunity(opp_id: int, db: Session = DB):
    o = _opp_or_404(db, opp_id)
    m = OpportunityDetail.model_validate(o)
    base = _decorate(db, [o])[0]
    m.organisation_name, m.source_key = base.organisation_name, base.source_key
    return m


@router.patch("/opportunities/{opp_id}", response_model=OpportunityDetail, tags=["opportunities"])
def update_opportunity(opp_id: int, body: OpportunityUpdate, db: Session = DB, who: str = Depends(actor)):
    o = _opp_or_404(db, opp_id)
    data = body.model_dump(exclude_unset=True)
    if "organisation_id" in data and data["organisation_id"] is not None and not db.get(Organisation, data["organisation_id"]):
        raise HTTPException(404, "Organisation not found")
    for k, v in data.items():
        setattr(o, k, v.value if hasattr(v, "value") else v)
    if "country" in data or "region" in data:
        o.geography_basis = f"Set manually by {who}"
    if {"country", "region", "organisation_id"} & data.keys():
        run_scoring(db, o)
    log_activity(db, "opportunity", o.id, "updated", {k: str(v) for k, v in data.items()}, who)
    db.commit()
    return get_opportunity(opp_id, db)


@router.post("/opportunities/{opp_id}/reclassify", response_model=OpportunityDetail, tags=["opportunities"])
def reclassify(opp_id: int, db: Session = DB, who: str = Depends(actor)):
    o = _opp_or_404(db, opp_id)
    src = db.get(Source, o.source_id) if o.source_id else None
    cls = classify(o.title, o.description, source_category=src.category if src else None)
    _apply_classification(o, cls)
    db.query(BuyingSignal).filter(BuyingSignal.opportunity_id == o.id).delete()
    for s in cls.signals:
        db.add(BuyingSignal(opportunity_id=o.id, signal_type=s.signal_type, strength=s.strength, text=s.text))
    db.flush()
    evaluate_opportunity(db, o)
    log_activity(db, "opportunity", o.id, "reclassified", {"category": o.category}, who)
    db.commit()
    return get_opportunity(opp_id, db)


@router.post("/opportunities/{opp_id}/merge-into/{target_id}", response_model=OpportunityDetail, tags=["opportunities"])
def merge(opp_id: int, target_id: int, db: Session = DB, who: str = Depends(actor)):
    """Manually merge a duplicate. Evidence is re-pointed to the target; the duplicate keeps its record."""
    if opp_id == target_id:
        raise HTTPException(400, "Cannot merge into itself")
    o, t = _opp_or_404(db, opp_id), _opp_or_404(db, target_id)
    if t.merged_into_id:
        raise HTTPException(400, "Target is itself merged")
    for e in db.scalars(select(Evidence).where(Evidence.opportunity_id == o.id)).all():
        e.opportunity_id = t.id
    o.merged_into_id, o.status = t.id, OpportunityStatus.ARCHIVED.value
    log_activity(db, "opportunity", o.id, "merged", {"into": t.id}, who)
    db.flush()
    run_scoring(db, t)
    db.commit()
    return get_opportunity(target_id, db)


@router.post("/opportunities/{opp_id}/evaluate", response_model=list[ScoreOut], tags=["scoring"])
def evaluate(opp_id: int, db: Session = DB):
    o = _opp_or_404(db, opp_id)
    evaluate_opportunity(db, o)
    db.commit()
    return db.scalars(select(OpportunityScore).where(OpportunityScore.opportunity_id == o.id)).all()


@router.get("/opportunities/{opp_id}/scores", response_model=list[ScoreOut], tags=["scoring"])
def scores(opp_id: int, db: Session = DB):
    _opp_or_404(db, opp_id)
    return db.scalars(select(OpportunityScore).where(OpportunityScore.opportunity_id == opp_id)).all()


@router.get("/opportunities/{opp_id}/evidence", response_model=list[EvidenceOut], tags=["evidence"])
def opp_evidence(opp_id: int, db: Session = DB):
    _opp_or_404(db, opp_id)
    return db.scalars(select(Evidence).where(Evidence.opportunity_id == opp_id).order_by(Evidence.id)).all()


@router.get("/opportunities/{opp_id}/signals", response_model=list[BuyingSignalOut], tags=["opportunities"])
def opp_signals(opp_id: int, db: Session = DB):
    return db.scalars(select(BuyingSignal).where(BuyingSignal.opportunity_id == opp_id)).all()


@router.get("/evidence", response_model=Page[EvidenceOut], tags=["evidence"])
def list_evidence(q: str | None = None, opportunity_id: int | None = None, organisation_id: int | None = None, evidence_type: str | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(Evidence).order_by(Evidence.id.desc())
    if q:
        stmt = stmt.where(Evidence.excerpt.ilike(f"%{q}%"))
    if opportunity_id:
        stmt = stmt.where(Evidence.opportunity_id == opportunity_id)
    if organisation_id:
        stmt = stmt.where(Evidence.organisation_id == organisation_id)
    if evidence_type:
        stmt = stmt.where(Evidence.evidence_type == evidence_type)
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/evidence/{evidence_id}", response_model=EvidenceOut, tags=["evidence"])
def get_evidence(evidence_id: int, db: Session = DB):
    e = db.get(Evidence, evidence_id)
    if not e:
        raise HTTPException(404, "Evidence not found")
    return e


# --- Eligibility ------------------------------------------------------------------------------


@router.get("/opportunities/{opp_id}/requirements", response_model=list[RequirementOut], tags=["eligibility"])
def list_requirements(opp_id: int, db: Session = DB):
    _opp_or_404(db, opp_id)
    return db.scalars(select(EligibilityRequirement).where(EligibilityRequirement.opportunity_id == opp_id).order_by(EligibilityRequirement.id)).all()


@router.post("/opportunities/{opp_id}/requirements", response_model=RequirementOut, status_code=201, tags=["eligibility"])
def add_requirement(opp_id: int, body: RequirementIn, db: Session = DB, who: str = Depends(actor)):
    o = _opp_or_404(db, opp_id)
    r = EligibilityRequirement(opportunity_id=o.id, scope=body.scope.value, requirement_key=body.requirement_key.value, mandatory=body.mandatory,
                               text=body.text, parameters=body.parameters, origin="manual", page_reference=body.page_reference)
    db.add(r)
    db.flush()
    evaluate_opportunity(db, o)
    log_activity(db, "opportunity", o.id, "requirement_added", {"key": r.requirement_key}, who)
    db.commit()
    return r


@router.delete("/opportunities/{opp_id}/requirements/{req_id}", status_code=204, tags=["eligibility"])
def delete_requirement(opp_id: int, req_id: int, db: Session = DB, who: str = Depends(actor)):
    o = _opp_or_404(db, opp_id)
    r = db.get(EligibilityRequirement, req_id)
    if not r or r.opportunity_id != opp_id:
        raise HTTPException(404, "Requirement not found")
    db.delete(r)
    db.flush()
    evaluate_opportunity(db, o)
    log_activity(db, "opportunity", o.id, "requirement_removed", {"key": r.requirement_key}, who)
    db.commit()


@router.get("/opportunities/{opp_id}/eligibility", response_model=dict[str, AssessmentOut | None], tags=["eligibility"])
def latest_eligibility(opp_id: int, db: Session = DB):
    _opp_or_404(db, opp_id)
    out = {}
    for scope in EligibilityScope:
        out[scope.value] = db.scalar(select(EligibilityAssessment).where(EligibilityAssessment.opportunity_id == opp_id, EligibilityAssessment.scope == scope.value).order_by(EligibilityAssessment.id.desc()).limit(1))
    return out


@router.post("/opportunities/{opp_id}/ai-review", response_model=AIReviewOut | None, status_code=202, tags=["ai"])
def start_ai_review(opp_id: int, wait: bool = False, db: Session = DB, who: str = Depends(actor)):
    """Claude retrieves sources, verifies facts and checks eligibility (advisory; rules stay authoritative)."""
    opp = _opp_or_404(db, opp_id)
    if not get_settings().claude_enabled:
        raise HTTPException(400, "Claude is not configured: set IOI_ANTHROPIC_API_KEY in .env and restart")
    log_activity(db, "opportunity", opp_id, "ai_review_requested", {}, who)
    db.commit()
    if wait:
        from app.ai.agent import run_review

        return run_review(db, opp)
    jobs.submit_review(opp_id)
    return None


@router.get("/opportunities/{opp_id}/ai-reviews", response_model=list[AIReviewOut], tags=["ai"])
def list_ai_reviews(opp_id: int, db: Session = DB):
    _opp_or_404(db, opp_id)
    return db.scalars(select(AIReview).where(AIReview.opportunity_id == opp_id).order_by(AIReview.id.desc()).limit(20)).all()


@router.post("/ai-reviews/batch", status_code=202, tags=["ai"])
def ai_review_batch(limit: int = Query(5, ge=1, le=50)):
    if not get_settings().claude_enabled:
        raise HTTPException(400, "Claude is not configured: set IOI_ANTHROPIC_API_KEY in .env and restart")
    jobs.submit_review_batch(limit)
    return {"queued": limit}


@router.get("/eligibility", response_model=Page[AssessmentOut], tags=["eligibility"])
def list_assessments(outcome: str | None = None, scope: str = "project", paging: Paging = Depends(), db: Session = DB):
    """Latest assessment per opportunity for the given scope."""
    sub = select(func.max(EligibilityAssessment.id)).where(EligibilityAssessment.scope == scope).group_by(EligibilityAssessment.opportunity_id)
    stmt = select(EligibilityAssessment).where(EligibilityAssessment.id.in_(sub)).order_by(EligibilityAssessment.id.desc())
    if outcome:
        stmt = stmt.where(EligibilityAssessment.outcome == outcome)
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


# --- Organisations ----------------------------------------------------------------------------


@router.get("/organisations", response_model=Page[OrganisationOut], tags=["organisations"])
def list_orgs(q: str | None = None, country: str | None = None, accepts_external_vendors: bool | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(Organisation).order_by(Organisation.name)
    if q:
        stmt = stmt.where(or_(Organisation.name.ilike(f"%{q}%"), Organisation.domain.ilike(f"%{q}%")))
    if country:
        stmt = stmt.where(Organisation.country == country)
    if accepts_external_vendors is not None:
        stmt = stmt.where(Organisation.accepts_external_vendors.is_(accepts_external_vendors))
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/organisations/{org_id}", tags=["organisations"])
def get_org(org_id: int, db: Session = DB):
    o = db.get(Organisation, org_id)
    if not o:
        raise HTTPException(404, "Organisation not found")
    opps = db.scalars(select(Opportunity).where(Opportunity.organisation_id == org_id).order_by(Opportunity.priority.desc().nulls_last())).all()
    contacts = db.scalars(select(Contact).where(Contact.organisation_id == org_id)).all()
    return {
        "organisation": OrganisationOut.model_validate(o),
        "opportunities": _decorate(db, list(opps)),
        "contacts": [ContactOut.model_validate(c) for c in contacts],
        "relationships": [_rel_out(db, r) for r in db.scalars(select(OrganisationRelationship).where(or_(OrganisationRelationship.source_org_id == org_id, OrganisationRelationship.target_org_id == org_id))).all()],
    }


@router.patch("/organisations/{org_id}", response_model=OrganisationOut, tags=["organisations"])
def update_org(org_id: int, body: OrganisationUpdate, db: Session = DB, who: str = Depends(actor)):
    o = db.get(Organisation, org_id)
    if not o:
        raise HTTPException(404, "Organisation not found")
    data = body.model_dump(exclude_unset=True)
    if "website" in data and data["website"] is not None:
        data["website"] = str(data["website"])
        new_dom = domain_of(data["website"])
        if new_dom != o.domain:
            o.domain, o.domain_verified = new_dom, False
    if "name" in data and data["name"]:
        o.normalized_name = normalize_org_name(data["name"])
    for k, v in data.items():
        setattr(o, k, v)
    log_activity(db, "organisation", o.id, "updated", {"fields": list(data)}, who)
    for opp in db.scalars(select(Opportunity).where(Opportunity.organisation_id == o.id)).all():
        run_scoring(db, opp)
    db.commit()
    return o


# --- Contacts ---------------------------------------------------------------------------------


@router.get("/contacts", response_model=Page[ContactOut], tags=["contacts"])
def list_contacts(opportunity_id: int | None = None, organisation_id: int | None = None, verified: bool | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(Contact).order_by(Contact.id.desc())
    if opportunity_id:
        stmt = stmt.where(Contact.opportunity_id == opportunity_id)
    if organisation_id:
        stmt = stmt.where(Contact.organisation_id == organisation_id)
    if verified is not None:
        stmt = stmt.where(Contact.verified.is_(verified))
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.post("/contacts", response_model=ContactOut, status_code=201, tags=["contacts"])
def add_contact(body: ContactIn, db: Session = DB, who: str = Depends(actor)):
    """Record a public business contact route. A source URL where it was published is mandatory."""
    if not body.organisation_id and not body.opportunity_id:
        raise HTTPException(422, "organisation_id or opportunity_id is required")
    c = Contact(
        organisation_id=body.organisation_id, opportunity_id=body.opportunity_id, contact_type=body.contact_type.value,
        value=body.value, label=body.label, person_name=body.person_name, role=body.role, source_url=str(body.source_url),
        verified=body.verified, verification_method=f"manual:{who}" if body.verified else None,
        verification_date=utcnow() if body.verified else None, notes=body.notes,
    )
    db.add(c)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Contact already exists") from exc
    if body.opportunity_id:
        o = db.get(Opportunity, body.opportunity_id)
        if o:
            run_scoring(db, o)
    log_activity(db, "contact", c.id, "created", {"type": c.contact_type}, who)
    db.commit()
    return c


@router.delete("/contacts/{contact_id}", status_code=204, tags=["contacts"])
def delete_contact(contact_id: int, db: Session = DB, who: str = Depends(actor)):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    db.delete(c)
    log_activity(db, "contact", contact_id, "deleted", {}, who)
    db.commit()


# --- Relationships ----------------------------------------------------------------------------


def _rel_out(db: Session, r: OrganisationRelationship) -> OrgRelationshipOut:
    m = OrgRelationshipOut.model_validate(r)
    src = db.get(Organisation, r.source_org_id)
    m.source_org_name = src.name if src else None
    if r.target_org_id:
        t = db.get(Organisation, r.target_org_id)
        m.target_org_name = t.name if t else None
    return m


@router.get("/relationships/organisations", response_model=Page[OrgRelationshipOut], tags=["relationships"])
def list_org_rels(verification_status: str | None = None, org_id: int | None = None, relationship_type: str | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(OrganisationRelationship).order_by(OrganisationRelationship.id.desc())
    if verification_status:
        stmt = stmt.where(OrganisationRelationship.verification_status == verification_status)
    if org_id:
        stmt = stmt.where(or_(OrganisationRelationship.source_org_id == org_id, OrganisationRelationship.target_org_id == org_id))
    if relationship_type:
        stmt = stmt.where(OrganisationRelationship.relationship_type == relationship_type)
    items, total = paginate(db, stmt, paging)
    return Page(items=[_rel_out(db, r) for r in items], total=total, limit=paging.limit, offset=paging.offset)


@router.post("/relationships/organisations", response_model=OrgRelationshipOut, status_code=201, tags=["relationships"])
def add_org_rel(body: OrgRelationshipIn, db: Session = DB, who: str = Depends(actor)):
    if not (body.target_org_id or body.target_opportunity_id or body.target_label):
        raise HTTPException(422, "A target organisation, opportunity or label is required")
    if not db.get(Organisation, body.source_org_id):
        raise HTTPException(404, "Source organisation not found")
    r = OrganisationRelationship(**{**body.model_dump(), "evidence_url": str(body.evidence_url), "relationship_type": body.relationship_type.value,
                                    "verification_status": body.verification_status.value}, origin="manual")
    if body.verification_status.value == "confirmed":
        r.verified_at = utcnow()
    db.add(r)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Relationship already exists") from exc
    _rescore_org(db, body.source_org_id)
    log_activity(db, "relationship", r.id, "created", {"type": r.relationship_type, "status": r.verification_status}, who)
    db.commit()
    return _rel_out(db, r)


@router.patch("/relationships/organisations/{rel_id}", response_model=OrgRelationshipOut, tags=["relationships"])
def verify_org_rel(rel_id: int, body: VerificationIn, db: Session = DB, who: str = Depends(actor)):
    r = db.get(OrganisationRelationship, rel_id)
    if not r:
        raise HTTPException(404, "Relationship not found")
    set_verification(r, body.verification_status.value)
    db.flush()
    _rescore_org(db, r.source_org_id)
    log_activity(db, "relationship", r.id, f"marked_{r.verification_status}", {}, who)
    db.commit()
    return _rel_out(db, r)


@router.get("/relationships/opportunities", response_model=Page[OppRelationshipOut], tags=["relationships"])
def list_opp_rels(opportunity_id: int | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(OpportunityRelationship).order_by(OpportunityRelationship.id.desc())
    if opportunity_id:
        stmt = stmt.where(or_(OpportunityRelationship.source_opportunity_id == opportunity_id, OpportunityRelationship.target_opportunity_id == opportunity_id))
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.post("/relationships/opportunities", response_model=OppRelationshipOut, status_code=201, tags=["relationships"])
def add_opp_rel(body: OppRelationshipIn, db: Session = DB, who: str = Depends(actor)):
    if body.source_opportunity_id == body.target_opportunity_id:
        raise HTTPException(422, "Source and target must differ")
    a, b = _opp_or_404(db, body.source_opportunity_id), _opp_or_404(db, body.target_opportunity_id)
    r = OpportunityRelationship(**{**body.model_dump(), "evidence_url": str(body.evidence_url), "relationship_type": body.relationship_type.value,
                                   "verification_status": body.verification_status.value}, source_org_id=a.organisation_id)
    db.add(r)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Relationship already exists") from exc
    run_scoring(db, a)
    run_scoring(db, b)
    log_activity(db, "opp_relationship", r.id, "created", {}, who)
    db.commit()
    return r


@router.patch("/relationships/opportunities/{rel_id}", response_model=OppRelationshipOut, tags=["relationships"])
def verify_opp_rel(rel_id: int, body: VerificationIn, db: Session = DB, who: str = Depends(actor)):
    r = db.get(OpportunityRelationship, rel_id)
    if not r:
        raise HTTPException(404, "Relationship not found")
    set_verification(r, body.verification_status.value)
    for oid in (r.source_opportunity_id, r.target_opportunity_id):
        o = db.get(Opportunity, oid)
        if o:
            run_scoring(db, o)
    log_activity(db, "opp_relationship", r.id, f"marked_{r.verification_status}", {}, who)
    db.commit()
    return r


@router.get("/chains", tags=["relationships"])
def chains(db: Session = DB, include_hypotheses: bool = True):
    """Graph view: nodes (organisations/opportunities/labels) and evidence-backed edges."""
    stmt = select(OrganisationRelationship)
    if not include_hypotheses:
        stmt = stmt.where(OrganisationRelationship.verification_status == "confirmed")
    rels = db.scalars(stmt.where(OrganisationRelationship.verification_status != "rejected")).all()
    nodes: dict[str, dict] = {}
    edges = []
    for r in rels:
        src = db.get(Organisation, r.source_org_id)
        sid = f"org:{r.source_org_id}"
        nodes[sid] = {"id": sid, "label": src.name if src else sid, "kind": "organisation"}
        if r.target_org_id:
            t = db.get(Organisation, r.target_org_id)
            tid, label, kind = f"org:{r.target_org_id}", (t.name if t else ""), "organisation"
        elif r.target_opportunity_id:
            t = db.get(Opportunity, r.target_opportunity_id)
            tid, label, kind = f"opp:{r.target_opportunity_id}", (t.title if t else ""), "opportunity"
        else:
            tid, label, kind = f"label:{(r.target_label or '').lower()}", r.target_label, "unresolved"
        nodes[tid] = {"id": tid, "label": label, "kind": kind}
        edges.append({"id": r.id, "source": sid, "target": tid, "type": r.relationship_type, "status": r.verification_status,
                      "confidence": r.confidence, "evidence_url": r.evidence_url, "evidence_excerpt": r.evidence_excerpt})
    return {"nodes": list(nodes.values()), "edges": edges, "note": "Relationships indicate possible routes; no downstream project is guaranteed."}


def _rescore_org(db: Session, org_id: int) -> None:
    for opp in db.scalars(select(Opportunity).where(Opportunity.organisation_id == org_id)).all():
        run_scoring(db, opp)


# --- Research ---------------------------------------------------------------------------------


@router.get("/research/tasks", response_model=Page[ResearchTaskOut], tags=["research"])
def list_research(status: str | None = None, opportunity_id: int | None = None, paging: Paging = Depends(), db: Session = DB):
    stmt = select(ResearchTask).order_by(ResearchTask.id.desc())
    if status:
        stmt = stmt.where(ResearchTask.status == status)
    if opportunity_id:
        stmt = stmt.where(ResearchTask.opportunity_id == opportunity_id)
    items, total = paginate(db, stmt, paging)
    return Page(items=items, total=total, limit=paging.limit, offset=paging.offset)


@router.get("/research/queue", response_model=Page[OpportunityOut], tags=["research"])
def research_queue(paging: Paging = Depends(), db: Session = DB):
    """Candidates awaiting deep research, ranked by priority."""
    stmt = (select(Opportunity).options(selectinload(Opportunity.scores))
            .where(Opportunity.merged_into_id.is_(None), Opportunity.status.in_(["new", "shortlisted"]), Opportunity.priority > 0,
                   or_(Opportunity.research_status.is_(None), Opportunity.research_status != "done"))
            .order_by(Opportunity.priority.desc()))
    items, total = paginate(db, stmt, paging)
    return Page(items=_decorate(db, items), total=total, limit=paging.limit, offset=paging.offset)


@router.post("/opportunities/{opp_id}/research", response_model=ResearchTaskOut, tags=["research"])
def research_one(opp_id: int, force: bool = False, db: Session = DB, who: str = Depends(actor)):
    o = _opp_or_404(db, opp_id)
    task = research_opportunity(db, o, force=force)
    log_activity(db, "research_task", task.id, "manual_research", {"opportunity_id": o.id}, who)
    db.commit()
    return task


@router.post("/research/batch", tags=["research"])
def research_batch(wait: bool = False, db: Session = DB, who: str = Depends(actor)):
    log_activity(db, "research", None, "batch_started", {}, who)
    db.commit()
    if not wait:
        jobs.submit_research()
        return {"status": "started"}
    rep = run_research_batch(db)
    return rep.__dict__
