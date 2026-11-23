import { useState } from "react";
import { Link } from "react-router-dom";
import { FileSearch, Search } from "lucide-react";
import { Badge, Card, Empty, ErrorState, Input, PageHeader, Select, Spinner } from "../components/ui";
import { AIChip } from "../components/intel";
import { LocationBadge, QualBadge } from "../components/prospect";
import { api } from "../lib/api";
import { useQuery } from "../lib/hooks";
import { AI_STATUS, EVQ, FIT, INDUSTRY, date, duration } from "../lib/format";
import type { CompanyCard, Job } from "../lib/types";

interface Row extends CompanyCard { people: number; testimonials: number; research_error: string | null; ai_researched_at: string | null; agent_outcome: string | null }

export default function Research() {
  const [q, setQ] = useState("");
  const [ai, setAi] = useState("");
  const data = useQuery(() => api.get<{ total: number; items: Row[]; jobs: Job[] }>("/research", { q, ai, limit: 60 }), [q, ai]);
  return (
    <>
      <PageHeader title="Research" description="Company dossiers and the research runs that built them. Every claim links to its source." actions={<AIChip />} />
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative min-w-[14rem] flex-1">
          <Search className="absolute left-3 top-3 h-4 w-4 text-subtle" />
          <Input className="pl-9" placeholder="Search companies" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search dossiers" />
        </div>
        <Select value={ai} onChange={(e) => setAi(e.target.value)} aria-label="AI research status">
          <option value="">Any AI status</option>
          {Object.entries(AI_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </Select>
      </div>
      <ErrorState error={data.error} onRetry={data.reload} />
      {!data.data ? <Spinner /> : (
        <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
          <div className="space-y-3">
            {data.data.items.length === 0 ? (
              <Empty icon={<FileSearch className="h-6 w-6" />} title="No dossiers yet">Run discovery in Balanced or Deep mode — researched companies appear here.</Empty>
            ) : data.data.items.map((r) => (
              <Link key={r.id} to={`/prospects/${r.id}`} className="block rounded-2xl border border-border bg-surface p-4 text-fg no-underline transition hover:border-brand/50 hover:no-underline">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold">{r.name}</div>
                    <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
                      <Badge tone="brand">{INDUSTRY[r.industry ?? ""] ?? "—"}</Badge><LocationBadge c={r} /><QualBadge q={r.qualification} />
                      <Badge tone={AI_STATUS[r.ai_status]?.tone ?? "neutral"}>{AI_STATUS[r.ai_status]?.label ?? r.ai_status}</Badge>
                    </div>
                  </div>
                  <div className="text-right text-xs text-subtle">Researched {date(r.ai_researched_at ?? r.researched_at)}</div>
                </div>
                <p className="mt-2 text-sm text-subtle">{r.description}</p>
                <div className="mt-2 flex flex-wrap gap-3 text-xs text-subtle">
                  <span>Operational fit: <strong className="text-fg">{FIT[r.operational_fit]}</strong></span>
                  <span>Evidence: <strong className="text-fg">{EVQ[r.evidence_quality]}</strong></span>
                  <span>{r.sources} sources</span><span>{r.people} people</span><span>{r.testimonials} testimonials</span>
                  {r.research_error && <span className="text-bad">{r.research_error}</span>}
                </div>
              </Link>
            ))}
          </div>
          <Card title="Research runs">
            <ul className="space-y-2 text-sm">
              {data.data.jobs.map((j) => (
                <li key={j.id} className="flex items-center justify-between gap-2">
                  <span>#{j.id} · <span className="capitalize">{j.mode}</span> · {date(j.created_at, true)}<span className="block text-xs text-subtle">{duration(j.elapsed_s)} · {String(j.counters.run?.researched ?? "—")} researched · {String(j.counters.run?.ai_calls ?? 0)} AI calls</span></span>
                  <Badge tone={j.status === "completed" ? "ok" : j.status === "failed" ? "bad" : "neutral"}>{j.status}</Badge>
                </li>
              ))}
            </ul>
            <Link to="/discover" className="mt-3 block text-sm">Open Discover</Link>
          </Card>
        </div>
      )}
    </>
  );
}
