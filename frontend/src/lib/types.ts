export type Qual = "P0" | "P1" | "P2" | "P3";
export interface Signal { label: string; date: string | null; url: string | null; confirmed: boolean }
export interface CompanyCard {
  id: number; name: string; industry: string | null; industry_subtype: string | null; locality: string | null;
  location_confidence: "verified" | "partial" | "unknown" | "outside"; description: string | null; qualification: Qual;
  qualification_reasons: string[]; score: number; friction: string; review_status: string; buying_intent: string;
  offer: string | null; next_action: string | null; latest_signal: Signal | null; website: string | null; research_level: string;
  has_contact: boolean; official_contact: boolean; sources: number; sales_ready: boolean; next_follow_up_at: string | null; is_test: boolean;
}
export interface Fact {
  id: number; kind: string; key: string | null; statement: string; state: "source_verified" | "inferred" | "buyer_confirmed" | "unknown";
  excerpt: string | null; source_url: string | null; source_name: string | null; reliability: string; published_at: string | null;
  observed_at: string; detected_by: string; review_status: string | null; reviewed_by: string | null; label: string | null;
}
export interface Gate { key: string; label: string; passed: boolean | null; detail: string }
export interface ScorePart { key: string; label: string; points: number; max: number; why: string }
export interface Solution {
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
}
export interface Job {
  id: number; mode: string; status: string; stage: string | null; stage_index: number; stages: { key: string; label: string }[];
  counters: Record<string, number>; sources: Record<string, { status: string; records?: number; error?: string | null }>;
  params: Record<string, unknown>; summary: { companies?: number; by_category?: Record<string, number>; ready_to_review?: number; verified_locations?: number };
  log: string[]; error: string | null; trigger: string; retry_of_id: number | null; created_at: string; started_at: string | null;
  finished_at: string | null; heartbeat_at: string | null;
}
export interface Preflight { checks: { source: string; enabled: boolean; ready: boolean; message: string }[]; can_start: boolean; can_find_new: boolean }
export interface Revenue { potential: number; quoted: number; contracted: number; advances_received: number; outstanding: number; collected_total: number; collected_this_month: number }
