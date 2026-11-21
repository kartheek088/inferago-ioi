"""SQLAlchemy 2.x ORM models.

Conventions:
- Integer surrogate primary keys; timestamps are naive UTC.
- Unknown values are NULL, never guessed.
- `published_at` (when the source published it) is kept separate from `retrieved_at`.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class Organisation(TimestampMixin, Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    domain: Mapped[str | None] = mapped_column(String(253), index=True)
    domain_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    website: Mapped[str | None] = mapped_column(String(2048))
    country: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    org_type: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    accepts_external_vendors: Mapped[bool | None] = mapped_column(Boolean)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="organisation", passive_deletes=True)
    contacts: Mapped[list["Contact"]] = relationship(back_populates="organisation", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        # A verified domain identifies exactly one organisation.
        Index(
            "uq_org_verified_domain",
            "domain",
            unique=True,
            sqlite_where=text("domain_verified = 1"),
        ),
    )


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str | None] = mapped_column(String(2048))
    country: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    access_method: Mapped[str] = mapped_column(String(50))
    connector: Mapped[str | None] = mapped_column(String(50))  # implementation key
    api_auth_requirements: Mapped[str | None] = mapped_column(Text)
    terms_notes: Mapped[str | None] = mapped_column(Text)
    collection_frequency_minutes: Mapped[int | None] = mapped_column(Integer)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=30)
    max_items_per_run: Mapped[int] = mapped_column(Integer, default=50)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    failure_status: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage: Mapped[str | None] = mapped_column(Text)
    connector_status: Mapped[str] = mapped_column(String(30))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cursor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # incremental state

    runs: Mapped[list["SourceRun"]] = relationship(back_populates="source")


class DiscoveryJob(Base):
    """A user- or scheduler-initiated discovery run across one or more sources (search history)."""

    __tablename__ = "discovery_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20))  # manual | scheduled
    query_terms: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20))
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class SourceRun(Base):
    __tablename__ = "source_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    discovery_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovery_jobs.id", ondelete="SET NULL"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    items_fetched: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    items_rejected: Mapped[int] = mapped_column(Integer, default=0)
    requests_made: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    log: Mapped[list[str]] = mapped_column(JSON, default=list)

    source: Mapped[Source] = relationship(back_populates="runs")


class RawRecord(Base):
    """Raw evidence exactly as collected, preserved for provenance."""

    __tablename__ = "raw_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("source_runs.id", ondelete="SET NULL"))
    external_id: Mapped[str] = mapped_column(String(300))
    canonical_url: Mapped[str | None] = mapped_column(String(2048), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_raw_source_external"),)


class Opportunity(TimestampMixin, Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    pipeline: Mapped[str] = mapped_column(String(20), index=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    classification_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    classification_method: Mapped[str] = mapped_column(String(20), default="rules")
    classification_evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    services_matched: Mapped[list[str]] = mapped_column(JSON, default=list)
    signals_matched: Mapped[list[str]] = mapped_column(JSON, default=list)
    organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="SET NULL"), index=True
    )
    # Geography is only set when explicitly stated; `geography_basis` records why.
    country: Mapped[str | None] = mapped_column(String(100), index=True)
    region: Mapped[str | None] = mapped_column(String(100))
    geography_basis: Mapped[str | None] = mapped_column(Text)
    remote_ok: Mapped[bool | None] = mapped_column(Boolean)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    dedupe_key: Mapped[str] = mapped_column(String(300), unique=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime)
    deadline: Mapped[datetime | None] = mapped_column(DateTime)
    budget_text: Mapped[str | None] = mapped_column(String(300))
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL")
    )
    priority: Mapped[float | None] = mapped_column(Float, index=True)
    eligibility_outcome: Mapped[str | None] = mapped_column(String(30), index=True)
    research_status: Mapped[str | None] = mapped_column(String(20))
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    organisation: Mapped[Organisation | None] = relationship(back_populates="opportunities")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="opportunity", cascade="all, delete-orphan", passive_deletes=True)
    scores: Mapped[list["OpportunityScore"]] = relationship(back_populates="opportunity", cascade="all, delete-orphan", passive_deletes=True)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    raw_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_records.id", ondelete="SET NULL")
    )
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    evidence_type: Mapped[str] = mapped_column(String(30))  # post|document|page|manual
    url: Mapped[str | None] = mapped_column(String(2048))
    excerpt: Mapped[str] = mapped_column(Text)
    page_reference: Mapped[str | None] = mapped_column(String(50))
    document_name: Mapped[str | None] = mapped_column(String(300))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    opportunity: Mapped[Opportunity | None] = relationship(back_populates="evidence")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    contact_type: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(String(500))
    label: Mapped[str | None] = mapped_column(String(200))
    person_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(200))
    # Where the contact route was observed. Mandatory: no source, no contact.
    source_url: Mapped[str] = mapped_column(String(2048))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_method: Mapped[str | None] = mapped_column(String(100))
    verification_date: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    organisation: Mapped[Organisation | None] = relationship(back_populates="contacts")

    __table_args__ = (
        UniqueConstraint("organisation_id", "opportunity_id", "contact_type", "value", name="uq_contact"),
    )


class BuyingSignal(Base):
    __tablename__ = "buying_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    signal_type: Mapped[str] = mapped_column(String(60))
    strength: Mapped[str] = mapped_column(String(20))  # strong|moderate|weak
    text: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EligibilityRequirement(Base):
    __tablename__ = "eligibility_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(30), default="project")
    requirement_key: Mapped[str] = mapped_column(String(50))
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    text: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(20), default="rules")  # rules|document|manual|ai
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"))
    page_reference: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EligibilityAssessment(Base):
    __tablename__ = "eligibility_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(30))
    outcome: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    satisfied: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    missing: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    mandatory_failures: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    clarifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    next_action: Mapped[str] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OpportunityScore(Base):
    __tablename__ = "opportunity_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    score_type: Mapped[str] = mapped_column(String(40))
    raw_total: Mapped[float] = mapped_column(Float)
    effective_total: Mapped[float] = mapped_column(Float)
    disqualified: Mapped[bool] = mapped_column(Boolean, default=False)
    unknown_components: Mapped[int] = mapped_column(Integer, default=0)
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    opportunity: Mapped[Opportunity] = relationship(back_populates="scores")

    __table_args__ = (
        UniqueConstraint("opportunity_id", "score_type", name="uq_score_opp_type"),
        CheckConstraint("raw_total >= 0 AND raw_total <= 100", name="ck_score_range"),
    )


class OrganisationRelationship(Base):
    __tablename__ = "organisation_relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_org_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    target_org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )
    target_opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    target_label: Mapped[str | None] = mapped_column(String(300))
    relationship_type: Mapped[str] = mapped_column(String(50))
    evidence_url: Mapped[str] = mapped_column(String(2048))
    evidence_excerpt: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    verification_status: Mapped[str] = mapped_column(String(20), default="hypothesis")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    origin: Mapped[str] = mapped_column(String(20), default="rules")

    __table_args__ = (
        CheckConstraint(
            "target_org_id IS NOT NULL OR target_opportunity_id IS NOT NULL OR target_label IS NOT NULL",
            name="ck_org_rel_target",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_org_rel_conf"),
        UniqueConstraint(
            "source_org_id", "target_org_id", "target_opportunity_id", "target_label",
            "relationship_type", "evidence_url", name="uq_org_rel",
        ),
    )


class OpportunityRelationship(Base):
    __tablename__ = "opportunity_relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    target_opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    source_org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="SET NULL")
    )
    relationship_type: Mapped[str] = mapped_column(String(50))
    evidence_url: Mapped[str] = mapped_column(String(2048))
    evidence_excerpt: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    verification_status: Mapped[str] = mapped_column(String(20), default="hypothesis")
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "source_opportunity_id", "target_opportunity_id", "relationship_type", name="uq_opp_rel"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_opp_rel_conf"),
    )


class ResearchTask(Base):
    __tablename__ = "research_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    priority: Mapped[float] = mapped_column(Float, default=0.0)
    depth: Mapped[str] = mapped_column(String(20), default="standard")  # light|standard|deep
    request_budget: Mapped[int] = mapped_column(Integer, default=6)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    findings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    brief: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class OutreachDraft(TimestampMixin, Base):
    __tablename__ = "outreach_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    generated_by: Mapped[str] = mapped_column(String(20), default="template")
    company_background: Mapped[str] = mapped_column(Text)
    why_shortlisted: Mapped[str] = mapped_column(Text)
    buying_signal: Mapped[str] = mapped_column(Text)
    evidence_links: Mapped[list[str]] = mapped_column(JSON, default=list)
    relevant_capability: Mapped[str] = mapped_column(Text)
    contact_route: Mapped[str] = mapped_column(Text)
    call_opening: Mapped[str] = mapped_column(Text)
    discovery_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    likely_objections: Mapped[list[str]] = mapped_column(JSON, default=list)
    email_subject: Mapped[str] = mapped_column(String(300))
    email_body: Mapped[str] = mapped_column(Text)
    recommended_next_action: Mapped[str] = mapped_column(Text)
    sent_manually_at: Mapped[datetime | None] = mapped_column(DateTime)


class OutreachApproval(Base):
    __tablename__ = "outreach_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("outreach_drafts.id", ondelete="CASCADE"), index=True
    )
    decision: Mapped[str] = mapped_column(String(20))  # approved|rejected
    decided_by: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CallTask(Base):
    __tablename__ = "call_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("outreach_drafts.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), default="open")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime)
    outcome: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    call_task_id: Mapped[int | None] = mapped_column(ForeignKey("call_tasks.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(100), default="system")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AIReview(Base):
    """Claude agent review of one opportunity: retrieved sources, verified facts, eligibility opinion.

    Advisory: the rule engine's assessment stays authoritative for mandatory gates. `agrees_with_rules`
    flags disagreements for human review.
    """

    __tablename__ = "ai_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|success|failed
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    model: Mapped[str | None] = mapped_column(String(200))
    verdict: Mapped[str | None] = mapped_column(String(40))
    opportunity_open: Mapped[str | None] = mapped_column(String(10))
    rule_outcome: Mapped[str | None] = mapped_column(String(30))
    agrees_with_rules: Mapped[bool | None] = mapped_column(Boolean)
    summary: Mapped[str | None] = mapped_column(Text)
    next_step: Mapped[str | None] = mapped_column(Text)
    requirement_reviews: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    facts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    open_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class AIUsageLog(Base):
    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(200))
    success: Mapped[bool] = mapped_column(Boolean)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ActionItem(Base):
    """Owner's own to-do list shown on the dashboard (e.g. "This week" actions)."""

    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2048))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(40), default="general")
    due_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Prospect(TimestampMixin, Base):
    """A business or independent professional that MAY need Inferago's services.

    Found from open data (OpenStreetMap) — they did not ask for anything. Every fact comes from
    the source record (`source_url`) or from a recorded website audit; nothing is guessed.
    """

    __tablename__ = "prospects"
    __table_args__ = (UniqueConstraint("source_ref", name="uq_prospect_source_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    segment: Mapped[str] = mapped_column(String(40), index=True)  # small_business | professional | enterprise
    business_type: Mapped[str] = mapped_column(String(80), index=True)  # e.g. "dentist"
    type_label: Mapped[str] = mapped_column(String(120))
    area: Mapped[str | None] = mapped_column(String(100), index=True)  # search area it was found in
    state: Mapped[str | None] = mapped_column(String(60), index=True)  # from the listing's region or a listed city within 40 km
    country: Mapped[str | None] = mapped_column(String(100), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    phone: Mapped[str | None] = mapped_column(String(200))  # exactly as published
    phone_normalized: Mapped[str | None] = mapped_column(String(30))  # e.g. +919843012345
    phone_type: Mapped[str | None] = mapped_column(String(20), index=True)  # mobile|landline|toll_free|international|invalid
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # confirmed by a human (call/WhatsApp)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    email: Mapped[str | None] = mapped_column(String(300))
    website: Mapped[str | None] = mapped_column(String(2048))
    social_links: Mapped[list[str]] = mapped_column(JSON, default=list)
    opening_hours: Mapped[str | None] = mapped_column(String(300))
    has_website: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    new_listing: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # not in the previous directory release
    source: Mapped[str] = mapped_column(String(40), default="openstreetmap")
    source_ref: Mapped[str] = mapped_column(String(100))  # e.g. "osm:node/123"
    source_url: Mapped[str] = mapped_column(String(2048))
    raw_tags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{key,label,detail}]
    recommended_services: Mapped[list[str]] = mapped_column(JSON, default=list)
    audit: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    audited_at: Mapped[datetime | None] = mapped_column(DateTime)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    need_level: Mapped[str | None] = mapped_column(String(20), index=True)  # definite | likely | upgrade | check_site | maybe
    need_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    quality_level: Mapped[str | None] = mapped_column(String(20), index=True)  # established | good | small
    quality_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    qualification: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # needs, budget, decision_maker, timeline (from calls)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_follow_up: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    contact_log: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ProspectRun(Base):
    __tablename__ = "prospect_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    areas: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    found: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    log: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class ProjectLead(TimestampMixin, Base):
    """A big project announced in public news (contract won, new plant, expansion, investment).

    The company running it may need outside help (software, websites, CRM, automation), so
    the owner can approach them as a vendor. Every lead links to the article it came from;
    the company name is read from the headline and must be checked by the owner.
    """

    __tablename__ = "project_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    feed: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    company: Mapped[str | None] = mapped_column(String(300))  # from the headline; owner should verify
    project_type: Mapped[str] = mapped_column(String(30), index=True)  # contract_won | new_facility | investment | mou
    amount_text: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str | None] = mapped_column(String(100), index=True)  # only if named in the text
    state: Mapped[str | None] = mapped_column(String(60), index=True)  # from a place named in the text
    fit: Mapped[str | None] = mapped_column(Text)  # how Inferago's services fit this project
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # connected companies [{company, role, quote, url, confirmed}]
    links_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    contact_log: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_follow_up: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    services: Mapped[list[str]] = mapped_column(JSON, default=list)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class BusinessChain(TimestampMixin, Base):
    """A local / regional business with several branches (found by grouping directory listings).

    Evidence is kept: branches that share a phone number, social page or website, or the same
    name + category in one state. One deal can cover every branch (CRM, billing, website).
    """

    __tablename__ = "business_chains"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)  # normalised name
    name: Mapped[str] = mapped_column(String(300))
    type_label: Mapped[str] = mapped_column(String(120))
    segment: Mapped[str] = mapped_column(String(40))
    branch_count: Mapped[int] = mapped_column(Integer, index=True)
    cities: Mapped[list[str]] = mapped_column(JSON, default=list)
    states: Mapped[list[str]] = mapped_column(JSON, default=list)
    main_state: Mapped[str | None] = mapped_column(String(60), index=True)
    phones: Mapped[list[str]] = mapped_column(JSON, default=list)
    socials: Mapped[list[str]] = mapped_column(JSON, default=list)
    has_website: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    evidence: Mapped[str] = mapped_column(String(40))  # shared_contact | same_name_one_state
    evidence_detail: Mapped[str | None] = mapped_column(Text)
    branches: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # up to 30: name, address, city, phone, lat, lon, source_url
    services: Mapped[list[str]] = mapped_column(JSON, default=list)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    contact_log: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_follow_up: Mapped[datetime | None] = mapped_column(DateTime, index=True)
