"""Domain vocabularies. Stored as plain strings in the database for migration simplicity."""

from enum import StrEnum


class Pipeline(StrEnum):
    DIRECT = "A_direct"  # Pipeline A — direct buyers
    VENDOR = "B_vendor"  # Pipeline B — vendor / subcontracting
    CHAIN = "C_chain"  # Pipeline C — opportunity chain intelligence
    NONE = "none"


class Category(StrEnum):
    DIRECT_SOFTWARE_PROJECT = "direct_software_project"
    VENDOR_ONBOARDING = "vendor_onboarding"
    SUBCONTRACTING = "subcontracting"
    IMPLEMENTATION_PARTNERSHIP = "implementation_partnership"
    GOVERNMENT_TENDER = "government_tender"
    PRIVATE_PROCUREMENT = "private_procurement"
    WEAK_BUYING_SIGNAL = "weak_buying_signal"
    GENERAL_ORGANISATION = "general_organisation"
    IRRELEVANT = "irrelevant"
    UNKNOWN = "unknown"


CATEGORY_PIPELINE: dict[Category, Pipeline] = {
    Category.DIRECT_SOFTWARE_PROJECT: Pipeline.DIRECT,
    Category.WEAK_BUYING_SIGNAL: Pipeline.DIRECT,
    Category.VENDOR_ONBOARDING: Pipeline.VENDOR,
    Category.SUBCONTRACTING: Pipeline.VENDOR,
    Category.IMPLEMENTATION_PARTNERSHIP: Pipeline.VENDOR,
    Category.GOVERNMENT_TENDER: Pipeline.VENDOR,
    Category.PRIVATE_PROCUREMENT: Pipeline.VENDOR,
    Category.GENERAL_ORGANISATION: Pipeline.CHAIN,
    Category.IRRELEVANT: Pipeline.NONE,
    Category.UNKNOWN: Pipeline.NONE,
}


class OpportunityStatus(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    RESEARCHING = "researching"
    QUALIFIED = "qualified"
    OUTREACH = "outreach"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


class EligibilityOutcome(StrEnum):
    ELIGIBLE = "eligible"
    POTENTIALLY_ELIGIBLE = "potentially_eligible"
    NOT_ELIGIBLE = "not_eligible"
    PARTNER_ROUTE = "partner_route"
    UNCLEAR = "unclear"
    UNKNOWN = "unknown"


class EligibilityScope(StrEnum):
    PROJECT = "project"
    VENDOR_REGISTRATION = "vendor_registration"


class RequirementKey(StrEnum):
    COUNTRY_RESTRICTION = "country_restriction"
    INDIA_PROVIDERS_ACCEPTED = "india_providers_accepted"
    LEGAL_ENTITY = "legal_entity"
    PROPRIETORSHIP_ACCEPTANCE = "proprietorship_acceptance"
    GST = "gst"
    PAN = "pan"
    UDYAM_MSME = "udyam_msme"
    MIN_TURNOVER = "min_turnover"
    PRIOR_EXPERIENCE = "prior_experience"
    SIMILAR_WORK_CERTIFICATES = "similar_work_certificates"
    WORKFORCE = "workforce"
    TECHNICAL_CERTIFICATIONS = "technical_certifications"
    SECURITY_CERTIFICATIONS = "security_certifications"
    INSURANCE = "insurance"
    EMD = "emd"
    DIGITAL_SIGNATURE = "digital_signature"
    REGISTRATION_FEE = "registration_fee"
    TAX_INVOICING = "tax_invoicing"
    SUBCONTRACTING_PERMISSION = "subcontracting_permission"
    CONSORTIUM_PERMISSION = "consortium_permission"
    VENDOR_REGISTRATION = "vendor_registration"
    PROJECT_RESTRICTION = "project_restriction"


class RequirementStatus(StrEnum):
    SATISFIED = "satisfied"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CLARIFY = "clarify"


class ScoreType(StrEnum):
    DIRECT = "direct_client"
    VENDOR = "vendor_subcontracting"
    CHAIN = "chain_potential"


class VerificationStatus(StrEnum):
    CONFIRMED = "confirmed"
    HYPOTHESIS = "hypothesis"
    REJECTED = "rejected"


class OrgRelationshipType(StrEnum):
    PARTNER_PROGRAMME = "partner_programme"
    IMPLEMENTATION_PARTNER = "implementation_partner"
    VENDOR_OF = "vendor_of"
    CUSTOMER_OF = "customer_of"
    CONTRACTOR_FOR = "contractor_for"
    TECHNOLOGY_PROVIDER = "technology_provider"
    ANNOUNCED_PROJECT = "announced_project"
    REFERRAL_ROUTE = "referral_route"
    BRANCH_OR_DIVISION = "branch_or_division"
    AWARDED_CONTRACT = "awarded_contract"


class OppRelationshipType(StrEnum):
    SAME_BUYER = "same_buyer"
    REPEAT_PROJECT = "repeat_project"
    RELATED_REQUIREMENT = "related_requirement"
    CROSS_SELL = "cross_sell"
    DUPLICATE_OF = "duplicate_of"


class ConnectorStatus(StrEnum):
    LIVE = "live"
    CREDENTIAL_GATED = "credential_gated"
    MANUAL = "manual"
    PLANNED = "planned"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class ResearchStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class DraftStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT_MANUALLY = "sent_manually"


class CallOutcome(StrEnum):
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    CALL_BACK = "call_back"
    WRONG_CONTACT = "wrong_contact"
    EXISTING_VENDOR = "existing_vendor"
    WANTS_COMPANY_PROFILE = "wants_company_profile"
    WANTS_PROPOSAL = "wants_proposal"
    SHARED_VENDOR_DETAILS = "shared_vendor_details"
    NO_ANSWER = "no_answer"


class ContactType(StrEnum):
    EMAIL = "official_email"
    CONTACT_PAGE = "contact_page"
    PHONE = "published_phone"
    VENDOR_PORTAL = "vendor_onboarding_page"
    DECISION_MAKER = "decision_maker"
    PLATFORM_THREAD = "platform_thread"  # e.g. reply on the original public post


class TaskStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"
