import { Bot, CheckCircle2, CircleSlash, Cpu, FileText, Globe, Search, ShieldAlert, XCircle } from "lucide-react";
import { Badge } from "./ui";
import { api } from "../lib/api";
import { useQuery } from "../lib/hooks";
import { EVQ, FIT, FRICTION, INTENT, READINESS, cn, date } from "../lib/format";
import type { AgentEvent, AIStatus } from "../lib/types";

/** "AI connected" / "AI unavailable — rule-based research active", from the real backend status. */
export function AIChip({ compact }: { compact?: boolean }) {
  const s = useQuery(() => api.get<AIStatus>("/ai/status"), [], 60000);
  if (!s.data) return null;
  const on = s.data.configured && s.data.agent_supported;
  return (
    <Badge tone={on ? "ok" : "warn"} title={s.data.note ?? `${s.data.provider} · ${s.data.model}`}>
      <Cpu className="h-3 w-3" />
      {on ? (compact ? "AI connected" : `AI connected · ${s.data.model}`) : "AI unavailable — rule-based research active"}
    </Badge>
  );
}

const TOOL_ICON: Record<string, typeof Globe> = {
  fetch_official_company_page: Globe, list_official_pages: Search, record_fact: FileText, record_person: FileText,
  retrieve_cached_evidence: FileText, check_recent_events: Search, find_public_business_contacts: Search,
};

/** Auditable trace of real agent events. Shows what happened, never model reasoning. */
export function AgentTrace({ events, empty = "No AI research has run for this yet." }: { events: AgentEvent[]; empty?: string }) {
  if (!events.length) return <p className="text-sm text-subtle">{empty}</p>;
  return (
    <ol className="space-y-1.5 text-sm" aria-label="AI research activity">
      {events.map((e) => {
        const Icon = e.kind === "model" ? Bot : e.kind === "fallback" ? CircleSlash : e.status === "rejected" ? ShieldAlert
          : e.status === "failed" ? XCircle : e.kind === "finish" ? CheckCircle2 : TOOL_ICON[e.tool ?? ""] ?? FileText;
        const tone = e.status === "rejected" ? "text-warn" : e.status === "failed" ? "text-bad" : e.kind === "finish" ? "text-ok" : "text-subtle";
        return (
          <li key={e.id} className={cn("flex items-start gap-2", e.kind === "model" && "text-subtle")}>
            <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", tone)} />
            <span className="min-w-0 flex-1">
              {e.message}
              <span className="ml-1 text-xs text-subtle">
                {date(e.at, true)}
                {e.duration_ms ? ` · ${(e.duration_ms / 1000).toFixed(1)}s` : ""}
                {e.tokens_in ? ` · ${e.tokens_in + (e.tokens_out ?? 0)} tokens` : ""}
                {e.cost_usd ? ` · $${e.cost_usd.toFixed(4)}` : ""}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function Classifications({ c }: { c: { operational_fit: string; buying_intent: string; commercial_readiness: string; friction: string; evidence_quality: string } }) {
  const items: [string, string][] = [
    ["Operational fit", FIT[c.operational_fit] ?? c.operational_fit],
    ["Buying intent", INTENT[c.buying_intent] ?? c.buying_intent],
    ["Commercial readiness", READINESS[c.commercial_readiness] ?? c.commercial_readiness],
    ["Sales friction", (FRICTION[c.friction] ?? c.friction).replace(" friction", "")],
    ["Evidence quality", EVQ[c.evidence_quality] ?? c.evidence_quality],
  ];
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
      {items.map(([k, v]) => (
        <div key={k} className="rounded-xl border border-border bg-bg/50 px-3 py-2">
          <dt className="text-[11px] uppercase tracking-wide text-subtle">{k}</dt>
          <dd className="text-sm font-medium">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
