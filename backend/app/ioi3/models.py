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


class _Stamped:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Campaign(_Stamped, Base):
    __tablename__ = "ioi_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), default="Chennai")
    industries: Mapped[list[str]] = mapped_column(JSON, default=list)  # equipment_service | wholesale_distribution
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
    qualification: Mapped[str] = mapped_column(String(4), default="P2", index=True)  # P0 | P1 | P2 | P3
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
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    source_key: Mapped[str] = mapped_column(String(60))
    source_ref: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(2048))
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("ioi_companies.id", ondelete="SET NULL"))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)  # synthetic data, never shown with production records

    facts: Mapped[list["Fact"]] = relationship(back_populates="company", cascade="all, delete-orphan", passive_deletes=True,
                                               order_by="Fact.id")
    contacts: Mapped[list["CompanyContact"]] = relationship(back_populates="company", cascade="all, delete-orphan", passive_deletes=True,
                                                     order_by="CompanyContact.id")
    locations: Mapped[list["Location"]] = relationship(back_populates="company", cascade="all, delete-orphan", passive_deletes=True,
                                                       order_by="Location.id")


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
