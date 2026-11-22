"""Outreach (human-approved; nothing is sent by IOI), sales pipeline, proposals, payments, revenue.

Revenue rules:
- potential  = owner's rough estimates on open deals (never revenue)
- quoted     = amounts in sent proposals
- contracted = quoted amount of deals that reached "Advance Received" or later
- collected  = sum of recorded payments — the only number that counts toward the monthly goal
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.ioi3 import core, qualify
from app.ioi3.models import Activity, Company, Deal, Payment, Proposal
from app.lead_rules import EQUIPMENT

STAGES = [
    ("new_prospect", "New Prospect"), ("contacted", "Contacted"), ("replied", "Replied"), ("discovery_call", "Discovery Call"),
    ("requirement_confirmed", "Requirement Confirmed"), ("proposal_sent", "Proposal Sent"), ("negotiating", "Negotiating"),
    ("advance_received", "Advance Received"), ("in_delivery", "In Delivery"), ("completed", "Completed"),
    ("payment_collected", "Payment Collected"),
]
STAGE_KEYS = [k for k, _ in STAGES]
OUTCOMES = {"not_interested": "Not Interested", "no_response": "No Response", "lost": "Lost", "follow_up_later": "Follow Up Later"}
CONTRACTED = set(STAGE_KEYS[STAGE_KEYS.index("advance_received"):])


class SalesError(ValueError):
    pass


def log(db: Session, c: Company, kind: str, summary: str, *, actor: str = "owner", channel: str | None = None,
        deal: Deal | None = None, at: datetime | None = None) -> Activity:
    a = Activity(company_id=c.id, deal_id=deal.id if deal else None, kind=kind, summary=summary[:2000], actor=actor, channel=channel,
                 occurred_at=at or utcnow())
    db.add(a)
    return a


# ------------------------------------------------------------------------------------------------
# Outreach draft + approval
# ------------------------------------------------------------------------------------------------
def draft(c: Company, sender_name: str = "", sender_link: str = "") -> dict[str, Any]:
    sol = c.solution or {}
    confirmed = [f for f in c.facts if f.kind == "signal" and f.review_status == "confirmed"]
    seen = [f for f in c.facts if f.kind == "workflow" and f.state == "source_verified"]
    me = f"I'm {sender_name} from Inferago Tech Services" if sender_name else "I run Inferago Tech Services"
    if confirmed:
        hook = f"I saw that {c.name} {confirmed[0].statement.lower()} ({confirmed[0].source_url})."
    elif seen:
        hook = f"I noticed on your website that you handle {seen[0].statement.removeprefix('The business mentions ').lower()}."
    else:
        hook = "I came across your company while looking at Chennai " + ("equipment service companies." if c.industry == EQUIPMENT else "distributors.")
    offer = sol.get("improvement") or "simple tools that fit the way your team already works"
    msg = (f"Hello {c.name} team,\n\n{me}, a small Udyam-registered software practice in Tamil Nadu. {hook}\n\n"
           f"We set up simple business automation — for example, {offer[0].lower() + offer[1:] if offer else ''} — that works with "
           "the tools you already use (phone, WhatsApp, Excel, Tally), with very little training.\n\n"
           "I don't know yet whether this would help you, so I'd like to ask a few questions first. Would a 15-minute call this week "
           "be useful? If not, just reply 'no' and I won't follow up." + (f"\n\nAbout us: {sender_link}" if sender_link else "") + "\n\nRegards")
    role = "Service manager or owner" if c.industry == EQUIPMENT else "Operations/dispatch manager or owner"
    return {"message": c.outreach_draft or msg, "edited": bool(c.outreach_draft), "contact_role": role,
            "questions": sol.get("confirm_with_buyer") or [],
            "notice": "IOI never sends messages. Copy the text and contact them yourself."}


def approve(db: Session, c: Company, actor: str, message: str | None = None) -> Company:
    if c.review_status in ("rejected", "duplicate") or c.qualification == "P3":
        raise SalesError("This business is excluded; restore it before approving.")
    if not qualify.sales_ready(c.gates):
        missing = [g["label"] for g in c.gates if g["passed"] is not True]
        raise SalesError("Can't approve yet — still needs: " + ", ".join(missing))
    if message:
        c.outreach_draft = message
    elif not c.outreach_draft:
        c.outreach_draft = draft(c)["message"]
    c.review_status, c.outreach_approved_by, c.outreach_approved_at = "approved", actor, utcnow()
    log(db, c, "approved", "Approved for outreach", actor=actor)
    core.evaluate(c)
    return c


def edit_draft(db: Session, c: Company, message: str, actor: str) -> Company:
    c.outreach_draft = message
    if c.review_status == "approved":  # editing an approved message needs a fresh approval
        c.review_status, c.outreach_approved_by, c.outreach_approved_at = "shortlisted", None, None
        log(db, c, "note", "Message edited — approval reset", actor=actor)
    return c


def set_review(db: Session, c: Company, status: str, actor: str, reason: str | None = None) -> Company:
    if status not in ("watchlist", "rejected", "new", "shortlisted"):
        raise SalesError("Unknown status")
    c.review_status = status
    log(db, c, {"watchlist": "watchlist", "rejected": "rejected"}.get(status, "note"),
        {"watchlist": "Moved to watchlist", "rejected": "Rejected", "new": "Restored", "shortlisted": "Moved to Ready to Review"}[status]
        + (f": {reason}" if reason else ""), actor=actor)
    core.evaluate(c)
    return c


def _require_approved(c: Company) -> None:
    if c.review_status != "approved" and c.outreach_approved_at is None:
        raise SalesError("Approve this business for outreach first.")


def mark_contacted(db: Session, c: Company, actor: str, channel: str, note: str | None, follow_up_days: int | None = 3) -> Company:
    _require_approved(c)
    log(db, c, "contacted", f"Contacted by {channel}" + (f": {note}" if note else ""), actor=actor, channel=channel)
    c.next_follow_up_at = utcnow() + timedelta(days=follow_up_days) if follow_up_days else None
    deal = ensure_deal(db, c)
    if STAGE_KEYS.index(deal.stage) < STAGE_KEYS.index("contacted"):
        move(db, deal, "contacted", actor)
    return c


def record_reply(db: Session, c: Company, actor: str, summary: str, interested: bool | None, buyer_problem: str | None = None) -> Company:
    _require_approved(c)
    log(db, c, "reply", ("Interested — " if interested else "Not interested — " if interested is False else "") + summary, actor=actor)
    if buyer_problem:
        core.add_fact(c, kind="problem", key=None, state="buyer_confirmed", statement=buyer_problem.strip()[:500],
                      source_name="Buyer (recorded by you)", detected_by="buyer", reliability="high")
    deal = ensure_deal(db, c)
    if interested is False:
        deal.outcome = "not_interested"
        c.next_follow_up_at = None
    elif STAGE_KEYS.index(deal.stage) < STAGE_KEYS.index("replied"):
        move(db, deal, "replied", actor)
    core.evaluate(c)
    return c


def schedule_follow_up(db: Session, c: Company, at: datetime, actor: str, note: str | None = None) -> Company:
    c.next_follow_up_at = at
    deal = db.scalar(select(Deal).where(Deal.company_id == c.id))
    if deal:
        deal.next_follow_up_at = at
    log(db, c, "follow_up", f"Follow-up on {at:%d %b %Y}" + (f": {note}" if note else ""), actor=actor, deal=deal)
    return c


# ------------------------------------------------------------------------------------------------
# Pipeline
# ------------------------------------------------------------------------------------------------
def ensure_deal(db: Session, c: Company) -> Deal:
    d = db.scalar(select(Deal).where(Deal.company_id == c.id))
    if d is None:
        d = Deal(campaign_id=c.campaign_id, company_id=c.id, stage="new_prospect", offer=(c.solution or {}).get("offer"))
        db.add(d)
        db.flush()
        log(db, c, "stage", "Added to the sales pipeline", deal=d)
    return d


def move(db: Session, d: Deal, stage: str, actor: str) -> Deal:
    if stage not in STAGE_KEYS:
        raise SalesError("Unknown stage")
    if stage in CONTRACTED and not d.quoted_amount:
        raise SalesError("Record the quoted amount (create a proposal) before moving to " + dict(STAGES)[stage])
    if stage == "payment_collected" and balance(d) > 0:
        raise SalesError(f"₹{balance(d):,} is still outstanding — record the payment first")
    old = d.stage
    d.stage, d.outcome = stage, None
    log(db, d.company, "stage", f"{dict(STAGES).get(old, old)} → {dict(STAGES)[stage]}", actor=actor, deal=d)
    return d


def set_outcome(db: Session, d: Deal, outcome: str | None, actor: str) -> Deal:
    if outcome is not None and outcome not in OUTCOMES:
        raise SalesError("Unknown outcome")
    d.outcome = outcome
    log(db, d.company, "stage", f"Outcome: {OUTCOMES.get(outcome or '', 'reopened')}", actor=actor, deal=d)
    return d


def add_proposal(db: Session, d: Deal, *, title: str, scope: str | None, amount: int | None, sent: bool, actor: str) -> Proposal:
    if amount is not None and amount <= 0:
        raise SalesError("Amount must be positive")
    p = Proposal(deal_id=d.id, title=title.strip()[:200], scope=scope, amount=amount, status="sent" if sent else "draft",
                 sent_on=date.today() if sent else None)
    db.add(p)
    if sent and amount:
        d.quoted_amount = amount
        if STAGE_KEYS.index(d.stage) < STAGE_KEYS.index("proposal_sent"):
            move(db, d, "proposal_sent", actor)
    log(db, d.company, "proposal", f"Proposal '{p.title}'" + (f" ₹{amount:,}" if amount else "") + (" sent" if sent else " drafted"),
        actor=actor, deal=d)
    return p


def add_payment(db: Session, d: Deal, *, amount: int, kind: str, received_on: date, reference: str | None, note: str | None,
                actor: str) -> Payment:
    if amount <= 0:
        raise SalesError("Payment amount must be positive")
    if kind not in ("advance", "milestone", "final"):
        raise SalesError("Unknown payment type")
    if received_on > date.today():
        raise SalesError("A payment can't be received in the future — record it when the money arrives")
    p = Payment(deal_id=d.id, amount=amount, kind=kind, received_on=received_on, reference=reference, note=note)
    d.payments.append(p)
    db.flush()
    if kind == "advance" and d.quoted_amount and STAGE_KEYS.index(d.stage) < STAGE_KEYS.index("advance_received"):
        move(db, d, "advance_received", actor)
    log(db, d.company, "payment", f"Payment received: ₹{amount:,} ({kind})", actor=actor, deal=d)
    return p


def collected(d: Deal) -> int:
    return sum(p.amount for p in d.payments)


def balance(d: Deal) -> int:
    return max(0, (d.quoted_amount or 0) - collected(d)) if d.stage in CONTRACTED or d.payments else 0


def revenue(db: Session, campaign_id: int, today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    month_start = today.replace(day=1)
    deals = list(db.scalars(select(Deal).where(Deal.campaign_id == campaign_id)))
    open_deals = [d for d in deals if d.outcome not in ("not_interested", "lost")]
    quoted = sum(d.quoted_amount or 0 for d in open_deals if d.stage in {"proposal_sent", "negotiating"} | CONTRACTED)
    contracted = sum(d.quoted_amount or 0 for d in deals if d.stage in CONTRACTED)
    all_paid = sum(collected(d) for d in deals)
    month = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).join(Deal).where(
        Deal.campaign_id == campaign_id, Payment.received_on >= month_start, Payment.received_on <= today)) or 0
    advances = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).join(Deal).where(
        Deal.campaign_id == campaign_id, Payment.kind == "advance")) or 0
    return {
        "potential": sum(d.potential_amount or 0 for d in open_deals if d.stage not in CONTRACTED),
        "quoted": quoted, "contracted": contracted, "advances_received": int(advances),
        "outstanding": sum(balance(d) for d in deals if d.stage in CONTRACTED),
        "collected_total": all_paid, "collected_this_month": int(month),
    }


def tasks(db: Session, campaign_id: int, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    base = select(Company).where(Company.campaign_id == campaign_id, Company.archived.is_(False))
    to_review = db.scalar(select(func.count()).select_from(base.where(Company.review_status == "shortlisted").subquery())) or 0
    due_c = list(db.scalars(base.where(Company.next_follow_up_at.is_not(None), Company.next_follow_up_at <= now)))
    deals = list(db.scalars(select(Deal).where(Deal.campaign_id == campaign_id, Deal.outcome.is_(None))))
    replies = [d for d in deals if d.stage == "replied"]
    proposals = [d for d in deals if d.stage in ("requirement_confirmed", "proposal_sent", "negotiating")]
    signals = 0
    from app.ioi3.models import Fact

    signals = db.scalar(select(func.count()).select_from(Fact).join(Company).where(
        Company.campaign_id == campaign_id, Company.archived.is_(False), Fact.kind == "signal", Fact.review_status == "hypothesis")) or 0
    return {
        "leads_to_review": to_review,
        "signals_to_check": signals,
        "follow_ups_due": [{"company_id": c.id, "name": c.name, "due": c.next_follow_up_at} for c in due_c],
        "replies": [{"deal_id": d.id, "company_id": d.company_id, "name": d.company.name} for d in replies],
        "proposals": [{"deal_id": d.id, "company_id": d.company_id, "name": d.company.name, "stage": d.stage} for d in proposals],
    }
