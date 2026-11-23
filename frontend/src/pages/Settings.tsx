import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CheckCircle2, CircleDashed, Download, XCircle } from "lucide-react";
import { Badge, Button, Card, ErrorState, Field, Input, Modal, Msg, Notice, PageHeader, Select, Spinner, Tabs, Textarea } from "../components/ui";
import { api, getToken } from "../lib/api";
import { useAction, useQuery } from "../lib/hooks";
import { ago, date } from "../lib/format";
import { AIChip } from "../components/intel";
import { useTheme } from "../components/Shell";
import type { AIStatus } from "../lib/types";
import type { Job } from "../lib/types";

type Tab = "business" | "discovery" | "ai" | "data" | "advanced";
interface SettingsData {
  business: { company_name: string; positioning: string; services: string[]; facts: string[]; revenue_goal_monthly: number; sender_name: string; sender_link: string };
  discovery: { depth: string; max_candidates: number; max_deep: number; daily_shortlist: number; ai_max_calls: number; approved_localities: string[];
    sources: Record<string, boolean>; schedule: string; city: string; industry_mix: Record<string, number> };
  ai: { configured: boolean; provider: string | null; model: string | null; how_to_configure: string };
}

async function download(path: string, filename: string) {
  const token = getToken();
  const res = await fetch(`/api/v3${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

export default function Settings() {
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get("tab") as Tab) || "business";
  const s = useQuery(() => api.get<SettingsData>("/settings"), []);
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs tabs={[{ id: "business", label: "Business" }, { id: "discovery", label: "Discovery" }, { id: "ai", label: "AI" }, { id: "data", label: "Data" }, { id: "advanced", label: "Advanced" }] as { id: Tab; label: string }[]}
        value={tab} onChange={(t) => setSp({ tab: t })} />
      <div className="mt-6">
        <ErrorState error={s.error} onRetry={s.reload} />
        {!s.data ? <Spinner /> : tab === "business" ? <div className="space-y-6"><Business s={s.data} onSaved={s.setData} /><Appearance /></div>
          : tab === "discovery" ? <Discovery s={s.data} onSaved={s.setData} />
          : tab === "ai" ? <AI s={s.data} onSaved={s.setData} />
          : tab === "data" ? <Data /> : <Advanced />}
      </div>
    </>
  );
}

function Business({ s, onSaved }: { s: SettingsData; onSaved: (x: SettingsData) => void }) {
  const [b, setB] = useState(s.business);
  const act = useAction();
  return (
    <Card title="Business profile" description="Used in outreach messages. Only state what is true.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Business name"><Input value={b.company_name} onChange={(e) => setB({ ...b, company_name: e.target.value })} /></Field>
        <Field label="Monthly revenue goal (₹)"><Input type="number" min={0} value={b.revenue_goal_monthly} onChange={(e) => setB({ ...b, revenue_goal_monthly: Math.max(0, parseInt(e.target.value || "0", 10)) })} /></Field>
        <Field label="Your name (signs messages)"><Input value={b.sender_name} onChange={(e) => setB({ ...b, sender_name: e.target.value })} /></Field>
        <Field label="Link about you (optional)" hint="A website or profile a buyer can check"><Input value={b.sender_link} onChange={(e) => setB({ ...b, sender_link: e.target.value })} /></Field>
      </div>
      <div className="mt-4 space-y-4">
        <Field label="Positioning"><Textarea rows={2} value={b.positioning} onChange={(e) => setB({ ...b, positioning: e.target.value })} /></Field>
        <Field label="Services offered" hint="One per line"><Textarea rows={4} value={b.services.join("\n")} onChange={(e) => setB({ ...b, services: e.target.value.split("\n").filter((x) => x.trim()) })} /></Field>
        <p className="text-sm text-subtle">Facts: {b.facts.join(" · ")}</p>
        <Msg msg={act.msg} />
        <Button variant="primary" loading={act.busy} onClick={async () => { const r = await act.run(() => api.put<SettingsData>("/settings", { business: b }), "Saved"); if (r) onSaved(r); }}>Save</Button>
      </div>
    </Card>
  );
}

function Discovery({ s, onSaved }: { s: SettingsData; onSaved: (x: SettingsData) => void }) {
  const [d, setD] = useState(s.discovery);
  const [loc, setLoc] = useState(s.discovery.approved_localities.join(", "));
  const act = useAction();
  const num = (k: "max_candidates" | "max_deep" | "daily_shortlist" | "ai_max_calls", label: string, hint?: string) => (
    <Field label={label} hint={hint}><Input type="number" min={0} value={d[k]} onChange={(e) => setD({ ...d, [k]: parseInt(e.target.value || "0", 10) })} /></Field>
  );
  const save = async () => {
    const r = await act.run(() => api.put<SettingsData>("/settings", { discovery: { depth: d.depth, max_candidates: d.max_candidates, max_deep: d.max_deep,
      daily_shortlist: d.daily_shortlist, ai_max_calls: d.ai_max_calls, sources: d.sources, schedule: d.schedule, industry_mix: d.industry_mix,
      approved_localities: loc.split(",").map((x) => x.trim()).filter(Boolean) } }), "Saved");
    if (r) onSaved(r);
  };
  return (
    <div className="space-y-6">
      <Card title="Where" description="Chennai city (Greater Chennai Corporation area).">
        <Field label="Also accept these metro-area localities" hint="Comma-separated, e.g. Tambaram, Avadi. Leave empty to keep strictly to the city.">
          <Input value={loc} onChange={(e) => setLoc(e.target.value)} /></Field>
      </Card>
      <Card title="Industries & limits">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Equipment Sales & Service — share of effort (%)"><Input type="number" min={0} max={100} value={d.industry_mix.equipment_sales_service ?? 70}
            onChange={(e) => { const v = Math.min(100, Math.max(0, parseInt(e.target.value || "0", 10))); setD({ ...d, industry_mix: { equipment_sales_service: v, wholesale_distribution: 100 - v } }); }} /></Field>
          <Field label="Wholesale Distribution — share (%)"><Input disabled value={d.industry_mix.wholesale_distribution ?? 30} /></Field>
          <Field label="Default research depth"><Select className="w-full" value={d.depth} onChange={(e) => setD({ ...d, depth: e.target.value })}>
            <option value="quick">Quick</option><option value="balanced">Balanced</option><option value="deep">Deep</option></Select></Field>
          {num("max_candidates", "New businesses per run", "Default 50")}
          {num("max_deep", "Websites researched per run", "Default 10")}
          {num("daily_shortlist", "Ready-to-review limit", "Default 5")}
        </div>
      </Card>
      <Card title="Sources">
        <div className="space-y-2">
          {Object.entries({ overture_places: "Business directory (Overture open data)", official_websites: "Company websites", news_rss: "Chennai business news" }).map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={d.sources[k] ?? true} onChange={(e) => setD({ ...d, sources: { ...d.sources, [k]: e.target.checked } })} />{label}</label>
          ))}
        </div>
      </Card>
      <Card title="Schedule (optional)" description="Runs discovery automatically when the app is running. Never sends anything.">
        <Select value={d.schedule} onChange={(e) => setD({ ...d, schedule: e.target.value })} aria-label="Schedule">
          <option value="off">Off — I start discovery myself</option><option value="daily">Once a day</option><option value="weekly">Once a week</option>
        </Select>
      </Card>
      <Msg msg={act.msg} />
      <Button variant="primary" loading={act.busy} onClick={save}>Save discovery settings</Button>
    </div>
  );
}

function AI({ s, onSaved }: { s: SettingsData; onSaved: (x: SettingsData) => void }) {
  const act = useAction();
  const [calls, setCalls] = useState(s.discovery.ai_max_calls);
  const [res, setRes] = useState<string | null>(null);
  return (
    <Card title="AI assistance" description="Optional. Discovery and research work fully without AI.">
      <div className="space-y-4 text-sm">
        {s.ai.configured ? <Notice kind="ok">Provider: {s.ai.provider} · Model: {s.ai.model}</Notice> : <Notice>Not configured. {s.ai.how_to_configure}</Notice>}
        <p className="text-subtle">API keys live only in the server's .env file and are never shown here. AI is used only in Deep research, and anything it reports must be quoted word-for-word from the company's website or it is discarded.</p>
        <Field label="Maximum AI calls per Deep run" hint="0 turns AI off. Each call reads one company website."><Input type="number" min={0} max={200} value={calls} onChange={(e) => setCalls(parseInt(e.target.value || "0", 10))} /></Field>
        <div className="flex gap-2">
          <Button onClick={async () => { const r = await act.run(() => api.put<SettingsData>("/settings", { discovery: { ai_max_calls: calls } }), "Saved"); if (r) onSaved(r); }}>Save limit</Button>
          <Button disabled={!s.ai.configured} loading={act.busy} onClick={async () => { const r = await act.run(() => api.post<{ ok: boolean; message: string }>("/ai/test")); if (r) setRes(r.message); }}>Test connection</Button>
        </div>
        {res && <Notice>{res}</Notice>}
        <Msg msg={act.msg} />
        <AIDiagnostics />
      </div>
    </Card>
  );
}

function AIDiagnostics() {
  const st = useQuery(() => api.get<AIStatus>("/ai/status"), []);
  const d = st.data;
  if (!d) return null;
  const row = (k: string, v: React.ReactNode) => <div className="flex justify-between gap-3 border-t border-border py-1.5"><dt className="text-subtle">{k}</dt><dd className="text-right">{v}</dd></div>;
  return (
    <div>
      <h3 className="mb-1 font-semibold">Diagnostics</h3>
      <dl>
        {row("Status", <AIChip />)}
        {row("Provider · model", d.configured ? `${d.provider} · ${d.model}` : "—")}
        {row("Last successful call", d.last_success ? `${date(d.last_success.at, true)} (${d.last_success.task})` : "never")}
        {row("Last error", d.last_error ? `${date(d.last_error.at, true)}: ${d.last_error.error}` : "none")}
        {row("Fallback", d.fallback)}
        {row("Last 24 h", `${d.usage_24h.calls} calls · ${d.usage_24h.tokens_in + d.usage_24h.tokens_out} tokens · $${d.usage_24h.cost_usd.toFixed(4)}`)}
        {row("Last 30 days", `${d.usage_30d.calls} calls · ${d.usage_30d.tokens_in + d.usage_30d.tokens_out} tokens · $${d.usage_30d.cost_usd.toFixed(4)}`)}
        {row("Agent limits per company", `${d.limits.max_model_calls} AI calls · ${d.limits.max_tool_calls} tools · ${d.limits.max_pages} pages · ${d.limits.max_seconds}s · $${d.limits.max_cost_usd}`)}
      </dl>
      {d.note && <p className="mt-2 text-xs text-subtle">{d.note}</p>}
    </div>
  );
}

function Appearance() {
  const [dark, toggle] = useTheme();
  return (
    <Card title="Appearance">
      <div className="flex items-center justify-between text-sm"><span>Theme: <strong>{dark ? "Dark (default)" : "Light"}</strong></span>
        <Button size="sm" onClick={toggle}>Switch to {dark ? "light" : "dark"}</Button></div>
      <p className="mt-2 text-xs text-subtle">Saved in this browser.</p>
    </Card>
  );
}

interface Legacy { tables: Record<string, number>; note: string; backups: { name: string; size_mb: number; created: string }[] }
interface ResetPreview { campaign: string; companies: number; deals: number; payments: number; what_happens: string; confirm_phrase: string }

function Data() {
  const legacy = useQuery(() => api.get<Legacy>("/legacy"), []);
  const preview = useQuery(() => api.get<ResetPreview>("/campaign/reset-preview"), []);
  const act = useAction();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [phrase, setPhrase] = useState("");
  const dl = (path: string, name: string) => act.run(() => download(path, name), "Download started");
  return (
    <div className="space-y-6">
      <Msg msg={act.msg} />
      <Card title="Export & import">
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => dl("/export/companies.csv", "ioi-prospects.csv")}><Download className="h-4 w-4" />Export prospects (CSV)</Button>
          <Link to="/prospects"><Button variant="ghost">Import an authorised CSV (in Prospects)</Button></Link>
        </div>
      </Card>
      <Card title="Backups" description="A full copy of the database, checked for integrity.">
        <Button loading={act.busy} onClick={async () => { const r = await act.run(() => api.post<{ file: string }>("/backup"), "Backup created"); if (r) legacy.reload(); }}>Back up now</Button>
        <ul className="mt-3 space-y-1 text-sm text-subtle">{legacy.data?.backups.map((b) => <li key={b.name}>{b.name} · {b.size_mb} MB · {date(b.created, true)}</li>)}</ul>
        <p className="mt-2 text-xs text-subtle">Backups are saved in backend/data/backups on this computer. To restore one, stop IOI and copy it over backend/data/ioi.db (see README).</p>
      </Card>
      <Card title="Legacy archive" description={legacy.data?.note}>
        {legacy.data && (
          <ul className="space-y-1 text-sm">
            {Object.entries(legacy.data.tables).map(([t, n]) => (
              <li key={t} className="flex items-center justify-between gap-2"><span>{t.replace(/_/g, " ")} — {n.toLocaleString("en-IN")} records</span>
                <Button size="sm" variant="ghost" disabled={!n} onClick={() => dl(`/legacy/${t}.csv`, `legacy-${t}.csv`)}>Export CSV</Button></li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Start a new campaign" description="For a fresh start. Nothing is deleted.">
        {preview.data && <p className="text-sm">{preview.data.what_happens} Current campaign: {preview.data.companies} businesses, {preview.data.deals} deals, {preview.data.payments} payments.</p>}
        <Button className="mt-3" variant="danger" onClick={() => setConfirmOpen(true)}>Archive this campaign and start a new one…</Button>
      </Card>
      <Modal open={confirmOpen} onClose={() => setConfirmOpen(false)} title="Start a new campaign?"
        footer={<><Button variant="ghost" onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button variant="danger" disabled={phrase !== preview.data?.confirm_phrase} loading={act.busy}
            onClick={async () => { const r = await act.run(() => api.post("/campaign/reset", { confirm: phrase }), "New campaign started"); if (r) { setConfirmOpen(false); preview.reload(); } }}>Start new campaign</Button></>}>
        <p className="text-sm">{preview.data?.what_happens}</p>
        <Field label={`Type ${preview.data?.confirm_phrase} to confirm`}><Input value={phrase} onChange={(e) => setPhrase(e.target.value)} /></Field>
      </Modal>
    </div>
  );
}

interface Source { key: string; name: string; description: string | null; health: string; last_success_at: string | null; last_error: string | null; last_records: number | null;
  data_freshness: string | null; terms: string | null; rate_limit_per_minute: number | null; access_method: string; geo_coverage: string }
interface Directory { files: { name: string; size_mb: number; modified: string }[]; downloading: boolean; last_download: { status: string; log: string[] } | null; about: string }

function Advanced() {
  const src = useQuery(() => api.get<{ sources: Source[] }>("/sources"), []);
  const dir = useQuery(() => api.get<Directory>("/sources/directory"), []);
  const jobs = useQuery(() => api.get<Job[]>("/jobs", { limit: 15 }), []);
  const diag = useQuery(() => api.get<{ worker_alive: boolean; database_mb: number; auth: string; discovery_scope: string; scheduler: { enabled: boolean; jobs: { id: string; next_run: string | null }[] };
    recent_events: { at: string; actor: string; action: string; entity: string }[] }>("/diagnostics"), []);
  const act = useAction();
  useEffect(() => { if (!dir.data?.downloading) return; const t = setInterval(() => dir.reload(), 10000); return () => clearInterval(t); }, [dir.data?.downloading]);
  const icon = (h: string) => h === "working" ? <CheckCircle2 className="h-4 w-4 text-ok" /> : h === "untested" ? <CircleDashed className="h-4 w-4 text-subtle" /> : <XCircle className="h-4 w-4 text-bad" />;
  return (
    <div className="space-y-6">
      <Msg msg={act.msg} />
      <Card title="Source health" description="A source shows 'working' only after a real successful retrieval.">
        <ul className="divide-y divide-border">
          {src.data?.sources.map((s) => (
            <li key={s.key} className="py-3 text-sm">
              <div className="flex items-center gap-2 font-medium">{icon(s.health)}{s.name}<Badge>{s.health}</Badge></div>
              <p className="mt-1 text-subtle">{s.description}</p>
              <p className="mt-1 text-xs text-subtle">Last success: {ago(s.last_success_at)}{s.last_records !== null ? ` · ${s.last_records} records` : ""}{s.data_freshness ? ` · ${s.data_freshness}` : ""}
                {s.rate_limit_per_minute ? ` · ≤${s.rate_limit_per_minute}/min` : ""} · {s.terms}</p>
              {s.last_error && <p className="mt-1 text-xs text-bad">Last error: {s.last_error}</p>}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Business directory file" description={dir.data?.about}>
        {dir.data?.files.length ? <ul className="text-sm">{dir.data.files.map((f) => <li key={f.name}>{f.name} · {f.size_mb} MB · {date(f.modified)}</li>)}</ul> : <Notice kind="warn">No directory file yet — discovery can't find new businesses until it's downloaded.</Notice>}
        {dir.data?.last_download && <p className="mt-2 text-xs text-subtle">Last download: {dir.data.last_download.status} — {dir.data.last_download.log.slice(-1)[0]}</p>}
        <Button className="mt-3" loading={act.busy} disabled={dir.data?.downloading} onClick={async () => { if (await act.run(() => api.post("/sources/directory/download"), "Download started")) dir.reload(); }}>
          {dir.data?.downloading ? "Downloading…" : dir.data?.files.length ? "Download the latest release" : "Download directory file"}</Button>
      </Card>
      <Card title="Job history">
        <ul className="space-y-2 text-sm">{jobs.data?.map((j) => (
          <li key={j.id}><details><summary className="cursor-pointer">#{j.id} · {j.mode} · {j.status} · {date(j.created_at, true)} · {String(j.counters.run?.added ?? j.counters.accepted ?? 0)} added · {String(j.counters.run?.ai_calls ?? 0)} AI calls{j.error ? ` · ${j.error.slice(0, 80)}` : ""}</summary>
            <pre className="mt-2 max-h-48 overflow-auto rounded bg-muted p-2 text-xs">{j.log.join("\n")}</pre></details></li>
        ))}</ul>
      </Card>
      {diag.data && (
        <Card title="System diagnostics">
          <ul className="space-y-1 text-sm">
            <li>Discovery worker: {diag.data.worker_alive ? "running" : "not running (restart IOI)"}</li>
            <li>Scheduler: {diag.data.scheduler.enabled ? `on (${diag.data.scheduler.jobs.map((j) => j.id).join(", ") || "no jobs"})` : "off"}</li>
            <li>Access: {diag.data.auth} · Scope: {diag.data.discovery_scope} · Database: {diag.data.database_mb} MB</li>
          </ul>
          <details className="mt-3"><summary className="cursor-pointer text-sm">Recent events</summary>
            <ul className="mt-2 space-y-1 text-xs text-subtle">{diag.data.recent_events.map((e, i) => <li key={i}>{date(e.at, true)} · {e.actor} · {e.action} · {e.entity}</li>)}</ul></details>
        </Card>
      )}
    </div>
  );
}

