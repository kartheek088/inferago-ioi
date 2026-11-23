import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Circle, Loader2, Play, RotateCcw, Square, XCircle } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorState, Ext, Field, Input, Msg, Notice, PageHeader, Spinner } from "../components/ui";
import { AgentTrace, AIChip } from "../components/intel";
import { api } from "../lib/api";
import { useAction, useQuery } from "../lib/hooks";
import { ago, cn, date, duration } from "../lib/format";
import type { AgentEvent, Job, Preflight } from "../lib/types";

interface DiscoverData {
  settings: { depth: string; max_candidates: number; max_deep: number; daily_shortlist: number; ai_max_calls: number };
  preflight: Preflight; active: Job | null; history: Job[];
  market_news: { title: string; url: string; published_at: string | null; signals: string[] }[];
}

const DEPTHS = [
  { id: "quick", label: "Quick", text: "Directory only: find businesses and check location & industry. No websites visited." },
  { id: "balanced", label: "Balanced", text: "Also reads news and researches the most promising company websites. Recommended." },
  { id: "deep", label: "Deep", text: "Reads more pages per site, then the AI agent investigates the strongest candidates." },
];
const SOURCE_NAMES: Record<string, string> = { overture_places: "Business directory", official_websites: "Company websites", news_rss: "News feeds", ai_agent: "AI research agent" };
const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "info" | "neutral"> = {
  queued: "info", running: "info", stopping: "warn", completed: "ok", stopped: "neutral", failed: "bad", interrupted: "warn",
};
const ACTIVE = ["queued", "running", "stopping"];

export default function Discover() {
  const q = useQuery(() => api.get<DiscoverData>("/discover"), []);
  const active = q.data?.active;
  const live = useQuery(() => (active ? api.get<Job>(`/jobs/${active.id}`) : Promise.resolve(undefined)), [active?.id], active ? 1500 : false);
  const act = useAction();
  const [mode, setMode] = useState<string | null>(null);
  const [maxC, setMaxC] = useState<number | null>(null);
  const [maxD, setMaxD] = useState<number | null>(null);
  const d = q.data;
  const job = live.data ?? active ?? d?.history[0] ?? null;
  const isActive = !!job && ACTIVE.includes(job.status);
  const liveStatus = live.data?.status;
  useEffect(() => {
    if (liveStatus && !ACTIVE.includes(liveStatus)) q.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveStatus]);

  const depth = mode ?? d?.settings.depth ?? "balanced";
  const start = async () => {
    if (!d) return;
    const r = await act.run(() => api.post<Job>("/jobs", { mode: depth, max_candidates: maxC ?? d.settings.max_candidates, max_deep: maxD ?? d.settings.max_deep }));
    if (r) q.reload();
  };
  const stop = async () => { if (job && await act.run(() => api.post(`/jobs/${job.id}/stop`), "Stopping after the current item…")) live.reload(); };
  const retry = async () => { if (job && await act.run(() => api.post(`/jobs/${job.id}/retry`))) q.reload(); };

  return (
    <>
      <PageHeader title="Discover" description="One click: IOI finds Chennai equipment-service companies and wholesale distributors, checks them against public sources, and shortlists the best." />
      <ErrorState error={q.error} onRetry={q.reload} />
      {!d ? <Spinner /> : (
        <div className="space-y-6">
          <Card>
            <div className="grid gap-6 lg:grid-cols-[1fr_auto]">
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge tone="brand">Chennai city</Badge><Badge tone="brand">Equipment Sales & Service · 70%</Badge><Badge tone="brand">Wholesale Distribution · 30%</Badge>
                  <AIChip />
                </div>
                <fieldset>
                  <legend className="mb-2 text-sm font-medium">Research mode</legend>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {DEPTHS.map((x) => {
                      const on = depth === x.id;
                      return (
                        <label key={x.id} className={cn("cursor-pointer rounded-xl border p-3 text-sm transition", on ? "border-brand bg-brand-soft/60" : "border-border hover:bg-muted")}>
                          <input type="radio" name="depth" className="sr-only" checked={on} onChange={() => setMode(x.id)} />
                          <span className="flex items-center gap-2 font-medium">{on ? <CheckCircle2 className="h-4 w-4 text-brand" /> : <Circle className="h-4 w-4 text-subtle" />}{x.label}</span>
                          <span className="mt-1 block text-xs text-subtle">{x.text}</span>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
                <div className="grid max-w-md grid-cols-2 gap-3">
                  <Field label="Candidate limit"><Input type="number" min={1} max={500} value={maxC ?? d.settings.max_candidates} onChange={(e) => setMaxC(parseInt(e.target.value || "1", 10))} /></Field>
                  <Field label="Research limit (websites)"><Input type="number" min={0} max={100} value={maxD ?? d.settings.max_deep} onChange={(e) => setMaxD(parseInt(e.target.value || "0", 10))} /></Field>
                </div>
                <p className="text-xs text-subtle">
                  Usage cap: local directory (free) · up to {maxD ?? d.settings.max_deep} websites × {depth === "deep" ? 7 : 4} pages, robots.txt respected ·
                  {depth === "deep" ? ` at most ${d.settings.ai_max_calls} AI calls this run` : " no AI calls"}.
                </p>
              </div>
              <div className="flex flex-col items-stretch justify-center gap-2 lg:w-60">
                {isActive ? (
                  <Button variant="danger" size="lg" onClick={stop} loading={act.busy} disabled={job?.status === "stopping"}><Square className="h-4 w-4" />{job?.status === "stopping" ? "Stopping…" : "Stop"}</Button>
                ) : (
                  <Button variant="primary" size="lg" onClick={start} loading={act.busy} disabled={!d.preflight.can_start}><Play className="h-5 w-5" />Find Chennai Prospects</Button>
                )}
                {job && !isActive && ["failed", "interrupted", "stopped"].includes(job.status) && <Button onClick={retry} loading={act.busy}><RotateCcw className="h-4 w-4" />Retry</Button>}
                {job && !isActive && job.status === "completed" && Object.values(job.sources).some((s) => s.status === "failed") &&
                  <Button onClick={retry} loading={act.busy}><RotateCcw className="h-4 w-4" />Retry failed sources</Button>}
                <Link to="/prospects" className="text-center text-sm">View results</Link>
              </div>
            </div>
            <div className="mt-4 space-y-2">
              {d.preflight.checks.filter((c) => c.enabled && !c.ready && c.source !== "ai").map((c) => <Notice key={c.source} kind="warn">{c.message}</Notice>)}
              <Msg msg={act.msg} />
            </div>
          </Card>

          {job ? <Progress job={job} live={isActive} /> : <Empty title="No discovery run yet">Click <strong>Find Chennai Prospects</strong>. It keeps running in the background — you can switch pages.</Empty>}

          {d.market_news.length > 0 && (
            <Card title="Chennai market news" description="Relevant news that didn't name a business in your list. If it names a company, add it in Prospects.">
              <ul className="space-y-2 text-sm">{d.market_news.map((n) => (
                <li key={n.url}><Ext href={n.url}>{n.title}</Ext> <span className="text-subtle">· {date(n.published_at)} · {n.signals.join(", ")}</span></li>
              ))}</ul>
            </Card>
          )}

          {d.history.length > 1 && (
            <Card title="Previous runs">
              <ul className="divide-y divide-border text-sm">
                {d.history.slice(job ? 1 : 0).map((j) => (
                  <li key={j.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span>#{j.id} · <span className="capitalize">{j.mode}</span> · {date(j.created_at, true)} · {duration(j.elapsed_s)}</span>
                    <span className="flex items-center gap-2">
                      <span className="text-subtle">{String(j.counters.run?.added ?? j.counters.accepted ?? 0)} added · {j.summary?.ready_to_review ?? 0} ready</span>
                      <Badge tone={STATUS_TONE[j.status]}>{j.status}</Badge>
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </>
  );
}

function Progress({ job, live }: { job: Job; live: boolean }) {
  const run = job.counters.run ?? {};
  const pool = job.counters.pool ?? {};
  const camp = job.counters.campaign ?? {};
  const events = useQuery(() => api.get<AgentEvent[]>(`/jobs/${job.id}/events`), [job.id], live ? 3000 : false);
  const toReview = run.to_review ?? 0;
  const legacy = !job.counters.run && job.counters.processed !== undefined;
  return (
    <Card title={<span className="flex items-center gap-2">Run #{job.id} <Badge tone={STATUS_TONE[job.status]}>{job.status}</Badge> <span className="text-xs font-normal capitalize text-subtle">{job.mode}</span></span>}
      description={<>Elapsed {duration(job.elapsed_s)}{live ? ` · last update ${ago(job.heartbeat_at ?? job.created_at)}` : job.finished_at ? ` · finished ${date(job.finished_at, true)}` : ""}</>}>
      <div className="grid gap-6 lg:grid-cols-2">
        <ol className="relative space-y-3 before:absolute before:bottom-2 before:left-[7px] before:top-2 before:w-px before:bg-border" aria-label="Stages">
          {job.stages.map((s, i) => {
            const n = i + 1;
            const done = n < job.stage_index || (n === job.stage_index && !live && job.status === "completed");
            const now = n === job.stage_index && live;
            return (
              <li key={s.key} className={cn("relative flex items-center gap-2 text-sm", now ? "font-medium text-fg" : done ? "text-fg" : "text-subtle")}>
                <span className="relative z-10 rounded-full bg-surface">{now ? <Loader2 className="h-4 w-4 animate-spin text-brand" /> : done ? <CheckCircle2 className="h-4 w-4 text-ok" /> : <Circle className="h-4 w-4" />}</span>
                {n}. {s.label}
              </li>
            );
          })}
        </ol>
        <div className="space-y-4">
          {toReview > 0 && (
            <div>
              <div className="mb-1 flex justify-between text-xs text-subtle"><span>This run: businesses checked</span><span className="tabular-nums">{run.reviewed ?? 0} of {toReview}</span></div>
              <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={run.reviewed ?? 0} aria-valuemax={toReview} aria-label="Businesses checked">
                <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${Math.min(100, ((run.reviewed ?? 0) / toReview) * 100)}%` }} />
              </div>
            </div>
          )}
          <Group title="This run" items={[["Reviewed", run.reviewed], ["Added", run.added], ["Duplicates", run.duplicates], ["Websites researched", run.researched],
            ["Research failed", run.research_failed], ["Newly qualified", run.newly_qualified], ["AI calls", run.ai_calls]]} />
          <Group title="Directory file (Chennai area)" items={[["Relevant, not yet reviewed", pool.unseen_relevant], ["Outside city (never added)", pool.outside_city], ["Chain outlets (never added)", pool.chain_outlets]]} />
          <Group title="Campaign totals" items={[["Businesses", camp.companies], ["Need verification", camp.needs_verification], ["Pass every check", camp.sales_ready], ["Ready to review", camp.ready_to_review]]} />
          {legacy && <p className="text-xs text-subtle">Older run: {String(job.counters.processed)} reviewed · {String(job.counters.accepted)} added (older runs mixed per-run and campaign-wide numbers).</p>}
          <ul className="space-y-1 text-sm">
            {Object.entries(job.sources).map(([k, s]) => {
              const kind = (s as { kind?: string }).kind;
              return (
                <li key={k} className="flex flex-wrap items-center gap-2">
                  {s.status === "failed" ? <XCircle className="h-4 w-4 text-bad" /> : s.status === "done" ? <CheckCircle2 className="h-4 w-4 text-ok" /> : s.status === "running" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Circle className="h-4 w-4 text-subtle" />}
                  {SOURCE_NAMES[k] ?? k}
                  {s.status === "skipped" && <span className="text-xs text-subtle">— skipped{job.mode === "quick" && k !== "overture_places" ? " (not used in Quick)" : ""}</span>}
                  {s.error && <span className="text-xs text-bad">— {s.error}{kind === "retryable" ? " (will retry)" : kind === "permanent" ? " (permanent)" : ""}</span>}
                </li>
              );
            })}
          </ul>
          {job.last_success && <p className="text-xs text-subtle">Last successful step: {job.last_success}</p>}
          {job.error && <Notice kind="err"><AlertTriangle className="inline h-4 w-4" /> {job.error}</Notice>}
          {!live && job.summary?.companies !== undefined && (
            <Notice kind={job.status === "completed" ? "ok" : "info"}>
              {job.summary.companies} businesses in this campaign · {job.summary.ready_to_review ?? 0} ready to review · {job.summary.verified_locations ?? 0} with a verified Chennai address.{" "}
              <Link to="/prospects">Review prospects</Link>
            </Notice>
          )}
        </div>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">AI research activity</h3>
          <div className="max-h-72 overflow-auto rounded-xl border border-border bg-bg/40 p-3">
            <AgentTrace events={events.data ?? []} empty={job.mode === "deep" ? "No AI activity in this run yet." : "AI research runs in Deep mode only."} />
          </div>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Activity log</h3>
          <pre className="max-h-72 overflow-auto rounded-xl border border-border bg-bg/40 p-3 text-xs leading-relaxed">{job.log.join("\n")}</pre>
        </div>
      </div>
    </Card>
  );
}

function Group({ title, items }: { title: string; items: [string, number | undefined][] }) {
  const shown = items.filter(([, v]) => v !== undefined);
  if (!shown.length) return null;
  return (
    <div>
      <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-subtle">{title}</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {shown.map(([k, v]) => (
          <div key={k} className="rounded-xl border border-border bg-bg/40 px-3 py-2"><div className="text-xs text-subtle">{k}</div><div className="text-lg font-semibold tabular-nums">{v}</div></div>
        ))}
      </div>
    </div>
  );
}
