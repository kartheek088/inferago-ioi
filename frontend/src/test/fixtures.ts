import type { CompanyCard, CompanyDetail, Job } from "../lib/types";

export const card: CompanyCard = {
  id: 7, name: "Test Biomedical Services", industry: "equipment_sales_service", industry_subtype: "medical", locality: "t nagar",
  location_confidence: "verified", description: "Equipment Sales & Service (medical). Website mentions: amc / warranty.", qualification: "P1",
  qualification_reasons: ["Passes every gate"], score: 72, friction: "low", review_status: "shortlisted", buying_intent: "indirect",
  offer: "ServiceFlow Setup", next_action: "Review and approve for outreach.", latest_signal: { label: "New service centre / warehouse / branch", date: "2026-11-02", url: "https://n.example", confirmed: false },
  website: "https://x.example", research_level: "website", has_contact: true, official_contact: true, sources: 3, sales_ready: true, next_follow_up_at: null, is_test: true,
  operational_fit: "strong", evidence_quality: "partial", commercial_readiness: "unknown", ai_status: "partial", researched_at: "2026-11-20T10:00:00",
};

export const detail: CompanyDetail = {
  ...card, address: "14 Usman Road, T Nagar, Chennai 600017", pincode: "600017", location_reason: "'t nagar' is inside Chennai city (official website)",
  activity: "active", industry_strength: "strong", industry_reasons: [], directory_category: null,
  gates: [
    { key: "chennai", label: "Verified Chennai operation", passed: true, detail: "Confirmed" },
    { key: "contact", label: "Legitimate public contact route", passed: true, detail: "On website" },
  ],
  score_breakdown: [{ key: "intent", label: "Buying intent / documented pain", points: 0, max: 30, why: "No evidence of a need yet" }],
  friction_reasons: ["Easier: they publish a business contact"],
  solution: { offer: "ServiceFlow Setup", level: 5, level_label: "Build a small custom module", known_workflow: "Seen in sources: AMC / warranty contracts",
    improvement: "One place to log service requests", scope: ["Service request log"], why: "Coordinates service work.", confirm_with_buyer: ["How are AMC renewals tracked?"] },
  disqualifier: null, source_url: "https://explore.overturemaps.org/", source_key: "overture_places", researched_at: null, research_error: null,
  last_verified_at: null, created_at: "2026-11-20T10:00:00", outreach_approved_by: null, outreach_approved_at: null,
  facts: [
    { id: 1, kind: "workflow", key: "amc_warranty", statement: "The business mentions amc / warranty", state: "source_verified", excerpt: "Annual maintenance contracts", source_url: "https://x.example/services",
      source_name: "Official website", reliability: "high", published_at: null, observed_at: "2026-11-20T10:00:00", detected_by: "rule", review_status: null, reviewed_by: null, label: null },
    { id: 2, kind: "problem", key: "technician_tracking", statement: "May benefit from one place to assign technicians", state: "inferred", excerpt: null, source_url: null,
      source_name: null, reliability: "medium", published_at: null, observed_at: "2026-11-20T10:00:00", detected_by: "rule", review_status: null, reviewed_by: null, label: null },
    { id: 3, kind: "tools", key: "current_software", statement: "Whether they already use software for service tracking", state: "unknown", excerpt: null, source_url: null,
      source_name: null, reliability: "medium", published_at: null, observed_at: "2026-11-20T10:00:00", detected_by: "rule", review_status: null, reviewed_by: null, label: null },
  ],
  contacts: [{ kind: "email", value: "service@x.example", source_url: "https://x.example/contact", official: true }],
  locations: [], activities: [], deal: null,
  people: [{ id: 1, name: "R. Kumar", role: "Managing Director", role_group: "leadership", excerpt: "Our Managing Director, R. Kumar, leads 15 service engineers",
    source_url: "https://x.example/about", published_contact: null, detected_by: "rule", verified_at: "2026-11-20T10:00:00" }],
  scope_confirmed: false, research_error_kind: null, research_retry_after: null, ai_researched_at: "2026-11-20T10:00:00",
  agent_events: [
    { id: 1, session: "s1", company_id: 7, job_id: null, step: 1, kind: "tool", tool: "fetch_official_company_page", args: { url: "/about" }, status: "ok",
      message: "Checked official company page /about", model: null, duration_ms: 900, tokens_in: null, tokens_out: null, cost_usd: null, at: "2026-11-20T10:00:00" },
    { id: 2, session: "s1", company_id: 7, job_id: null, step: 2, kind: "tool", tool: "record_fact", args: {}, status: "rejected",
      message: "Rejected an unsupported claim (quote not found on the page)", model: null, duration_ms: 1, tokens_in: null, tokens_out: null, cost_usd: null, at: "2026-11-20T10:00:01" },
  ],
  dossier: { answers: [{ q: "Why was this company found?", a: "Found via a public business directory." }, { q: "Is that problem verified or hypothetical?", a: "Hypothesis — not confirmed by the buyer." }],
    agent: { outcome: "partial", summary: "Service-heavy lab equipment firm.", open_questions: ["How are AMC visits scheduled?"], first_question: null, stop_reason: null,
      model_calls: 4, tool_calls: 6, tokens: 9000, cost_usd: 0.004, at: "2026-11-20T10:00:00" } },
  outreach: { message: "Hello Test Biomedical Services team, …", edited: false, contact_role: "Service manager or owner", questions: ["How are AMC renewals tracked?"], notice: "IOI never sends messages." },
};

export const job: Job = {
  id: 3, mode: "balanced", status: "running", stage: "research", stage_index: 5,
  stages: ["Finding businesses", "Checking Chennai locations", "Checking industry relevance", "Looking for operational signals", "Researching promising candidates", "Preparing qualified prospects"].map((label, i) => ({ key: `s${i}`, label })),
  counters: { run: { reviewed: 18, to_review: 50, added: 12, duplicates: 1, researched: 3 }, pool: { unseen_relevant: 900, outside_city: 95, chain_outlets: 28 }, campaign: { companies: 40, needs_verification: 30 } },
  sources: { overture_places: { status: "done", records: 12 }, official_websites: { status: "running" }, news_rss: { status: "failed", error: "1 feed failed" } },
  params: {}, summary: {}, log: ["10:00:00 Queued (balanced)", "10:00:01 Researched 3 of 10: X — P2"], error: null, trigger: "manual", retry_of_id: null,
  created_at: "2026-11-23T10:00:00", started_at: "2026-11-23T10:00:00", finished_at: null, heartbeat_at: "2026-11-23T10:00:05", elapsed_s: 95, last_success: "10:01:30 Researched 3 of 10",
};
