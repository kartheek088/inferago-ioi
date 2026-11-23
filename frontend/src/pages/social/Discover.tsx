import { useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, CircleAlert, CircleSlash, Play, RotateCcw, Search, Square, Upload } from "lucide-react";
import { Badge, Button, Card, Field, Msg, Notice, PageHeader, Select, Spinner, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { date, duration } from "../../lib/format";
import { useAction, useQuery } from "../../lib/hooks";
import { SOURCE_LABEL, type SocialDiscover } from "../../lib/social";
import type { Job } from "../../lib/types";

const MODES: { id: "quick" | "balanced" | "deep"; label: string; blurb: string }[] = [
  { id: "quick", label: "Quick", blurb: "Find seller profiles and basic identity only." },
  { id: "balanced", label: "Balanced", blurb: "Also verify Chennai, activity, order complexity and contacts." },
  { id: "deep", label: "Deep", blurb: "Also research the most promising sellers, with AI if it is configured." },
];

function SourceRow({ k, enabled, ready, message }: { k: string; enabled: boolean; ready: boolean; message: string }) {
  const Icon = !enabled ? CircleSlash : ready ? CheckCircle2 : CircleAlert;
  const tone = !enabled ? "text-subtle" : ready ? "text-emerald-500" : "text-amber-500";
  return (
    <li className="flex gap-2 text-sm">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone}`} aria-hidden />
      <span>
        <strong>{SOURCE_LABEL[k] ?? k}</strong>
        {!enabled && <Badge className="ml-2">off</Badge>}
        <span className="block text-subtle">{message}</span>
      </span>
    </li>
  );
}

function JobPanel({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const { busy, msg, run } = useAction();
  const run_ = (job.counters?.run ?? {}) as Record<string, number>;
  const camp = (job.counters?.campaign ?? {}) as Record<string, number>;
  const active = ["queued", "running", "stopping"].includes(job.status);
  const stages = job.stages ?? [];
  return (
    <Card title={`Run #${job.id} — ${job.mode}`}
      description={<span className="capitalize">{job.status}{job.elapsed_s != null ? ` · ${duration(job.elapsed_s)}` : ""}</span>}
      action={active
        ? <Button size="sm" loading={busy} onClick={() => run(() => api.post(`/social/jobs/${job.id}/stop`), "Stopping…").then(onChanged)}>
          <Square className="h-4 w-4" />Stop</Button>
        : ["failed", "interrupted", "stopped"].includes(job.status)
          ? <Button size="sm" loading={busy} onClick={() => run(() => api.post(`/social/jobs/${job.id}/retry`), "Retrying").then(onChanged)}>
            <RotateCcw className="h-4 w-4" />Retry</Button>
          : null}>
      <div className="space-y-4">
        {stages.length > 0 && (
          <ol className="flex flex-wrap gap-1.5 text-xs">
            {stages.map((s, i) => (
              <li key={s.key} className={`rounded-md px-2 py-1 ${i < job.stage_index ? "bg-brand-soft text-brand"
                : i === job.stage_index ? "bg-muted font-medium" : "text-subtle"}`}>{s.label}</li>
            ))}
          </ol>
        )}
        {job.error && <Notice kind="err">{job.error}</Notice>}
        {job.last_success && <p className="text-xs text-subtle">Last successful step: {job.last_success}</p>}

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-subtle">This run</h4>
            <dl className="mt-1 space-y-0.5 text-sm">
              {Object.entries(run_).length === 0 && <dd className="text-subtle">Nothing yet.</dd>}
              {Object.entries(run_).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3">
                  <dt className="text-subtle">{k.replace(/_/g, " ")}</dt><dd className="tabular-nums">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-subtle">Campaign totals</h4>
            <dl className="mt-1 space-y-0.5 text-sm">
              {Object.entries(camp).length === 0 && <dd className="text-subtle">Nothing yet.</dd>}
              {Object.entries(camp).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3">
                  <dt className="text-subtle">{k.replace(/_/g, " ")}</dt><dd className="tabular-nums">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>

        {Object.keys(job.sources ?? {}).length > 0 && (
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-subtle">Sources</h4>
            <ul className="mt-1 space-y-1 text-sm">
              {Object.entries(job.sources).map(([k, v]) => (
                <li key={k} className="flex flex-wrap items-baseline gap-2">
                  <span>{SOURCE_LABEL[k] ?? k}</span>
                  <Badge tone={v.status === "done" ? "ok" : v.status === "failed" ? "bad" : v.status === "running" ? "brand" : "neutral"}>
                    {v.status}
                  </Badge>
                  {v.records != null && <span className="text-subtle">{v.records} added</span>}
                  {v.error && <span className="text-subtle">· {v.error}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {job.log?.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm text-subtle">Log ({job.log.length} lines)</summary>
            <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-muted p-2 text-xs leading-relaxed">{job.log.join("\n")}</pre>
          </details>
        )}
        <Msg msg={msg} />
      </div>
    </Card>
  );
}

export default function SocialDiscoverPage() {
  const q = useQuery(() => api.get<SocialDiscover>("/social/discover"), [], 4000);
  const jobs = useQuery(() => api.get<{ items: Job[] }>("/social/jobs", { limit: 8 }), []);
  const [mode, setMode] = useState<"quick" | "balanced" | "deep">("balanced");
  const [terms, setTerms] = useState("");
  const { busy, msg, run } = useAction();
  const [upload, setUpload] = useState<{ ok?: string; err?: string }>({});

  if (!q.data && q.loading) return <Spinner label="Loading discovery…" />;
  if (!q.data) return <Spinner label="Loading discovery…" />;
  const { preflight, search, active_job } = q.data;

  const start = () =>
    run(() => api.post<Job>("/social/jobs", {
      mode,
      search_terms: terms.split("\n").map((t) => t.trim()).filter(Boolean),
    }), "Discovery started").then(() => { q.reload(); jobs.reload(); });

  const sendCsv = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await api.upload<{ rows: number; accepted: number; duplicate: number; no_profile: number }>("/social/import/csv", form);
      setUpload({ ok: `${r.rows} rows read · ${r.accepted} added · ${r.duplicate} duplicates · ${r.no_profile} without a usable link` });
      q.reload();
    } catch (e) {
      setUpload({ err: e instanceof Error ? e.message : String(e) });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Find social sellers"
        description="Only permitted sources. A source that needs access IOI does not have says so instead of guessing."
        actions={<Button variant="primary" loading={busy} disabled={!!active_job} onClick={start}>
          <Play className="h-4 w-4" />Find Social Sellers
        </Button>} />

      {active_job && <JobPanel job={active_job} onChanged={() => { q.reload(); jobs.reload(); }} />}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Run settings">
          <div className="space-y-3">
            <Field label="How deep">
              <Select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                {MODES.map((m) => <option key={m.id} value={m.id}>{m.label} — {m.blurb}</option>)}
              </Select>
            </Field>
            <Field label="Extra search phrases" hint="One per line. Only used when a search API is configured.">
              <Textarea rows={3} value={terms} onChange={(e) => setTerms(e.target.value)}
                placeholder={"Chennai home bakery instagram\nChennai customised gifts whatsapp"} />
            </Field>
            {!search.ready && (
              <Notice kind="warn">
                <strong>Public web search is not available.</strong> {search.message}
              </Notice>
            )}
            {search.ready && search.example_queries.length > 0 && (
              <details><summary className="cursor-pointer text-sm text-subtle">Search phrases that will be used</summary>
                <ul className="mt-1 list-disc pl-5 text-xs text-subtle">
                  {search.example_queries.map((s) => <li key={s}>{s}</li>)}
                </ul>
              </details>
            )}
            <Msg msg={msg} />
          </div>
        </Card>

        <Card title="What can run right now">
          <ul className="space-y-2">
            {preflight.checks.map((c) => <SourceRow key={c.source} k={c.source} {...c} />)}
          </ul>
          {!preflight.can_find_new && (
            <Notice kind="info">
              No automatic discovery source is ready, so a run will only research and re-qualify the sellers you have
              already added. Adding a profile by hand always works.
            </Notice>
          )}
        </Card>
      </div>

      <Card title="Import an authorised list"
        description="A CSV of sellers you are allowed to use — an exhibitor list, a market's seller list."
        action={<a href={api.url("/social/import/template.csv")} download><Button size="sm">Template</Button></a>}>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <Upload className="h-4 w-4" />
          <span className="underline">Choose a CSV file</span>
          <input type="file" accept=".csv,text/csv" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void sendCsv(f); }} />
        </label>
        {upload.ok && <Notice kind="ok">{upload.ok}</Notice>}
        {upload.err && <Notice kind="err">{upload.err}</Notice>}
      </Card>

      <Card title="Recent runs" action={<Link to="/social-commerce/leads"><Button size="sm"><Search className="h-4 w-4" />Sellers</Button></Link>}>
        {jobs.data?.items.length ? (
          <ul className="divide-y divide-border text-sm">
            {jobs.data.items.map((j) => (
              <li key={j.id} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                <span>#{j.id} · {j.mode} · <span className="capitalize">{j.status}</span></span>
                <span className="text-subtle">
                  {date(j.finished_at ?? j.created_at, true)}
                  {j.summary?.sellers != null ? ` · ${j.summary.sellers} sellers` : ""}
                  {j.error ? ` · ${j.error.slice(0, 60)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-subtle">No runs yet.</p>}
      </Card>
    </div>
  );
}
