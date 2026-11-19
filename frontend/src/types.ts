export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ScoreComponent {
  name: string;
  max: number;
  value: number;
  known: boolean;
  explanation: string;
}

export interface Score {
  score_type: "direct_client" | "vendor_subcontracting" | "chain_potential";
  raw_total: number;
  effective_total: number;
  disqualified: boolean;
  unknown_components: number;
  components: ScoreComponent[];
  explanation: string;
}

export interface Opportunity {
  id: number;
  title: string;
  summary: string | null;
  description?: string | null;
  pipeline: string;
  category: string;
  classification_confidence: number;
  classification_method: string;
  classification_evidence: string[];
  services_matched: string[];
  signals_matched: string[];
  organisation_id: number | null;
  organisation_name: string | null;
  country: string | null;
  region: string | null;
  geography_basis: string | null;
  remote_ok: boolean | null;
  canonical_url: string | null;
  source_id: number | null;
  source_key: string | null;
  status: string;
  published_at: string | null;
  retrieved_at: string | null;
  deadline: string | null;
  budget_text: string | null;
  priority: number | null;
  eligibility_outcome: string | null;
  research_status: string | null;
  needs_manual_review: boolean;
  is_demo: boolean;
  created_at: string;
  merged_into_id?: number | null;
  scores: Score[];
}

export interface Organisation {
  id: number;
  name: string;
  domain: string | null;
  domain_verified: boolean;
  website: string | null;
  country: string | null;
  region: string | null;
  industry: string | null;
  org_type: string | null;
  description: string | null;
  accepts_external_vendors: boolean | null;
  is_demo: boolean;
  created_at: string;
}

export interface Evidence {
  id: number;
  opportunity_id: number | null;
  organisation_id: number | null;
  raw_record_id: number | null;
  source_id: number | null;
  evidence_type: string;
  url: string | null;
  excerpt: string;
  page_reference: string | null;
  document_name: string | null;
  published_at: string | null;
  retrieved_at: string;
}

export interface Contact {
  id: number;
  organisation_id: number | null;
  opportunity_id: number | null;
  contact_type: string;
  value: string;
  label: string | null;
  person_name: string | null;
  role: string | null;
  source_url: string;
  verified: boolean;
  verification_method: string | null;
  verification_date: string | null;
  notes: string | null;
}

export interface Requirement {
  id: number;
  scope: string;
  requirement_key: string;
  mandatory: boolean;
  text: string;
  parameters: Record<string, unknown>;
  origin: string;
  evidence_id: number | null;
  page_reference: string | null;
}

export interface ReqEval {
  key: string;
  status: string;
  reason: string;
  mandatory: boolean;
  text: string;
  page_reference: string | null;
}

export interface Assessment {
  id: number;
  opportunity_id: number;
  scope: string;
  outcome: string;
  reason: string;
  satisfied: ReqEval[];
  missing: ReqEval[];
  mandatory_failures: ReqEval[];
  clarifications: string[];
  next_action: string;
  created_at: string;
}

export interface OrgRelationship {
  id: number;
  source_org_id: number;
  source_org_name: string | null;
  target_org_id: number | null;
  target_org_name: string | null;
  target_opportunity_id: number | null;
  target_label: string | null;
  relationship_type: string;
  evidence_url: string;
  evidence_excerpt: string;
  confidence: number;
  verification_status: string;
  discovered_at: string;
  origin: string;
}

export interface Source {
  id: number;
  key: string;
  name: string;
  base_url: string | null;
  country: string | null;
  region: string | null;
  category: string;
  access_method: string;
  connector: string | null;
  api_auth_requirements: string | null;
  terms_notes: string | null;
  collection_frequency_minutes: number | null;
  rate_limit_per_minute: number;
  max_items_per_run: number;
  last_checked_at: string | null;
  last_success_at: string | null;
  failure_status: string | null;
  consecutive_failures: number;
  enabled: boolean;
  schedule_enabled: boolean;
  coverage: string | null;
  connector_status: string;
  config: Record<string, unknown>;
}

export interface SourceRun {
  id: number;
  source_id: number;
  discovery_job_id: number | null;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  items_fetched: number;
  items_new: number;
  items_duplicate: number;
  items_rejected: number;
  requests_made: number;
  error_message: string | null;
  log: string[];
}

export interface DiscoveryJob {
  id: number;
  trigger: string;
  query_terms: string[];
  source_keys: string[];
  status: string;
  stats: { new?: number; duplicate?: number; rejected?: number; failed_sources?: { source: string; error: string }[]; runs?: number[]; error?: string };
  created_at: string;
  finished_at: string | null;
}

export interface ResearchTask {
  id: number;
  opportunity_id: number;
  status: string;
  priority: number;
  request_budget: number;
  requests_used: number;
  ai_calls_used: number;
  tokens_used: number;
  findings: { steps?: string[]; contacts_found?: number; relationships_found?: number; domain_verified?: boolean };
  brief: string | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface Draft {
  id: number;
  opportunity_id: number;
  contact_id: number | null;
  status: string;
  generated_by: string;
  company_background: string;
  why_shortlisted: string;
  buying_signal: string;
  evidence_links: string[];
  relevant_capability: string;
  contact_route: string;
  call_opening: string;
  discovery_questions: string[];
  likely_objections: string[];
  email_subject: string;
  email_body: string;
  recommended_next_action: string;
  sent_manually_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CallTask {
  id: number;
  opportunity_id: number;
  contact_id: number | null;
  draft_id: number | null;
  status: string;
  scheduled_for: string | null;
  outcome: string | null;
  notes: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface FollowUp {
  id: number;
  opportunity_id: number;
  call_task_id: number | null;
  action: string;
  reason: string | null;
  due_date: string | null;
  status: string;
  created_at: string;
}

export interface Activity {
  id: number;
  entity_type: string;
  entity_id: number | null;
  action: string;
  actor: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface ActionItem {
  id: number;
  title: string;
  detail: string | null;
  url: string | null;
  opportunity_id: number | null;
  category: string;
  due_date: string | null;
  status: string;
  sort_order: number;
  created_at: string;
  completed_at: string | null;
}
