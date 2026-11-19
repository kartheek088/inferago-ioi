"""Outreach workspace: drafts, human approval, call tasks and follow-ups.

V1 NEVER sends email, places calls, submits bids, registers as a vendor or signs anything.
Every outbound communication requires an explicit human approval recorded in
`outreach_approvals`; a human then sends it themselves and may mark it "sent manually".
Drafts state only real profile facts — no fabricated credentials, clients or numbers.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.openrouter import AIOutreach, AIUnavailable, get_ai
from app.db import utcnow
from app.enums import CallOutcome, DraftStatus, OpportunityStatus, TaskStatus
from app.models import (
    BuyingSignal,
    CallTask,
    Contact,
    EligibilityAssessment,
    Evidence,
    FollowUpTask,
    Opportunity,
    OutreachApproval,
    OutreachDraft,
    Organisation,
)
from app.normalize import truncate
from app.profile import SERVICE_KEYS
from app.settings_store import get_profile, log_activity


class WorkflowError(Exception):
    pass


EDITABLE = {DraftStatus.DRAFT.value, DraftStatus.REJECTED.value}

FOLLOW_UP_RULES: dict[str, tuple[str, int] | None] = {
    CallOutcome.INTERESTED.value: ("Send meeting invite / scoping questions (draft requires approval)", 2),
    CallOutcome.NOT_INTERESTED.value: ("Re-check only if a new buying signal appears", 90),
    CallOutcome.CALL_BACK.value: ("Call back as requested", 3),
    CallOutcome.WRONG_CONTACT.value: ("Find the correct public contact route", 2),
    CallOutcome.EXISTING_VENDOR.value: ("Ask about overflow / subcontract needs; revisit later", 60),
    CallOutcome.WANTS_COMPANY_PROFILE.value: ("Send factual company profile (no fabricated credentials) — approval required", 1),
    CallOutcome.WANTS_PROPOSAL.value: ("Prepare proposal for review and approval", 3),
    CallOutcome.SHARED_VENDOR_DETAILS.value: ("Review vendor registration requirements manually (do not auto-register)", 2),
    CallOutcome.NO_ANSWER.value: ("Retry call", 2),
}


def generate_draft(db: Session, opp: Opportunity, *, use_ai: bool = True, actor: str = "system") -> OutreachDraft:
    profile = get_profile(db)
    org = db.get(Organisation, opp.organisation_id) if opp.organisation_id else None
    signals = db.scalars(select(BuyingSignal).where(BuyingSignal.opportunity_id == opp.id)).all()
    evidence = db.scalars(select(Evidence).where(Evidence.opportunity_id == opp.id, Evidence.url.is_not(None))).all()
    contacts = db.scalars(select(Contact).where(Contact.opportunity_id == opp.id)).all()
    elig = db.scalar(select(EligibilityAssessment).where(EligibilityAssessment.opportunity_id == opp.id, EligibilityAssessment.scope == "project").order_by(EligibilityAssessment.id.desc()).limit(1))
    best_contact = next((c for c in contacts if c.verified), None) or next(iter(contacts), None)

    services = [SERVICE_KEYS[s] for s in (opp.services_matched or []) if s in SERVICE_KEYS] or profile.services[:2]
    who = org.name if org else "your team"
    signal_text = signals[0].text if signals else "No explicit buying signal recorded."
    capability = "; ".join(services)
    contact_route = (
        f"{best_contact.contact_type}: {best_contact.value} ({'verified' if best_contact.verified else 'unverified'}; source {best_contact.source_url})"
        if best_contact else "No contact route found yet — research required."
    )
    subject = truncate(f"Re: {opp.title}", 120)
    body = (
        f"Hello {who},\n\n"
        f"I saw your post/notice: \"{truncate(opp.title, 140)}\".\n\n"
        f"I run {profile.company_name}, a {profile.region}, {profile.country}-based independent practice "
        f"(Udyam-registered sole proprietorship) focused on {capability.lower()}.\n\n"
        "Based on what you described, I'd like to understand your requirements before suggesting an approach. "
        "Would you be open to a short call this week?\n\n"
        f"Regards,\n{profile.company_name}"
    )
    draft = OutreachDraft(
        opportunity_id=opp.id,
        contact_id=best_contact.id if best_contact else None,
        status=DraftStatus.DRAFT.value,
        generated_by="template",
        company_background=(org.description if org and org.description else "No verified company background collected yet."),
        why_shortlisted=f"Priority {opp.priority}; category {opp.category}; services matched: {', '.join(opp.services_matched or []) or 'none'}; eligibility {opp.eligibility_outcome or 'unknown'}.",
        buying_signal=signal_text,
        evidence_links=list(dict.fromkeys(e.url for e in evidence if e.url))[:10],
        relevant_capability=capability,
        contact_route=contact_route,
        call_opening=f"Hi, this is the founder of {profile.company_name}. I'm calling about your requirement \"{truncate(opp.title, 80)}\" — is now a good time for two minutes?",
        discovery_questions=[
            "What problem are you trying to solve, and what happens today without it?",
            "Which systems/APIs need to be integrated?",
            "What timeline and budget range are you working with?",
            "Who else is involved in the decision?",
            "Do you work with external vendors or freelancers for this kind of work?",
        ] + ([f"Clarify: {q}" for q in (elig.clarifications[:3] if elig else [])]),
        likely_objections=[
            "We need a company with a larger team → offer a small, well-scoped first milestone.",
            "We need prior corporate references → be transparent; offer a paid pilot instead of claiming credentials.",
            "We require GST invoices → Inferago is not GST registered; confirm whether this blocks engagement.",
        ],
        email_subject=subject,
        email_body=body,
        recommended_next_action="Review and edit, then submit for approval. Nothing is sent automatically.",
    )
    if use_ai:
        ai = get_ai(db)
        if ai:
            try:
                res = ai.complete_json(
                    "outreach_draft",
                    "Draft a short, honest first-contact email and call opener for this opportunity. Use ONLY these "
                    f"facts about the sender: {profile.model_dump_json(include={'company_name', 'legal_structure', 'country', 'region', 'services', 'gst_registered', 'corporate_project_credentials'})}. "
                    "Do not claim past clients, team size, certifications or turnover.",
                    f"Opportunity: {opp.title}\n{truncate(opp.description, 5000)}",
                    AIOutreach, max_tokens=900,
                )
                draft.email_subject, draft.email_body, draft.call_opening = res.email_subject, res.email_body, res.call_opening
                draft.discovery_questions = res.discovery_questions or draft.discovery_questions
                draft.likely_objections = res.likely_objections or draft.likely_objections
                draft.generated_by = "ai"
            except AIUnavailable:
                pass
    db.add(draft)
    db.flush()
    log_activity(db, "outreach_draft", draft.id, "generated", {"opportunity_id": opp.id, "by": draft.generated_by}, actor)
    return draft


def update_draft(db: Session, draft: OutreachDraft, changes: dict, actor: str) -> OutreachDraft:
    if draft.status not in EDITABLE:
        if draft.status in (DraftStatus.APPROVED.value, DraftStatus.PENDING_APPROVAL.value):
            # Editing invalidates any approval: back to draft.
            draft.status = DraftStatus.DRAFT.value
        else:
            raise WorkflowError(f"Draft in status '{draft.status}' cannot be edited")
    for k, v in changes.items():
        setattr(draft, k, v)
    log_activity(db, "outreach_draft", draft.id, "edited", {"fields": list(changes)}, actor)
    db.flush()
    return draft


def submit_for_approval(db: Session, draft: OutreachDraft, actor: str) -> OutreachDraft:
    if draft.status not in EDITABLE:
        raise WorkflowError(f"Only drafts can be submitted (status is '{draft.status}')")
    draft.status = DraftStatus.PENDING_APPROVAL.value
    log_activity(db, "outreach_draft", draft.id, "submitted", {}, actor)
    db.flush()
    return draft


def decide(db: Session, draft: OutreachDraft, decision: str, decided_by: str, note: str | None) -> OutreachApproval:
    if not decided_by or not decided_by.strip():
        raise WorkflowError("An approver name is required")
    if draft.status != DraftStatus.PENDING_APPROVAL.value:
        raise WorkflowError(f"Draft must be pending approval (status is '{draft.status}')")
    if decision not in ("approved", "rejected"):
        raise WorkflowError("Decision must be 'approved' or 'rejected'")
    approval = OutreachApproval(draft_id=draft.id, decision=decision, decided_by=decided_by.strip(), note=note)
    db.add(approval)
    draft.status = DraftStatus.APPROVED.value if decision == "approved" else DraftStatus.REJECTED.value
    if decision == "approved":
        opp = db.get(Opportunity, draft.opportunity_id)
        if opp and opp.status not in (OpportunityStatus.REJECTED.value, OpportunityStatus.ARCHIVED.value):
            opp.status = OpportunityStatus.OUTREACH.value
    log_activity(db, "outreach_draft", draft.id, decision, {"note": note}, decided_by)
    db.flush()
    return approval


def mark_sent_manually(db: Session, draft: OutreachDraft, actor: str) -> OutreachDraft:
    """Record that a HUMAN sent the approved message outside the system."""
    approved = db.scalar(select(OutreachApproval.id).where(OutreachApproval.draft_id == draft.id, OutreachApproval.decision == "approved"))
    if draft.status != DraftStatus.APPROVED.value or not approved:
        raise WorkflowError("Only approved drafts can be marked as sent")
    draft.status = DraftStatus.SENT_MANUALLY.value
    draft.sent_manually_at = utcnow()
    db.add(FollowUpTask(opportunity_id=draft.opportunity_id, action="Check for a reply; follow up once if no response", reason="Outreach sent manually", due_date=utcnow() + timedelta(days=4)))
    log_activity(db, "outreach_draft", draft.id, "sent_manually", {}, actor)
    db.flush()
    return draft


def create_call_task(db: Session, opp: Opportunity, *, contact_id: int | None, draft_id: int | None, scheduled_for: datetime | None, actor: str) -> CallTask:
    """Calls are made by a human. A call task requires an approved draft (call opening) for the opportunity."""
    q = select(OutreachDraft).where(OutreachDraft.opportunity_id == opp.id, OutreachDraft.status.in_([DraftStatus.APPROVED.value, DraftStatus.SENT_MANUALLY.value]))
    if draft_id:
        q = q.where(OutreachDraft.id == draft_id)
    draft = db.scalar(q.limit(1))
    if not draft:
        raise WorkflowError("A call task requires an approved outreach draft for this opportunity")
    task = CallTask(opportunity_id=opp.id, contact_id=contact_id or draft.contact_id, draft_id=draft.id, scheduled_for=scheduled_for, status=TaskStatus.OPEN.value)
    db.add(task)
    db.flush()
    log_activity(db, "call_task", task.id, "created", {"opportunity_id": opp.id}, actor)
    return task


def record_call_outcome(db: Session, task: CallTask, outcome: str, notes: str | None, actor: str, follow_up_date: datetime | None = None) -> FollowUpTask | None:
    try:
        CallOutcome(outcome)
    except ValueError as exc:
        raise WorkflowError(f"Unknown call outcome '{outcome}'") from exc
    task.outcome, task.notes, task.status, task.completed_at = outcome, notes, TaskStatus.DONE.value, utcnow()
    opp = db.get(Opportunity, task.opportunity_id)
    if outcome == CallOutcome.NOT_INTERESTED.value and opp:
        opp.status = OpportunityStatus.ARCHIVED.value
    rule = FOLLOW_UP_RULES.get(outcome)
    fu = None
    if rule:
        action, days = rule
        fu = FollowUpTask(
            opportunity_id=task.opportunity_id, call_task_id=task.id, action=action, reason=f"Call outcome: {outcome}",
            due_date=follow_up_date or (utcnow() + timedelta(days=days)), status=TaskStatus.OPEN.value,
        )
        db.add(fu)
    log_activity(db, "call_task", task.id, "outcome_recorded", {"outcome": outcome}, actor)
    db.flush()
    return fu
