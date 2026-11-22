import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Circle, Loader2, Play, RotateCcw, Square, XCircle } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorState, Ext, Field, Input, Msg, Notice, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAction, useQuery } from "../lib/hooks";
import { ago, cn, date } from "../lib/format";
import type { Job, Preflight } from "../lib/types";

interface DiscoverData {
  settings: { depth: string; max_candidates: number; max_deep: number; daily_shortlist: number; ai_max_calls: number };
  preflight: Preflight; active: Job | null; history: Job[];
  market_news: { title: string; url: string; published_at: string | null; signals: string[] }[];
}

const DEPTHS = [
  { id: "quick", label: "Quick", text: "Find businesses and check location & industry from the directory. No websites visited." },
  { id: "balanced", label: "Balanced", text: "Also check news and research the most promising company websites. Recommended." },
  { id: "deep", label: "Deep", text: "Researches more pages per site; uses AI (if configured) within your call limit." },
];
const SOURCE_NAMES: Record<string, string> = { overture_places: "Business directory", official_websites: "Company websites", news_rss: "News feeds" };
const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "info" | "neutral"> = {
  queued: "info", running: "info", stopping: "warn", completed: "ok", stopped: "neutral", failed: "bad", interrupted: "warn",
};

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
  const isActive = !!job && ["queued", "running", "stopping"].includes(job.status);
  const liveStatus = live.data?.status;
  useEffect(() => {
    if (liveStatus && !["queued", "running", "stopping"].includes(liveStatus)) q.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveStatus]);

  const start = async () => {
    if (!d) return;
    const r = await act.run(() => api.post<Job>("/jobs", { mode: mode ?? d.settings.depth, max_candidates: maxC ?? d.settings.max_candidates, max_deep: maxD ?? d.settings.max_deep }));
    if (r) q.reload();
  };
  const stop = async () => { if (job && await act.run(() => api.post(`/jobs/${job.id}/stop`), "Stopping after the current item…")) live.reload(); };
  const retry = async () => { if (job && await act.run(() => api.post(`/jobs/${job.id}/retry`))) q.reload(); };

  return (
    <>
      <PageHeader title="Discover" description="Find Chennai equipment service companies and wholesale distributors, check them, and shortlist the best." />
      <ErrorState error={q.error} onRetry={q.reload} />
      {!d ? <Spinner /> : (
        <div className="space-y-6">
          <Card>
            <div className="grid gap-6 lg:grid-cols-[1fr_auto]">
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2 text-sm">
                  <Badge tone="brand">Chennai</Badge><Badge tone="brand">Equipment Sales & Service · 70%</Badge><Badge tone="brand">Wholesale Distribution · 30%</Badge>
                </div>
                <fieldset>
                  <legend className="mb-2 text-sm font-medium">Research depth</legend>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {DEPTHS.map((x) => {
                      const on = (mode ?? d.settings.depth) === x.id;
                      return (
                        <label key={x.id} className={cn("cursor-pointer rounded-lg border p-3 text-sm", on ? "border-brand bg-brand-soft/50" : "border-border hover:bg-muted")}>
                          <input type="radio" name="depth" className="sr-only" checked={on} onChange={() => setMode(x.id)} />
                          <span className="font-medium">{x.label}</span><span className="mt-1 block text-xs text-subtle">{x.text}</span>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
                <div className="grid max-w-md grid-cols-2 gap-3">
                  <Field label="New businesses (max)"><Input type="number" min={1} max={500} value={maxC ?? d.settings.max_candidates} onChange={(e) => setMaxC(parseInt(e.target.value || "1", 10))} /></Field>
                  <Field label="Websites to research"><Input type="number" min={0} max={100} value={maxD ?? d.settings.max_deep} onChange={(e) => setMaxD(parseInt(e.target.value || "0", 10))} /></Field>
                </div>
                <p className="text-xs text-subtle">
                  Uses: local business directory (no cost) · company websites (a few pages each, robots.txt respected) · news feeds.
                  {(mode ?? d.settings.depth) === "deep" ? ` AI: up to ${d.settings.ai_max_calls} calls this run (only if configured).` : " No AI calls."}
                </p>
              </div>
              <div className="flex flex-col items-stretch justify-center gap-2 lg:w-56">
                {isActive ? (
                  <Button variant="danger" size="lg" onClick={stop} loading={act.busy} disabled={job?.status === "stopping"}><Square className="h-4 w-4" />{job?.status === "stopping" ? "Stopping…" : "Stop"}</Button>
                ) : (
                  <Button variant="primary" size="lg" onClick={start} loading={act.busy} disabled={!d.preflight.can_start}><Play className="h-5 w-5" />Start Discovery</Button>
                )}
                {job && !isActive && ["failed", "interrupted", "stopped"].includes(job.status) && <Button onClick={retry} loading={act.busy}><RotateCcw className="h-4 w-4" />Retry</Button>}
                {job && !isActive && Object.values(job.sources).some((s) => s.status === "failed") && job.status === "completed" &&
                  <Button onClick={retry} loading={act.busy}><RotateCcw className="h-4 w-4" />Retry failed sources</Button>}
                <Link to="/prospects" className="text-center text-sm">View results</Link>
              </div>
            </div>
            <div className="mt-4 space-y-2">
              {d.preflight.checks.filter((c) => c.enabled && !c.ready && c.source !== "ai").map((c) => <Notice key={c.source} kind="warn">{c.message}</Notice>)}
              <Msg msg={act.msg} />
            </div>
          </Card>

          {job ? <Progress job={job} /> : <Empty title="No discovery run yet">Click <strong>Start Discovery</strong>. It runs in the background — you can leave this page.</Empty>}

          {d.market_news.length > 0 && (
            <Card title="Chennai market news" description="Relevant news that didn't name a business in your list. If it names a company, add it by hand in Prospects.">
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
                    <span>#{j.id} · <span className="capitalize">{j.mode}</span> · {date(j.created_at, true)}</span>
                    <span className="flex items-center gap-2"><span className="text-subtle">{j.counters.accepted ?? 0} added · {j.summary?.ready_to_review ?? 0} ready</span><Badge tone={STATUS_TONE[j.status]}>{j.status}</Badge></span>
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

function Progress({ job }: { job: Job }) {
  const c = job.counters;
  const active = ["queued", "running", "stopping"].includes(job.status);
  return (
    <Card title={<span className="flex items-center gap-2">Run #{job.id} <Badge tone={STATUS_TONE[job.status]}>{job.status}</Badge></span>}
      description={active ? `Last update ${ago(job.heartbeat_at ?? job.created_at)}` : job.finished_at ? `Finished ${date(job.finished_at, true)}` : undefined}>
      <div className="grid gap-6 lg:grid-cols-2">
        <ol className="relative space-y-3 before:absolute before:bottom-2 before:left-[7px] before:top-2 before:w-px before:bg-border" aria-label="Stages">
          {job.stages.map((s, i) => {
            const n = i + 1;
            const done = n < job.stage_index || (n === job.stage_index && !active && job.status === "completed");
            const now = n === job.stage_index && active;
            const skipped = !active && n > job.stage_index;
            return (
              <li key={s.key} className={cn("relative flex items-center gap-2 text-sm", now ? "font-medium text-fg" : done ? "text-fg" : "text-subtle")}>
                <span className="relative z-10 rounded-full bg-surface">{now ? <Loader2 className="h-4 w-4 animate-spin text-brand" /> : done ? <CheckCircle2 className="h-4 w-4 text-ok" /> : <Circle className="h-4 w-4" />}</span>
                {n}. {s.label}{skipped && job.mode === "quick" && n > 3 && n < 6 ? <span className="text-xs">(not in Quick mode)</span> : null}
              </li>
            );
          })}
        </ol>
        <div className="space-y-3">
          {c.total ? (
            <div>
              <div className="mb-1 flex justify-between text-xs text-subtle"><span>Businesses checked</span><span className="tabular-nums">{c.processed ?? 0} of {c.total}</span></div>
              <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={c.processed ?? 0} aria-valuemax={c.total} aria-label="Businesses checked">
                <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${Math.min(100, ((c.processed ?? 0) / c.total) * 100)}%` }} />
              </div>
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <Count k="Reviewed" v={c.total ? (c.processed ?? 0) : `${c.processed ?? 0}`} />
            <Count k="Added" v={c.accepted ?? 0} />
            <Count k="Rejected" v={(c.rejected_outside_total ?? c.rejected ?? 0) + (c.chain_outlets_total ?? 0)} />
            <Count k="Need checking" v={c.pending ?? 0} />
          </div>
          <ul className="space-y-1 text-sm">
            {Object.entries(job.sources).map(([k, s]) => (
              <li key={k} className="flex items-center gap-2">
                {s.status === "failed" ? <XCircle className="h-4 w-4 text-bad" /> : s.status === "done" ? <CheckCircle2 className="h-4 w-4 text-ok" /> : s.status === "running" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Circle className="h-4 w-4 text-subtle" />}
                {SOURCE_NAMES[k] ?? k}{s.status === "skipped" && <span className="text-xs text-subtle">— skipped{job.mode === "quick" && k !== "overture_places" ? " (not used in Quick)" : ""}</span>}
                {s.error && <span className="text-xs text-bad">— {s.error}</span>}
              </li>
            ))}
          </ul>
          {job.error && <Notice kind="err"><AlertTriangle className="inline h-4 w-4" /> {job.error}</Notice>}
          {!active && job.summary?.companies !== undefined && (
            <Notice kind={job.status === "completed" ? "ok" : "info"}>
              {job.summary.companies} businesses in this campaign · {job.summary.ready_to_review ?? 0} ready to review · {job.summary.verified_locations ?? 0} with verified Chennai address.{" "}
              <Link to="/prospects">Review prospects</Link>
            </Notice>
          )}
        </div>
      </div>
      <details className="mt-4">
        <summary className="cursor-pointer text-sm text-subtle">Activity log</summary>
        <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">{job.log.join("\n")}</pre>
      </details>
    </Card>
  );
}

function Count({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="rounded-xl border border-border bg-bg px-3 py-2"><div className="text-xs text-subtle">{k}</div><div className="text-lg font-semibold tabular-nums">{v}</div></div>;
}
