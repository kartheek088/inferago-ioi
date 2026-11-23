// Types and labels for the Social Commerce channel (/api/v3/social).

import type { Tone } from "./format";
import type { ActivityItem, AgentEvent, Deal, Fact, Gate, ScorePart, Solution } from "./types";

export type SQual = "S0" | "S1" | "S2" | "S3";
export type GeoConfidence = "verified_chennai" | "probable_chennai" | "unclear" | "outside_chennai";
export type Platform = "instagram" | "facebook" | "whatsapp" | "other";

export const SQUAL: Record<string, { label: string; short: string; tone: Tone; hint: string }> = {
  S0: { label: "Confirmed opportunity", short: "S0", tone: "ok", hint: "They asked for help, or confirmed a problem to you." },
  S1: { label: "High-fit social seller", short: "S1", tone: "brand", hint: "Verified, active and complex enough to need a tool — but they have not asked." },
  S2: { label: "Watchlist", short: "S2", tone: "warn", hint: "Relevant, but something still needs checking." },
  S3: { label: "Excluded", short: "S3", tone: "bad", hint: "Wrong place, wrong category, inactive or a duplicate." },
};

export const GEO: Record<string, { label: string; tone: Tone }> = {
  verified_chennai: { label: "Verified Chennai", tone: "ok" },
  probable_chennai: { label: "Probable Chennai", tone: "warn" },
  unclear: { label: "Location unclear", tone: "neutral" },
  outside_chennai: { label: "Outside Chennai", tone: "bad" },
};

export const CATEGORY: Record<string, string> = {
  fashion_boutique: "Fashion boutique",
  custom_gifts: "Personalised gifts",
  home_bakery: "Home bakery / pre-order food",
  meal_subscription: "Meal subscription / tiffin",
  other_social: "Other social seller",
};

export const PLATFORM: Record<string, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  whatsapp: "WhatsApp",
  other: "Other storefront",
};

export const SETUP: Record<string, string> = {
  social_only: "Social only",
  social_whatsapp: "Social + WhatsApp orders",
  social_simple_site: "Social + simple website",
  social_full_ecommerce: "Social + online checkout",
  marketplace_led: "Marketplace-led",
  multi_channel: "Several channels",
  unknown: "Not known yet",
};

export const MATURITY: Record<string, { label: string; tone: Tone }> = {
  growing_operational: { label: "Growing operational seller", tone: "ok" },
  established_social: { label: "Established social-first business", tone: "brand" },
  early_stage: { label: "Early-stage seller", tone: "warn" },
  activity_unclear: { label: "Activity unclear", tone: "neutral" },
  inactive_unverified: { label: "Inactive / unverified", tone: "bad" },
};

export const COMPLEXITY: Record<string, { label: string; tone: Tone }> = {
  high: { label: "High order complexity", tone: "ok" },
  moderate: { label: "Moderate complexity", tone: "warn" },
  low: { label: "Low complexity", tone: "neutral" },
  unknown: { label: "Complexity unknown", tone: "neutral" },
};

export const ORDER_CHANNEL: Record<string, string> = {
  dm: "Direct messages", whatsapp: "WhatsApp", phone: "Phone", form: "Order form",
  website_cart: "Website checkout", marketplace: "Marketplace",
};

export interface SellerCard {
  id: number; name: string; description: string | null;
  category: string | null; category_label: string | null; locality: string | null;
  geo_confidence: GeoConfidence; geo_label: string; geo_reason: string | null;
  qualification: SQual; qualification_label: string; qualification_reasons: string[];
  score: number; friction: string; review_status: string; buying_intent: string;
  offer: string | null; next_action: string | null;
  sales_setup: string; sales_setup_label: string;
  maturity: string | null; maturity_label: string;
  complexity_level: string; complexity_count: number;
  platforms: Platform[]; handles: { platform: Platform; handle: string; url: string }[];
  last_activity_at: string | null; activity_count: number; demand_indicator_count: number;
  website: string | null; has_contact: boolean; official_contact: boolean; sales_ready: boolean;
  research_level: string; research_error: string | null; needs_human_check: boolean;
  operational_fit: string; evidence_quality: string; commercial_readiness: string; ai_status: string;
  next_follow_up_at: string | null; is_test: boolean;
}

export interface SocialAccount {
  id: number; platform: Platform; label: string; handle: string; url: string;
  profile_name: string | null; account_kind: string; catalogue_url: string | null;
  bio_excerpt: string | null; followers: number | null; followers_note: string;
  last_post_at: string | null; is_primary: boolean; reachable: string; readable_by_ioi: boolean;
  source_url: string; excerpt: string | null; detected_by: string; observed_at: string;
}

export interface SocialSignal {
  id: number; signal_type: string; label: string; indicator_class: "activity" | "demand_indicator";
  statement: string; excerpt: string | null; url: string; platform: string | null;
  published_at: string | null; last_checked_at: string; state: string; reliability: string;
  source_name: string | null; detected_by: string; review_status: string | null;
}

export interface BlockedAccount { platform: string; label: string; handle: string; url: string; why: string }

export interface SocialOutreach {
  message: string; edited: boolean; contact_role: string; suggested_route: string;
  questions: string[]; notice: string; free_offer: string;
}

export interface SellerDetail extends SellerCard {
  geo_basis: string | null; geo_evidence_url: string | null; geo_excerpt: string | null;
  geo_bases: Record<string, string>; weak_evidence_note: string;
  category_reasons: string[]; products_excerpt: string | null;
  order_channels: string[]; known_tools: string[]; workflow_gaps: string[]; sales_setup_reason: string | null;
  complexity: { key: string; label: string }[];
  maturity_reasons: string[]; maturity_note: string;
  gates: Gate[]; score_breakdown: ScorePart[]; friction_reasons: string[];
  // Same shape as a B2B solution, except the existing-software block is social-specific
  // (`already_using` + plain-language `advice` instead of the B2B `already_mentioned`).
  solution: Omit<Solution, "existing_software"> & {
    delivery_note?: string;
    existing_software?: { note: string; already_using: string[]; advice: string;
      options: { name: string; url: string; category: string; solves: string; burden: string; inferago_role: string }[] };
  };
  accounts: SocialAccount[]; blocked_accounts: BlockedAccount[];
  readable_pages: string[]; pages_checked: string[];
  activity: SocialSignal[]; facts: Fact[];
  contacts: { id: number; kind: string; value: string; label: string | null; source_url: string; official: boolean }[];
  activities: ActivityItem[]; deal: Deal | null; outreach: SocialOutreach;
  dossier: { answers?: { q: string; a: string }[]; agent?: {
    outcome: string; summary: string | null; open_questions: string[]; first_question: string | null;
    stop_reason: string | null; model_calls: number; tool_calls: number; rejected_claims?: number;
    tokens: number; cost_usd: number; at: string } };
  agent_events: AgentEvent[];
  researched_at: string | null; research_error_kind: string | null; research_retry_after: string | null;
  ai_researched_at: string | null; source_url: string; source_key: string; created_at: string;
  outreach_approved_by: string | null; outreach_approved_at: string | null; disqualifier: string | null;
}

export interface SocialOverview {
  campaign: { id: number; name: string; city: string; categories: string[] };
  stats: {
    discovered: number; verified_sellers: number; high_fit: number; recently_active: number;
    needs_verification: number; approved: number; qualified_conversations: number;
    ready_to_review: number; needs_human_check: number;
  };
  revenue: { potential: number; quoted: number; contracted: number; advances_received: number;
    outstanding: number; collected_total: number; collected_this_month: number };
  by_platform: Record<string, number>;
  by_category: Record<string, number>;
  by_qualification: Record<string, number>;
  active_job: import("./types").Job | null;
  last_job: import("./types").Job | null;
  preflight: { checks: { source: string; enabled: boolean; ready: boolean; message: string }[];
    can_start: boolean; can_find_new: boolean };
}

export interface SocialDiscover {
  settings: Record<string, unknown>;
  preflight: SocialOverview["preflight"];
  stages: { key: string; label: string }[];
  categories: { key: string; label: string; blurb: string }[];
  active_job: import("./types").Job | null;
  search: { ready: boolean; message: string; example_queries: string[] };
}

export const SOURCE_LABEL: Record<string, string> = {
  manual_profile: "Add a profile by hand",
  csv_import: "Authorised list import",
  public_search: "Public web search",
  market_listings: "Chennai market & exhibitor pages",
  business_features: "Business features & news",
  meta_api: "Instagram / Facebook APIs",
  seller_pages: "Seller websites & catalogues",
  ai_agent: "AI research agent",
  ai: "AI",
};
