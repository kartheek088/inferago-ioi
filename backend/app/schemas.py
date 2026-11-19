"""Pydantic request/response schemas."""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.enums import CallOutcome, ContactType, EligibilityScope, OppRelationshipType, OpportunityStatus, OrgRelationshipType, RequirementKey, VerificationStatus

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# --- Sources ----------------------------------------------------------------------------------


class SourceOut(ORM):
    id: int
    key: str
    name: str
    base_url: str | None
    country: str | None
    region: str | None
    category: str
    access_method: str
    connector: str | None
    api_auth_requirements: str | None
    terms_notes: str | None
    collection_frequency_minutes: int | None
    rate_limit_per_minute: int
    max_items_per_run: int
    last_checked_at: datetime | None
    last_success_at: datetime | None
    failure_status: str | None
    consecutive_failures: int
    enabled: bool
    schedule_enabled: bool
    coverage: str | None
    connector_status: str
    config: dict[str, Any]


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    schedule_enabled: bool | None = None
    collection_frequency_minutes: int | None = Field(None, ge=15, le=10080)
    rate_limit_per_minute: int | None = Field(None, ge=1, le=600)
    max_items_per_run: int | None = Field(None, ge=1, le=500)
    config: dict[str, Any] | None = None


class SourceCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{3,60}$")
    name: str = Field(min_length=2, max_length=200)
    feed_url: HttpUrl
    country: str | None = None
    region: str | None = None
    terms_notes: str | None = None
    collection_frequency_minutes: int = Field(360, ge=15, le=10080)
    require_term_match: bool = True


class SourceRunOut(ORM):
    id: int
    source_id: int
    discovery_job_id: int | None
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    items_fetched: int
    items_new: int
    items_duplicate: int
    items_rejected: int
    requests_made: int
    error_message: str | None
    log: list[str]


class DiscoveryJobIn(BaseModel):
    source_keys: list[str] = Field(min_length=1, max_length=20)
    query_terms: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("query_terms")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return [t.strip()[:100] for t in v if t.strip()]


class DiscoveryJobOut(ORM):
    id: int
    trigger: str
    query_terms: list[str]
    source_keys: list[str]
    status: str
    stats: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None


class UrlImportIn(BaseModel):
    url: HttpUrl
    organisation_name: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=2000)


class ImportOut(BaseModel):
    status: str
    opportunity_id: int | None
    reason: str | None = None
    document: dict[str, Any] | None = None


# --- Organisations / opportunities ------------------------------------------------------------


class OrganisationOut(ORM):
    id: int
    name: str
    normalized_name: str
    domain: str | None
    domain_verified: bool
    website: str | None
    country: str | None
    region: str | None
    industry: str | None
    org_type: str | None
    description: str | None
    accepts_external_vendors: bool | None
    is_demo: bool
    created_at: datetime


class OrganisationUpdate(BaseModel):
    name: str | None = Field(None, max_length=300)
    website: HttpUrl | None = None
    country: str | None = None
    region: str | None = None
    industry: str | None = None
    org_type: str | None = None
    description: str | None = None
    accepts_external_vendors: bool | None = None


class ScoreOut(ORM):
    score_type: str
    raw_total: float
    effective_total: float
    disqualified: bool
    unknown_components: int
    components: list[dict[str, Any]]
    explanation: str


class OpportunityOut(ORM):
    id: int
    title: str
    summary: str | None
    pipeline: str
    category: str
    classification_confidence: float
    classification_method: str
    classification_evidence: list[str]
    services_matched: list[str]
    signals_matched: list[str]
    organisation_id: int | None
    organisation_name: str | None = None
    country: str | None
    region: str | None
    geography_basis: str | None
    remote_ok: bool | None
    canonical_url: str | None
    source_id: int | None
    source_key: str | None = None
    status: str
    published_at: datetime | None
    retrieved_at: datetime | None
    deadline: datetime | None
    budget_text: str | None
    priority: float | None
    eligibility_outcome: str | None
    research_status: str | None
    needs_manual_review: bool
    is_demo: bool
    created_at: datetime
    scores: list[ScoreOut] = []


class OpportunityDetail(OpportunityOut):
    description: str | None
    merged_into_id: int | None


class OpportunityUpdate(BaseModel):
    status: OpportunityStatus | None = None
    country: str | None = None
    region: str | None = None
    organisation_id: int | None = None


class EvidenceOut(ORM):
    id: int
    opportunity_id: int | None
    organisation_id: int | None
    raw_record_id: int | None
    source_id: int | None
    evidence_type: str
    url: str | None
    excerpt: str
    page_reference: str | None
    document_name: str | None
    published_at: datetime | None
    retrieved_at: datetime


class ContactOut(ORM):
    id: int
    organisation_id: int | None
    opportunity_id: int | None
    contact_type: str
    value: str
    label: str | None
    person_name: str | None
    role: str | None
    source_url: str
    verified: bool
    verification_method: str | None
    verification_date: datetime | None
    notes: str | None


class ContactIn(BaseModel):
    organisation_id: int | None = None
    opportunity_id: int | None = None
    contact_type: ContactType
    value: str = Field(min_length=3, max_length=500)
    label: str | None = None
    person_name: str | None = Field(None, max_length=200)
    role: str | None = Field(None, max_length=200)
    source_url: HttpUrl  # where it was published — mandatory
    verified: bool = False
    notes: str | None = None


class BuyingSignalOut(ORM):
    id: int
    signal_type: str
    strength: str
    text: str
    evidence_id: int | None


class RequirementOut(ORM):
    id: int
    opportunity_id: int
    scope: str
    requirement_key: str
    mandatory: bool
    text: str
    parameters: dict[str, Any]
    origin: str
    evidence_id: int | None
    page_reference: str | None


class RequirementIn(BaseModel):
    scope: EligibilityScope = EligibilityScope.PROJECT
    requirement_key: RequirementKey
    mandatory: bool = True
    text: str = Field(min_length=3, max_length=2000)
    parameters: dict[str, Any] = {}
    page_reference: str | None = None


class AssessmentOut(ORM):
    id: int
    opportunity_id: int
    scope: str
    outcome: str
    reason: str
    evidence: list[dict[str, Any]]
    satisfied: list[dict[str, Any]]
    missing: list[dict[str, Any]]
    mandatory_failures: list[dict[str, Any]]
    clarifications: list[str]
    next_action: str
    engine_version: str
    created_at: datetime


class OrgRelationshipOut(ORM):
    id: int
    source_org_id: int
    source_org_name: str | None = None
    target_org_id: int | None
    target_org_name: str | None = None
    target_opportunity_id: int | None
    target_label: str | None
    relationship_type: str
    evidence_url: str
    evidence_excerpt: str
    confidence: float
    verification_status: str
    discovered_at: datetime
    verified_at: datetime | None
    origin: str


class OrgRelationshipIn(BaseModel):
    source_org_id: int
    target_org_id: int | None = None
    target_opportunity_id: int | None = None
    target_label: str | None = Field(None, max_length=300)
    relationship_type: OrgRelationshipType
    evidence_url: HttpUrl
    evidence_excerpt: str = Field(min_length=10, max_length=5000)
    confidence: float = Field(ge=0, le=1)
    verification_status: VerificationStatus = VerificationStatus.HYPOTHESIS


class OppRelationshipOut(ORM):
    id: int
    source_opportunity_id: int
    target_opportunity_id: int
    relationship_type: str
    evidence_url: str
    evidence_excerpt: str
    confidence: float
    verification_status: str
    discovered_at: datetime


class OppRelationshipIn(BaseModel):
    source_opportunity_id: int
    target_opportunity_id: int
    relationship_type: OppRelationshipType
    evidence_url: HttpUrl
    evidence_excerpt: str = Field(min_length=10, max_length=5000)
    confidence: float = Field(ge=0, le=1)
    verification_status: VerificationStatus = VerificationStatus.HYPOTHESIS


class VerificationIn(BaseModel):
    verification_status: VerificationStatus


class ResearchTaskOut(ORM):
    id: int
    opportunity_id: int
    status: str
    priority: float
    depth: str
    request_budget: int
    requests_used: int
    ai_calls_used: int
    tokens_used: int
    findings: dict[str, Any]
    brief: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


# --- Outreach ---------------------------------------------------------------------------------


class DraftOut(ORM):
    id: int
    opportunity_id: int
    contact_id: int | None
    status: str
    generated_by: str
    company_background: str
    why_shortlisted: str
    buying_signal: str
    evidence_links: list[str]
    relevant_capability: str
    contact_route: str
    call_opening: str
    discovery_questions: list[str]
    likely_objections: list[str]
    email_subject: str
    email_body: str
    recommended_next_action: str
    sent_manually_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DraftUpdate(BaseModel):
    email_subject: str | None = Field(None, max_length=300)
    email_body: str | None = Field(None, max_length=10000)
    call_opening: str | None = Field(None, max_length=2000)
    discovery_questions: list[str] | None = None
    likely_objections: list[str] | None = None
    recommended_next_action: str | None = None


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    decided_by: str = Field(min_length=1, max_length=100)
    note: str | None = Field(None, max_length=2000)


class ApprovalOut(ORM):
    id: int
    draft_id: int
    decision: str
    decided_by: str
    note: str | None
    decided_at: datetime


class CallTaskIn(BaseModel):
    opportunity_id: int
    contact_id: int | None = None
    draft_id: int | None = None
    scheduled_for: datetime | None = None


class CallTaskOut(ORM):
    id: int
    opportunity_id: int
    contact_id: int | None
    draft_id: int | None
    status: str
    scheduled_for: datetime | None
    outcome: str | None
    notes: str | None
    completed_at: datetime | None
    created_at: datetime


class CallOutcomeIn(BaseModel):
    outcome: CallOutcome
    notes: str | None = Field(None, max_length=4000)
    follow_up_date: datetime | None = None


class FollowUpOut(ORM):
    id: int
    opportunity_id: int
    call_task_id: int | None
    action: str
    reason: str | None
    due_date: datetime | None
    status: str
    created_at: datetime
    completed_at: datetime | None


class FollowUpIn(BaseModel):
    opportunity_id: int
    action: str = Field(min_length=3, max_length=1000)
    due_date: datetime | None = None
    reason: str | None = None


class FollowUpUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(open|done|cancelled)$")
    due_date: datetime | None = None


class ActivityOut(ORM):
    id: int
    entity_type: str
    entity_id: int | None
    action: str
    actor: str
    detail: dict[str, Any]
    created_at: datetime


class SettingsUpdate(BaseModel):
    search_terms: list[str] | None = Field(None, max_length=100)
    country_priorities: list[dict[str, Any]] | None = None
    research_budget: dict[str, Any] | None = None
    profile_overrides: dict[str, Any] | None = None


class ActionOut(ORM):
    id: int
    title: str
    detail: str | None
    url: str | None
    opportunity_id: int | None
    category: str
    due_date: datetime | None
    status: str
    sort_order: int
    created_at: datetime
    completed_at: datetime | None


class ActionIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    detail: str | None = Field(None, max_length=4000)
    url: str | None = Field(None, max_length=2048, pattern=r"^(https?://|/)")
    opportunity_id: int | None = None
    category: str = Field("general", max_length=40)
    due_date: datetime | None = None


class ActionUpdate(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=300)
    detail: str | None = Field(None, max_length=4000)
    status: str | None = Field(None, pattern="^(open|done|cancelled)$")
    due_date: datetime | None = None
