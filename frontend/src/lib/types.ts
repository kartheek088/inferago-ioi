export type Qual = "P0" | "P1" | "P2" | "P3";
export interface Signal { label: string; date: string | null; url: string | null; confirmed: boolean }
export interface CompanyCard {
  id: number; name: string; industry: string | null; industry_subtype: string | null; locality: string | null;
  location_confidence: "verified" | "partial" | "unknown" | "outside"; description: string | null; qualification: Qual;
  qualification_reasons: string[]; score: number; friction: string; review_status: string; buying_intent: string;
  offer: string | null; next_action: string | null; latest_signal: Signal | null; website: string | null; research_level: string;
  has_contact: boolean; official_contact: boolean; sources: number; sales_ready: boolean; next_follow_up_at: string | null; is_test: boolean;
  operational_fit: string; evidence_quality: string; commercial_readiness: string; ai_status: string; researched_at: string | null;
}
export interface AgentEvent {
  id: number; session: string; company_id: number | null; job_id: number | null; step: number; kind: string; tool: string | null;
  args: Record<string, unknown>; status: string; message: string; model: string | null; duration_ms: number | null;
  tokens_in: number | null; tokens_out: number | null; cost_usd: number | null; at: string;
}
export interface Person { id: number; name: string; role: string; role_group: string; excerpt: string; source_url: string; published_contact: string | null; detected_by: string; verified_at: string }
export interface AIUsage { calls: number; tokens_in: number; tokens_out: number; cost_usd: number }
export interface AIStatus {
  configured: boolean; provider: string | null; model: string | null; agent_supported: boolean; note: string | null;
  last_success: { at: string; task: string; model: string } | null; last_error: { at: string; task: string; error: string } | null;
  fallback: string; usage_24h: AIUsage; usage_30d: AIUsage; limits: Record<string, number>;
}
export interface Fact {
  id: number; kind: string; key: string | null; statement: string; state: "source_verified" | "inferred" | "buyer_confirmed" | "unknown";
  excerpt: string | null; source_url: string | null; source_name: string | null; reliability: string; published_at: string | null;
  observed_at: string; detected_by: string; review_status: string | null; reviewed_by: string | null; label: string | null;
}
export interface Gate { key: string; label: string; passed: boolean | null; detail: string }
export interface ScorePart { key: string; label: string; points: number; max: number; why: string }
export interface SoftwareOption { name: string; url: string; category: string; solves: string; burden: string; inferago_role: string }
export interface Solution {
  existing_software?: { note: string; already_mentioned: string[]; options: SoftwareOption[] };
  offer: string | null; level: number | null; level_label: string | null; known_workflow: string; improvement: string | null;
  scope: string[]; why: string; confirm_with_buyer: string[];
}
export interface ContactRoute { id?: number; kind: string; value: string; label?: string | null; source_url: string; official: boolean }
export interface ActivityItem { id: number; kind: string; summary: string; channel: string | null; actor: string; occurred_at: string }
export interface Payment { id: number; amount: number; kind: string; received_on: string; reference: string | null; note: string | null }
export interface Deal {
  id: number; company_id: number; company: string; stage: string; outcome: string | null; contact_name: string | null;
  confirmed_requirement: string | null; offer: string | null; potential_amount: number | null; quoted_amount: number | null;
  expected_payment_date: string | null; delivery_status: string | null; next_follow_up_at: string | null; notes: string | null;
  collected: number; outstanding: number; payments: Payment[]; updated_at: string;
}
export interface Outreach { message: string; edited: boolean; contact_role: string; questions: string[]; notice: string }
export interface CompanyDetail extends CompanyCard {
  address: string | null; pincode: string | null; location_reason: string | null; activity: string; industry_strength: string;
  industry_reasons: string[]; directory_category: string | null; gates: Gate[]; score_breakdown: ScorePart[]; friction_reasons: string[];
  solution: Solution; disqualifier: string | null; source_url: string; source_key: string; researched_at: string | null;
  research_error: string | null; last_verified_at: string | null; created_at: string; outreach_approved_by: string | null;
  outreach_approved_at: string | null; facts: Fact[]; contacts: ContactRoute[];
  locations: { address: string | null; locality: string | null; status: string; reason: string; basis: string; evidence_url: string | null; excerpt: string | null; observed_at: string }[];
  activities: ActivityItem[]; deal: Deal | null; outreach: Outreach;
  people: Person[]; scope_confirmed: boolean; research_error_kind: string | null; research_retry_after: string | null;
  ai_researched_at: string | null; agent_events: AgentEvent[];
  dossier: { answers?: { q: string; a: string }[]; agent?: { outcome: string; summary: string | null; open_questions: string[]; first_question: string | null;
    stop_reason: string | null; model_calls: number; tool_calls: number; tokens: number; cost_usd: number; at: string } };
}
export interface Job {
  id: number; mode: string; status: string; stage: string | null; stage_index: number; stages: { key: string; label: string }[];
  counters: { run?: Record<string, number>; pool?: Record<string, number>; campaign?: Record<string, number>; [k: string]: unknown }; sources: Record<string, { status: string; records?: number; error?: string | null }>;
  params: Record<string, unknown>; summary: { companies?: number; by_category?: Record<string, number>; ready_to_review?: number; verified_locations?: number };
  log: string[]; error: string | null; trigger: string; retry_of_id: number | null; created_at: string; started_at: string | null;
  finished_at: string | null; heartbeat_at: string | null; elapsed_s: number | null; last_success: string | null;
}
export interface Preflight { checks: { source: string; enabled: boolean; ready: boolean; message: string }[]; can_start: boolean; can_find_new: boolean }
export interface Revenue { potential: number; quoted: number; contracted: number; advances_received: number; outstanding: number; collected_total: number; collected_this_month: number }
