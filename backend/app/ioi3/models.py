"""IOI 3.0 schema (tables prefixed `ioi_`). Legacy tables are kept untouched as a read-only archive.

Conventions: naive-UTC timestamps; unknown = NULL (never guessed); every fact has provenance;
money is stored as integer rupees.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow

# Acquisition channel: which pipeline a record belongs to. Shared tables carry it so the two
# pipelines stay isolated while sharing identity, contacts, evidence, outreach and payments.
B2B = "b2b"
SOCIAL = "social_commerce"
CHANNELS = (B2B, SOCIAL)


class _Stamped:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Campaign(_Stamped, Base):
    __tablename__ = "ioi_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(20), default=B2B, index=True)  # b2b | social_commerce
    city: Mapped[str] = mapped_column(String(100), default="Chennai")
    industries: Mapped[list[str]] = mapped_column(JSON, default=list)  # equipment_service | wholesale_distribution, or social categories
    industry_mix: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)  # share of discovery effort, e.g. {"equipment_service": 70}
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # depth, limits, schedule
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | archived
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)


class DiscoverySource(_Stamped, Base):
    __tablename__ = "ioi_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(2048))
    category: Mapped[str] = mapped_column(String(40))  # directory | website | news | import | manual
    access_method: Mapped[str] = mapped_column(String(40))  # local_file | http | rss | csv | form
    geo_coverage: Mapped[str] = mapped_column(String(200))
    industry_coverage: Mapped[str] = mapped_column(String(200))
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer)
    terms: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Health is only "working" after a real successful retrieval.
    health: Mapped[str] = mapped_column(String(20), default="untested")  # untested | working | failing | needs_setup
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_records: Mapped[int | None] = mapped_column(Integer)
    data_freshness: Mapped[str | None] = mapped_column(String(200))


class Job(Base):
    __tablename__ = "ioi_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("ioi_campaigns.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default=B2B, index=True)  # which pipeline's runner executes this job
    mode: Mapped[str] = mapped_column(String(20))  # quick | balanced | deep
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | running | stopping | stopped | completed | failed | interrupted
    stage: Mapped[str | None] = mapped_column(String(40))
    stage_index: Mapped[int] = mapped_column(Integer, default=0)
    counters: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)  # processed, accepted, rejected, pending, total
    sources: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # key -> {status, records, error}
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    log: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_of_id: Mapped[int | None] = mapped_column(ForeignKey("ioi_jobs.id", ondelete="SET NULL"))
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual | scheduled | retry
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class RawItem(Base):
    """Exactly what a source returned for a business that passed the first filters (provenance)."""

    __tablename__ = "ioi_raw_items"
    __table_args__ = (UniqueConstraint("campaign_id", "source_key", "external_id", name="uq_ioi_raw_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("ioi_campaigns.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("ioi_jobs.id", ondelete="SET NULL"), index=True)
    source_key: Mapped[str] = mapped_column(String(60))
    external_id: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    outcome: Mapped[str] = mapped_column(String(40), index=True)  # accepted | outside_chennai | duplicate | unmatched_news | news_matched
    company_id: Mapped[int | None] = mapped_column(ForeignKey("ioi_companies.id", ondelete="SET NULL"))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Company(_Stamped, Base):
    """A business in a campaign. Qualification fields are recomputed from facts by `qualify.evaluate`."""

    __tablename__ = "ioi_companies"
    __table_args__ = (
        UniqueConstraint("campaign_id", "source_ref", name="uq_ioi_company_source"),
        Index("ix_ioi_company_campaign_review", "campaign_id", "review_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("ioi_campaigns.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default=B2B, index=True)  # b2b | social_commerce
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    industry: Mapped[str | None] = mapped_column(String(40), index=True)  # equipment_service | wholesale_distribution
    industry_subtype: Mapped[str | None] = mapped_column(String(40))
    industry_strength: Mapped[str] = mapped_column(String(20), default="candidate")  # strong | candidate | none
    industry_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    directory_category: Mapped[str | None] = mapped_column(String(120))
    website: Mapped[str | None] = mapped_column(String(2048))
    domain: Mapped[str | None] = mapped_column(String(253), index=True)
    # Primary location (details and evidence in ioi_locations)
    address: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(String(120))
    pincode: Mapped[str | None] = mapped_column(String(10))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    location_confidence: Mapped[str] = mapped_column(String(20), default="unknown", index=True)  # verified | partial | unknown | outside
    location_reason: Mapped[str | None] = mapped_column(Text)
    activity: Mapped[str] = mapped_column(String(20), default="unknown")  # active | likely_active | unknown | inactive
    description: Mapped[str | None] = mapped_column(Text)  # short, source-based
    # Qualification (deterministic)
    # P0-P3 for the B2B channel, S0-S3 for social commerce (each channel's own engine owns this column).
    qualification: Mapped[str] = mapped_column(String(4), default="P2", index=True)
    qualification_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    gates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    friction: Mapped[str] = mapped_column(String(20), default="unknown", index=True)  # low | moderate | high | unknown
    friction_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    buying_intent: Mapped[str] = mapped_column(String(20), default="unknown")  # explicit | buyer_confirmed | indirect | unknown
    solution: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    next_action: Mapped[str | None] = mapped_column(Text)
    disqualifier: Mapped[str | None] = mapped_column(Text)  # owner-entered
    # Workflow state
    review_status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    # new | shortlisted | approved | watchlist | rejected | duplicate
    research_level: Mapped[str] = mapped_column(String(20), default="directory")  # directory | website | deep
    researched_at: Mapped[datetime | None] = mapped_column(DateTime)
    research_error: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    prescore: Mapped[float] = mapped_column(Float, default=0.0)  # research order only
    outreach_draft: Mapped[str | None] = mapped_column(Text)
    outreach_approved_by: Mapped[str | None] = mapped_column(String(100))
    outreach_approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Which screen approved it for outreach when that isn't the channel's own (e.g. "website_recovery"); drives
    # the per-source sales comparison. None = the channel's normal approval.
    lead_source: Mapped[str | None] = mapped_column(String(30))
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    source_key: Mapped[str] = mapped_column(String(60))
    source_ref: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(2048))
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("ioi_companies.id", ondelete="SET NULL"))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)  # synthetic data, never shown with production records
    # 3.1 research engine
    research_error_kind: Mapped[str | None] = mapped_column(String(20))  # retryable | permanent
    research_retry_after: Mapped[datetime | None] = mapped_column(DateTime)
    operational_fit: Mapped[str] = mapped_column(String(10), default="unknown")  # strong | moderate | weak | unknown
    commercial_readiness: Mapped[str] = mapped_column(String(20), default="unknown")  # buyer_confirmed | limited_public | unknown
    evidence_quality: Mapped[str] = mapped_column(String(10), default="weak")  # strong | partial | weak
    scope_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # owner confirmed it's not an enterprise-procurement target
    ai_status: Mapped[str] = mapped_column(String(20), default="not_run")  # not_run | done | partial | unavailable | failed
    ai_researched_at: Mapped[datetime | None] = mapped_column(DateTime)
    dossier: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # explainability answers (deterministic)

    facts: Mapped[list["Fact"]] = relationship(back_populates="company", cascade="all, delete-orphan", passive_deletes=True,
                                               order_by="Fact.id")
    contacts: Mapped[list["CompanyContact"]] = relationship(back_populates="company", cascade="all, delete-orphan", passive_deletes=True,
                                                     order_by="CompanyContact.id")
    locations: Mapped[list["Location"]] = relationship(back_populates="company", cascade="all, delete-orphan", passive_deletes=True,
                                                       order_by="Location.id")
    people: Mapped[list["Person"]] = relationship(back_populates="company", cascade="all, delete-orphan", passive_deletes=True,
                                                  order_by="Person.id")
    # Social-commerce channel only (empty for B2B companies)
    social_accounts: Mapped[list["SocialAccount"]] = relationship(back_populates="company", cascade="all, delete-orphan",
                                                                  passive_deletes=True, order_by="SocialAccount.id")
    social_activity: Mapped[list["SocialActivity"]] = relationship(back_populates="company", cascade="all, delete-orphan",
                                                                   passive_deletes=True, order_by="SocialActivity.id")
    social: Mapped["SocialProfile | None"] = relationship(back_populates="company", cascade="all, delete-orphan",
                                                          passive_deletes=True, uselist=False)


class Location(Base):
    __tablename__ = "ioi_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(String(120))
    pincode: Mapped[str | None] = mapped_column(String(10))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))  # chennai_city | gcma_outside | outside | unknown
    reason: Mapped[str] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(String(20))  # directory | official_site | owner
    evidence_url: Mapped[str | None] = mapped_column(String(2048))
    excerpt: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped[Company] = relationship(back_populates="locations")


class Fact(Base):
    """One statement about a company with its evidence level.

    state: source_verified (seen in a source we link to) | inferred (our hypothesis) |
           buyer_confirmed (the buyer told us) | unknown (we explicitly don't know).
    kind:  identity | activity | workflow | problem | signal | tools | note
    Signals (kind=signal) also carry review_status: hypothesis (rule-detected) | confirmed | rejected.
    """

    __tablename__ = "ioi_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    statement: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), index=True)
    key: Mapped[str | None] = mapped_column(String(60))  # rule key, e.g. amc_warranty / explicit_software_request
    excerpt: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    source_name: Mapped[str | None] = mapped_column(String(120))
    reliability: Mapped[str] = mapped_column(String(10), default="medium")  # high | medium | low
    published_at: Mapped[datetime | None] = mapped_column(DateTime)  # when the source published it (NULL = unknown)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    detected_by: Mapped[str] = mapped_column(String(20), default="rule")  # rule | ai | owner | buyer
    review_status: Mapped[str | None] = mapped_column(String(20))  # signals only
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    # Where it came from and who said it. Public content is evidence of what it states, not proof it's true.
    source_type: Mapped[str | None] = mapped_column(String(30))  # directory | official_site | news | owner | buyer
    account_type: Mapped[str | None] = mapped_column(String(30))  # company_published | third_party | owner | buyer
    contradiction: Mapped[str | None] = mapped_column(Text)  # conflicting evidence, if any

    company: Mapped[Company] = relationship(back_populates="facts")


class CompanyContact(Base):
    __tablename__ = "ioi_contacts"
    __table_args__ = (UniqueConstraint("company_id", "kind", "value", name="uq_ioi_contact"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # phone | email | contact_form
    value: Mapped[str] = mapped_column(String(500))
    label: Mapped[str | None] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(String(2048))  # never NULL: no contact without provenance
    official: Mapped[bool] = mapped_column(Boolean, default=False)  # published on the company's own website
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped[Company] = relationship(back_populates="contacts")


class Activity(Base):
    """Outreach and sales history (all actions are performed by the owner; nothing is sent by IOI)."""

    __tablename__ = "ioi_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("ioi_deals.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    # approved | contacted | reply | call | follow_up | note | stage | proposal | payment | watchlist | rejected
    channel: Mapped[str | None] = mapped_column(String(20))  # phone | email | whatsapp | in_person | other
    summary: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(100), default="owner")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Deal(_Stamped, Base):
    __tablename__ = "ioi_deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("ioi_campaigns.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), unique=True)
    stage: Mapped[str] = mapped_column(String(30), default="new_prospect", index=True)
    outcome: Mapped[str | None] = mapped_column(String(30))  # not_interested | no_response | lost | follow_up_later
    outcome_reason: Mapped[str | None] = mapped_column(String(300))  # the owner's words: why it was lost / declined
    contact_name: Mapped[str | None] = mapped_column(String(200))
    confirmed_requirement: Mapped[str | None] = mapped_column(Text)
    offer: Mapped[str | None] = mapped_column(String(200))
    potential_amount: Mapped[int | None] = mapped_column(Integer)  # owner's rough estimate (never counted as revenue)
    quoted_amount: Mapped[int | None] = mapped_column(Integer)
    expected_payment_date: Mapped[date | None] = mapped_column(Date)
    delivery_status: Mapped[str | None] = mapped_column(String(60))
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    payments: Mapped[list["Payment"]] = relationship(back_populates="deal", cascade="all, delete-orphan", passive_deletes=True,
                                                     order_by="Payment.received_on")
    company: Mapped[Company] = relationship()


class Payment(Base):
    """Money actually received. The only thing that counts as collected revenue."""

    __tablename__ = "ioi_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("ioi_deals.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer)  # rupees, > 0
    kind: Mapped[str] = mapped_column(String(20))  # advance | milestone | final
    received_on: Mapped[date] = mapped_column(Date, index=True)
    reference: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    deal: Mapped[Deal] = relationship(back_populates="payments")


class Proposal(_Stamped, Base):
    __tablename__ = "ioi_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("ioi_deals.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    scope: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[int | None] = mapped_column(Integer)  # rupees, as quoted by the owner
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | sent | accepted | declined
    sent_on: Mapped[date | None] = mapped_column(Date)


class Person(Base):
    """A publicly published business role (owner, MD, service manager…) on an official/public page.

    Only professional facts that the page itself states, with the verbatim quote. A contact route is kept
    only when published on the same page; nothing is guessed.
    """

    __tablename__ = "ioi_people"
    __table_args__ = (UniqueConstraint("company_id", "name", "role", name="uq_ioi_person"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(120))
    role_group: Mapped[str] = mapped_column(String(30))  # owner | leadership | operations | service | sales | other
    excerpt: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(2048))
    published_contact: Mapped[str | None] = mapped_column(String(300))  # only if on the same page
    detected_by: Mapped[str] = mapped_column(String(20), default="rule")  # rule | ai | owner
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped[Company] = relationship(back_populates="people")


class PageCache(Base):
    """Cached public page responses (respecting ETag / Last-Modified) to avoid repeated fetches."""

    __tablename__ = "ioi_page_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    final_url: Mapped[str] = mapped_column(String(2048))
    status_code: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(200))
    etag: Mapped[str | None] = mapped_column(String(300))
    last_modified: Mapped[str | None] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    validated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentEvent(Base):
    """Audit trail of the research agent: every model step and tool call (arguments redacted)."""

    __tablename__ = "ioi_agent_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    session: Mapped[str] = mapped_column(String(40), index=True)  # one research session (uuid)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("ioi_jobs.id", ondelete="SET NULL"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    step: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(20))  # start | model | tool | finish | fallback | error | limit
    tool: Mapped[str | None] = mapped_column(String(60))
    args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | rejected | failed | skipped
    message: Mapped[str] = mapped_column(Text)  # plain-language description of what actually happened
    model: Mapped[str | None] = mapped_column(String(120))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    evidence_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ------------------------------------------------------------------------------------------------
# Social commerce (channel = social_commerce). Shared identity, contacts, evidence, outreach,
# deals and payments stay in the tables above; only social-specific facts live here.
# ------------------------------------------------------------------------------------------------
class SocialAccount(Base):
    """One public platform account belonging to a seller, with the page that evidences it.

    Follower counts are recorded when a public profile states them, but never affect qualification
    or scoring: popularity is not revenue, budget or buying intent.
    """

    __tablename__ = "ioi_social_accounts"
    __table_args__ = (UniqueConstraint("company_id", "platform", "handle", name="uq_ioi_social_account"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)  # instagram | facebook | whatsapp | other
    handle: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2048))
    profile_name: Mapped[str | None] = mapped_column(String(300))
    account_kind: Mapped[str] = mapped_column(String(20), default="unknown")  # business | creator | page | personal | unknown
    catalogue_url: Mapped[str | None] = mapped_column(String(2048))
    bio_excerpt: Mapped[str | None] = mapped_column(Text)
    followers: Mapped[int | None] = mapped_column(Integer)  # recorded only; never scored
    last_post_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    # Provenance: where we saw that this account belongs to this business.
    source_url: Mapped[str] = mapped_column(String(2048))
    excerpt: Mapped[str | None] = mapped_column(Text)
    reachable: Mapped[str] = mapped_column(String(20), default="unknown")  # public | restricted | not_found | unknown
    detected_by: Mapped[str] = mapped_column(String(20), default="rule")  # rule | ai | owner
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped["Company"] = relationship(back_populates="social_accounts")


class SocialActivity(Base):
    """A dated, publicly visible business signal from a permitted source.

    `indicator_class` separates what the post *shows* (activity) from what it only *suggests*
    (demand_indicator). Neither is proof of sales, order volume, revenue or budget.
    """

    __tablename__ = "ioi_social_activity"
    __table_args__ = (
        UniqueConstraint("company_id", "url", "signal_type", name="uq_ioi_social_activity"),
        Index("ix_ioi_social_activity_company_published", "company_id", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("ioi_social_accounts.id", ondelete="SET NULL"))
    platform: Mapped[str | None] = mapped_column(String(20))
    signal_type: Mapped[str] = mapped_column(String(40), index=True)
    indicator_class: Mapped[str] = mapped_column(String(20), default="activity")  # activity | demand_indicator
    statement: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(2048))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)  # NULL = the source showed no date
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    state: Mapped[str] = mapped_column(String(20), default="source_verified")  # source_verified | inferred | unknown
    reliability: Mapped[str] = mapped_column(String(10), default="medium")  # high | medium | low
    source_name: Mapped[str | None] = mapped_column(String(120))
    detected_by: Mapped[str] = mapped_column(String(20), default="rule")  # rule | ai | owner
    review_status: Mapped[str | None] = mapped_column(String(20))  # hypothesis | confirmed | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped["Company"] = relationship(back_populates="social_activity")


class SocialProfile(_Stamped, Base):
    """The social-commerce assessment of one seller (one row per company in the social channel).

    The S0-S3 category, gates, score and solution are written to the shared `ioi_companies` columns
    so outreach, approval and the sales pipeline work unchanged; this table holds what is specific
    to selling through social platforms.
    """

    __tablename__ = "ioi_social_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), unique=True, index=True)
    # What they sell
    product_category: Mapped[str | None] = mapped_column(String(40), index=True)
    # fashion_boutique | custom_gifts | home_bakery | meal_subscription | other_social
    category_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    products_excerpt: Mapped[str | None] = mapped_column(Text)
    # Where they operate (social sellers often have no storefront)
    geo_confidence: Mapped[str] = mapped_column(String(20), default="unclear", index=True)
    # verified_chennai | probable_chennai | unclear | outside_chennai
    geo_reason: Mapped[str | None] = mapped_column(Text)
    geo_basis: Mapped[str | None] = mapped_column(String(30))  # profile_address | delivery_area | pickup_point | event_listing | official_site | owner
    geo_evidence_url: Mapped[str | None] = mapped_column(String(2048))
    geo_excerpt: Mapped[str | None] = mapped_column(Text)
    # How they sell today
    sales_setup: Mapped[str] = mapped_column(String(30), default="unknown")
    # social_only | social_whatsapp | social_simple_site | social_full_ecommerce | marketplace_led | multi_channel | unknown
    sales_setup_reason: Mapped[str | None] = mapped_column(Text)
    order_channels: Mapped[list[str]] = mapped_column(JSON, default=list)  # dm | whatsapp | phone | form | website_cart | marketplace
    known_tools: Mapped[list[str]] = mapped_column(JSON, default=list)  # order/inventory software named on a public page
    workflow_gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Operational complexity — indicators that a workflow tool may be relevant, not proof of a problem
    complexity_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    complexity_level: Mapped[str] = mapped_column(String(20), default="unknown")  # high | moderate | low | unknown
    # Evidence-based operational maturity (never a financial judgement)
    maturity: Mapped[str] = mapped_column(String(30), default="activity_unclear", index=True)
    # growing_operational | established_social | early_stage | activity_unclear | inactive_unverified
    maturity_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime)
    activity_count: Mapped[int] = mapped_column(Integer, default=0)
    demand_indicator_count: Mapped[int] = mapped_column(Integer, default=0)
    # Research state (separate from the B2B website research on ioi_companies)
    research_level: Mapped[str] = mapped_column(String(20), default="profile")  # profile | public | deep
    researched_at: Mapped[datetime | None] = mapped_column(DateTime)
    research_error: Mapped[str | None] = mapped_column(Text)
    research_error_kind: Mapped[str | None] = mapped_column(String(20))  # retryable | permanent
    research_retry_after: Mapped[datetime | None] = mapped_column(DateTime)
    pages_checked: Mapped[list[str]] = mapped_column(JSON, default=list)

    company: Mapped["Company"] = relationship(back_populates="social")


class WebsiteCheck(Base):
    """One low-impact health check of a company's own website (Website Recovery).

    Stores classification and short error text only, never the page HTML. History is kept, so a failure
    can be confirmed by a later recheck and a recovery is never erased.
    """

    __tablename__ = "ioi_website_checks"
    __table_args__ = (Index("ix_ioi_web_check_company_time", "company_id", "checked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    website_url: Mapped[str] = mapped_column(String(2048))
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    method: Mapped[str] = mapped_column(String(40), default="http_get_v1")
    dns_result: Mapped[str] = mapped_column(String(20))  # ok | unresolved | policy_blocked
    http_status: Mapped[int | None] = mapped_column(Integer)
    final_url: Mapped[str | None] = mapped_column(String(2048))
    tls_result: Mapped[str | None] = mapped_column(String(20))  # ok | problem | None (not reached)
    error_kind: Mapped[str | None] = mapped_column(String(20))  # timeout | refused | tls | robots | other
    error_text: Mapped[str | None] = mapped_column(String(300))
    observed_class: Mapped[str | None] = mapped_column(String(40))  # the specific failure seen this time
    status: Mapped[str] = mapped_column(String(40), index=True)  # overall Website Recovery status
    confidence: Mapped[str] = mapped_column(String(10))  # high | medium | low
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)


class ActivityEvidence(Base):
    """Dated evidence that a business is (or is not) still operating. Website Recovery, brief section 6.

    `method` keeps owner observations (manual) apart from automatically verified facts. `published_on` is when the
    source published it (never a crawl date); `observed_on` is when it was seen. Business facts only: free text is
    screened for phone numbers and email addresses before it is stored.
    """

    __tablename__ = "ioi_activity_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # phone_call | official_social | marketplace_listing | official_website | news | other | confirmed_need
    signal: Mapped[str] = mapped_column(String(20))  # active | inactive | closed
    statement: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    published_on: Mapped[date | None] = mapped_column(Date)
    observed_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(20), default="manual")  # manual | automatic
    recorded_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AlternativeSite(Base):
    """A possible newer website for a business whose listed site is failing (found from its own email domain or
    directory record), with the result of one health check."""

    __tablename__ = "ioi_alt_sites"
    __table_args__ = (UniqueConstraint("company_id", "url", name="uq_ioi_alt_site"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ioi_companies.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    found_via: Mapped[str] = mapped_column(String(40))  # email_domain | directory_listing
    status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(300))
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ContactReview(Base):
    """The owner's decision on a contact that needs review (e.g. a directory mobile that may be a person's own
    number). Only approved contacts pass the Website Recovery contact gate. Additive: ioi_contacts is untouched."""

    __tablename__ = "ioi_contact_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("ioi_contacts.id", ondelete="CASCADE"), unique=True, index=True)
    decision: Mapped[str] = mapped_column(String(20))  # approved | rejected
    note: Mapped[str | None] = mapped_column(String(200))
    reviewed_by: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
