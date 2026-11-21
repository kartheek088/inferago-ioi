import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "../api";
import { Empty, ErrorBox, ExtLink, Loading, Msg, Pager, fmtDate, useAction, useApi } from "../components/ui";

import { FOCUS } from "./CallList";

const ProspectMap = lazy(() => import("../components/ProspectMap"));

export interface Gap { key: string; label: string; detail: string }
export interface Prospect {
  id: number;
  name: string;
  segment: "small_business" | "professional" | "enterprise" | "college";
  business_type: string;
  type_label: string;
  area: string | null;
  state: string | null;
  country: string | null;
  address: string | null;
  phone: string | null;
  phone_normalized: string | null;
  phone_type: string | null;
  phone_verified: boolean;
  phone_verified_at: string | null;
  email: string | null;
  website: string | null;
  social_links: string[];
  opening_hours: string | null;
  has_website: boolean;
  new_listing: boolean;
  source_url: string;
  gaps: Gap[];
  recommended_services: string[];
  audit: { error?: string; checked_at?: string; final_url?: string; social_activity?: "very_active" | "some" | "inactive" };
  audited_at: string | null;
  score: number;
  score_reasons: string[];
  need_level: "definite" | "likely" | "upgrade" | "check_site" | "maybe" | null;
  need_reasons: string[];
  quality_level: "established" | "good" | "small" | null;
  quality_reasons: string[];
  qualification: Record<string, unknown>;
  status: string;
  notes: string | null;
  last_contacted_at: string | null;
  next_follow_up: string | null;
  contact_log: { at: string; channel: string; outcome: string; note: string | null }[];
}
interface Page { items: Prospect[]; total: number; limit: number; offset: number }
interface Summary { total: number; no_website: number; hot: number; definite: number; new_listings: number; by_state: Record<string, number>; by_need: Record<string, number>; by_quality: Record<string, number>; follow_ups_due: number; by_segment: Record<string, number>; services: Record<string, string> }
interface Areas { groups: Record<string, string[]>; selected: string[]; radius_m: number; max_per_area: number }
interface Run { id: number; areas: string[]; status: string; found: number; new: number; updated: number; log: string[]; started_at: string; finished_at: string | null }
interface Pitch { subject: string; message: string; call_script: string; links: { call: string | null; whatsapp: string | null; email: string | null; map: string }; note: string }

export const SEGMENTS: { id: string; label: string; hint: string }[] = [
  { id: "", label: "Everyone", hint: "" },
  { id: "college", label: "Colleges", hint: "Private colleges and universities" },
  { id: "small_business", label: "Small businesses", hint: "Shops, clinics, restaurants, hotels, schools" },
  { id: "professional", label: "Independent professionals", hint: "Doctors, lawyers, accountants, architects" },
  { id: "enterprise", label: "Bigger companies", hint: "Factories, Pvt Ltd firms: ERP / SAP / CRM" },
];
const RUN_LABEL: Record<string, string> = {
  success: "done", partial: "partly done", failed: "failed (map servers busy)", stopped: "stopped", running: "running", stopping: "stopping",
};

export const STATUS_LABEL: Record<string, string> = {
  new: "New", shortlisted: "Shortlisted", contacted: "Contacted", no_answer: "No answer", callback: "Call back", interested: "Interested",
  qualified: "Qualified ✅", proposal: "Proposal sent", won: "Won 🎉", not_interested: "Not interested", rejected: "Skip",
};
const QUALITY: Record<string, [string, string]> = { established: ["Established", "good"], good: ["Good", "info"], small: ["Small", ""] };
const SHORT_SERVICE: Record<string, string> = {
  website: "Website", marketing: "SEO & marketing", crm: "CRM", ai: "AI / chatbot", erp: "ERP / SAP",
  strategy: "Digital strategy", automation: "Automation", integration: "Integration", backend: "Software",
  api: "APIs", internal_apps: "Internal apps",
};

const PHONE_LABEL: Record<string, string> = { mobile: "Mobile", landline: "Landline", toll_free: "Toll-free", international: "International", invalid: "Looks wrong" };

export function PhoneBadge({ p }: { p: Prospect }) {
  if (!p.phone) return null;
  if (p.phone_verified) return <span className="badge good" title={`Confirmed by you ${fmtDate(p.phone_verified_at)}`}>✓ Number works</span>;
  if (p.phone_type === "invalid") return <span className="badge bad" title="This number doesn't look like a valid phone number">Number looks wrong</span>;
  return <span className="badge info" title="Format checked. Not yet confirmed by a call.">{PHONE_LABEL[p.phone_type ?? ""] ?? "Phone"} · format OK</span>;
}

const NEED: Record<string, { label: string; tone: string }> = {
  definite: { label: "Definitely needs us", tone: "good" },
  likely: { label: "Likely needs us", tone: "info" },
  upgrade: { label: "Website needs upgrade", tone: "warn" },
  check_site: { label: "Website not checked yet", tone: "" },
  maybe: { label: "Maybe", tone: "" },
};

export function NeedBadge({ level }: { level: string | null }) {
  if (!level || !NEED[level]) return null;
  return <span className={`badge ${NEED[level].tone}`}>{NEED[level].label}</span>;
}

export function ScoreRing({ score }: { score: number }) {
  const tone = score >= 70 ? "hot" : score >= 50 ? "warm" : "cool";
  return (
    <div className={`ring ${tone}`} style={{ ["--p" as string]: `${score}` }} title={`Potential score ${score}/100`}>
      <span>{Math.round(score)}</span>
    </div>
  );
}

interface MapFiles {
  files: { folder: string; file: string; path: string; size_mb: number; modified: string; downloading: boolean }[];
  folders: Record<string, string>;
  download_links: Record<string, string>;
  regions: string[];
}

function useRuns(onStarted: () => void) {
  const runs = useApi(() => api.get<Run[]>("/prospects/runs", { limit: 3 }));
  const running = !!runs.data?.some((r) => r.status === "running" || r.status === "stopping");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => { runs.reload(); onStarted(); }, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);
  return { runs, running, last: runs.data?.[0] };
}

function RunStatus({ runs, running, last }: ReturnType<typeof useRuns>) {
  const act = useAction();
  if (!last) return null;
  const done = last.log.filter((l) => /^[✓✗]/.test(l)).length;
  const isFile = last.areas.length === 1 && (last.areas[0].startsWith("map file") || last.areas[0].startsWith("Overture"));
  return (
    <>
      {running ? (
        <div className="progress-box">
          <div className="row between small">
            <strong>{isFile ? `${last.areas[0]}…` : `Searching ${last.areas.length} place(s)…`}</strong>
            <span className="row gap-s">
              {!isFile && <span className="muted">{done} of {last.areas.length} done · {last.found} found so far</span>}
              <button className="btn sm danger" disabled={act.busy || last.status === "stopping"}
                onClick={async () => { await act.run(() => api.post(`/prospects/runs/${last.id}/stop`)); runs.reload(); }}>
                {last.status === "stopping" ? "Stopping…" : "Stop"}
              </button>
            </span>
          </div>
          <div className={`bar ${isFile ? "indeterminate" : ""}`}><div className="fill" style={{ width: isFile ? "30%" : `${(100 * done) / Math.max(1, last.areas.length)}%` }} /></div>
          <div className="xs muted wrap">{last.log.length ? last.log[last.log.length - 1] : "Starting…"}</div>
        </div>
      ) : (
        <div className="small muted">
          Last search: <strong>{RUN_LABEL[last.status] ?? last.status}</strong> · {last.found} found ({last.new} new) · {fmtDate(last.started_at, true)}
        </div>
      )}
      <Msg msg={act.msg} />
      {last.log.length > 0 && !running && (
        <details className="small" open={last.status !== "success"}>
          <summary className="muted">Search log</summary>
          <ul className="list-plain xs">{last.log.map((l, i) => <li key={i} className="wrap">{l}</li>)}</ul>
        </details>
      )}
    </>
  );
}

function MapFilePanel({ status, onStarted }: { status: ReturnType<typeof useRuns>; onStarted: () => void }) {
  const files = useApi(() => api.get<MapFiles>("/prospects/map-files"));
  const areas = useApi(() => api.get<Areas>("/prospects/areas"));
  const [chosen, setChosen] = useState("");
  const [where, setWhere] = useState<"Tamil Nadu" | "cities" | "Whole file">("Tamil Nadu");
  const [cities, setCities] = useState<string[]>(["Chennai", "Coimbatore", "Madurai"]);
  const [radius, setRadius] = useState(15);
  const [maxKeep, setMaxKeep] = useState(3000);
  const act = useAction();
  const list = files.data?.files ?? [];
  useEffect(() => { if (!chosen && list.length) setChosen(`${list[0].folder}/${list[0].file}`); }, [list, chosen]);
  const start = async () => {
    const [folder, ...rest] = chosen.split("/");
    const body = { folder, file: rest.join("/"), region: where === "Whole file" ? "Whole file" : where === "cities" ? "Whole file" : "Tamil Nadu",
      cities: where === "cities" ? cities : null, radius_km: radius, max_keep: maxKeep };
    const r = await act.run(() => api.post<Run>("/prospects/scan-map-file", body), "Scan started. You can keep working; results appear when it finishes.");
    if (r) { status.runs.reload(); onStarted(); }
  };
  if (files.error) return <ErrorBox error={files.error} />;
  if (!files.data) return <Loading />;
  const southLink = Object.values(files.data.download_links)[0];
  return (
    <div className="find-panel">
      <ol className="steps-list small">
        <li>
          <strong>Download the map file once</strong> (free, about 1.7 GB):{" "}
          <a href={southLink} target="_blank" rel="noopener noreferrer">All-India map file ↓</a>
          <span className="muted"> · <a href={Object.values(files.data.download_links)[1]} target="_blank" rel="noopener noreferrer">other Indian zones</a> · <a href={Object.values(files.data.download_links)[2]} target="_blank" rel="noopener noreferrer">other countries</a></span>
          <div className="muted xs">Leave it in your Downloads folder ({files.data.folders.downloads}) or move it to {files.data.folders.maps}. Download a fresh one every month or two.</div>
        </li>
        <li>
          <strong>Pick the file</strong>{" "}
          <button className="link-btn" onClick={files.reload}>↻ refresh list</button>
          {list.length === 0 ? (
            <div className="alert warn small">No map file found yet. Download it above, then click “refresh list”.</div>
          ) : (
            <div className="chips" style={{ marginTop: 6 }}>
              {list.map((f) => {
                const k = `${f.folder}/${f.file}`;
                return <button key={k} className={`chip ${chosen === k ? "on" : ""}`} onClick={() => setChosen(k)}>{f.file} · {f.size_mb} MB · {f.downloading ? "⏳ still downloading" : fmtDate(f.modified)}</button>;
              })}
            </div>
          )}
        </li>
        <li>
          <strong>Where to look</strong>
          <div className="chips" style={{ marginTop: 6 }}>
            <button className={`chip ${where === "Tamil Nadu" ? "on" : ""}`} onClick={() => setWhere("Tamil Nadu")}>All of Tamil Nadu</button>
            <button className={`chip ${where === "cities" ? "on" : ""}`} onClick={() => setWhere("cities")}>Around chosen cities</button>
            <button className={`chip ${where === "Whole file" ? "on" : ""}`} onClick={() => setWhere("Whole file")}>Everywhere in the file</button>
          </div>
          {where === "cities" && areas.data && (
            <div style={{ marginTop: 8 }}>
              <div className="chips">
                {Object.values(areas.data.groups).flat().map((a) => (
                  <button key={a} className={`chip ${cities.includes(a) ? "on" : ""}`} onClick={() => setCities((c) => (c.includes(a) ? c.filter((x) => x !== a) : [...c, a]))}>{a}</button>
                ))}
              </div>
              <label className="field" style={{ marginTop: 8, maxWidth: 220 }}>Distance from each city (km)
                <input type="number" min={1} max={100} value={radius} onChange={(e) => setRadius(Number(e.target.value) || 15)} />
              </label>
            </div>
          )}
          <label className="field" style={{ marginTop: 8, maxWidth: 260 }}>Keep the best (max prospects)
            <input type="number" min={10} max={20000} value={maxKeep} onChange={(e) => setMaxKeep(Number(e.target.value) || 3000)} />
          </label>
        </li>
      </ol>
      <div className="row gap">
        <button className="btn primary" disabled={act.busy || status.running || !chosen || (where === "cities" && !cities.length)} onClick={start}>
          {status.running ? "Working…" : "Scan map file"}
        </button>
        <span className="muted small">Runs on this laptop with no internet needed. Usually 2–10 minutes.</span>
      </div>
      <Msg msg={act.msg} />
    </div>
  );
}

interface OvertureStatus { files: { file: string; size_mb: number; modified: string }[]; downloading: boolean; folder: string; about: string }

function OverturePanel({ status, onStarted }: { status: ReturnType<typeof useRuns>; onStarted: () => void }) {
  const ov = useApi(() => api.get<OvertureStatus>("/prospects/overture"), [status.running]);
  const areas = useApi(() => api.get<Areas>("/prospects/areas"));
  const [where, setWhere] = useState<"india" | "cities">("india");
  const [cities, setCities] = useState<string[]>(["Chennai", "Coimbatore", "Madurai"]);
  const [radius, setRadius] = useState(15);
  const [maxKeep, setMaxKeep] = useState(200000);
  const act = useAction();
  const file = ov.data?.files[ov.data.files.length - 1];
  const download = async () => {
    const r = await act.run(() => api.post<Run>("/prospects/overture/download"), "Download started. It takes 10–40 minutes; you can keep working.");
    if (r) { status.runs.reload(); onStarted(); }
  };
  const scan = async () => {
    if (!file) return;
    const r = await act.run(() => api.post<Run>("/prospects/scan-overture", {
      file: file.file, cities: where === "cities" ? cities : null, radius_km: radius, max_keep: maxKeep,
    }), "Scan started.");
    if (r) { status.runs.reload(); onStarted(); }
  };
  if (ov.error) return <ErrorBox error={ov.error} />;
  if (!ov.data) return <Loading />;
  return (
    <div className="find-panel">
      <p className="muted small">
        The biggest free business directory: millions of Indian shops, clinics, salons, dealers and offices, most with a phone number and a Facebook page.
        Open data from Overture Maps (Meta, Microsoft, Foursquare and others).
      </p>
      <ol className="steps-list small">
        <li>
          <strong>Get India’s business listings</strong> (once a month is enough)
          <div className="row gap" style={{ marginTop: 6 }}>
            {file ? <span className="badge good">✓ {file.file} · {file.size_mb} MB · {fmtDate(file.modified)}</span> : <span className="muted">Not downloaded yet.</span>}
            {ov.data.downloading
              ? <span className="badge warn">⏳ downloading…</span>
              : <button className="btn sm" disabled={act.busy || status.running} onClick={download}>{file ? "Get the latest" : "Download India listings"}</button>}
          </div>
        </li>
        <li>
          <strong>Where to look</strong>
          <div className="chips" style={{ marginTop: 6 }}>
            <button className={`chip ${where === "india" ? "on" : ""}`} onClick={() => setWhere("india")}>All of India</button>
            <button className={`chip ${where === "cities" ? "on" : ""}`} onClick={() => setWhere("cities")}>Around chosen cities</button>
          </div>
          {where === "cities" && areas.data && (
            <div style={{ marginTop: 8 }}>
              <div className="chips">
                {[...(areas.data.groups["Tamil Nadu"] ?? []), ...(areas.data.groups["Rest of India"] ?? [])].map((a) => (
                  <button key={a} className={`chip ${cities.includes(a) ? "on" : ""}`} onClick={() => setCities((c) => (c.includes(a) ? c.filter((x) => x !== a) : [...c, a]))}>{a}</button>
                ))}
              </div>
              <label className="field" style={{ marginTop: 8, maxWidth: 220 }}>Distance from each city (km)
                <input type="number" min={1} max={100} value={radius} onChange={(e) => setRadius(Number(e.target.value) || 15)} />
              </label>
            </div>
          )}
          <label className="field" style={{ marginTop: 8, maxWidth: 260 }}>Keep the best (max prospects)
            <input type="number" min={10} max={1000000} value={maxKeep} onChange={(e) => setMaxKeep(Number(e.target.value) || 200000)} />
          </label>
        </li>
      </ol>
      <div className="row gap">
        <button className="btn primary" disabled={act.busy || status.running || !file || (where === "cities" && !cities.length)} onClick={scan}>
          {status.running ? "Working…" : "Find prospects"}
        </button>
        <span className="muted small">Runs on this laptop. Businesses with a Facebook / Instagram page but no website come first.</span>
      </div>
      <Msg msg={act.msg} />
    </div>
  );
}

function LivePanel({ status, onStarted }: { status: ReturnType<typeof useRuns>; onStarted: () => void }) {
  const { data, error } = useApi(() => api.get<Areas>("/prospects/areas"));
  const [picked, setPicked] = useState<string[]>([]);
  const [custom, setCustom] = useState("");
  const act = useAction();
  useEffect(() => { if (data) setPicked(data.selected ?? []); }, [data]);
  const toggle = (a: string) => setPicked((p) => (p.includes(a) ? p.filter((x) => x !== a) : [...p, a]));
  const n = picked.length + custom.split("\n").filter((x) => x.trim()).length;
  const start = async () => {
    const areas = [...picked, ...custom.split("\n").map((s) => s.trim()).filter(Boolean)];
    const r = await act.run(() => api.post<Run>("/prospects/find", { areas }), "Search started. Results appear as each city finishes.");
    if (r) { status.runs.reload(); onStarted(); }
  };
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="find-panel">
      <div className="alert warn small">These free public map servers are often busy or down. If a search fails, use the map file instead.</div>
      <p className="muted small">Searches near each city centre ({data.radius_m / 1000} km). About 10–60 seconds per city when the servers work.</p>
      {Object.entries(data.groups).map(([group, areas]) => (
        <div key={group} className="area-group">
          <div className="row between">
            <strong className="small">{group}</strong>
            <span className="row gap-s">
              <button className="link-btn" onClick={() => setPicked((p) => [...new Set([...p, ...areas])])}>all</button>
              <button className="link-btn" onClick={() => setPicked((p) => p.filter((x) => !areas.includes(x)))}>none</button>
            </span>
          </div>
          <div className="chips">
            {areas.map((a) => <button key={a} className={`chip ${picked.includes(a) ? "on" : ""}`} onClick={() => toggle(a)}>{a}</button>)}
          </div>
        </div>
      ))}
      <label className="field">
        Other places (one per line, as <code>Name@lat,lon</code>, e.g. <code>Ooty@11.41,76.70</code>)
        <textarea rows={2} value={custom} onChange={(e) => setCustom(e.target.value)} style={{ minHeight: 50 }} />
      </label>
      {n > 5 && !status.running && <div className="alert warn small">{n} places picked. Start with 2–3; you can run more later.</div>}
      <div className="row gap">
        <button className="btn primary" disabled={act.busy || status.running || !n} onClick={start}>
          {status.running ? "Working…" : `Search ${n} place(s)`}
        </button>
      </div>
      <Msg msg={act.msg} />
    </div>
  );
}

function FindPanel({ onStarted }: { onStarted: () => void }) {
  const status = useRuns(onStarted);
  const [mode, setMode] = useState<"overture" | "file" | "live">("overture");
  return (
    <div className="find-panel">
      <div className="alert info small">New searches keep only businesses <strong>without a website</strong> that list a <strong>valid phone number</strong>. Chains and partner-run places (OYO, franchises, bank branches), colleges, IT companies and government offices are skipped. Independent dealers are kept.</div>
      <div className="seg-tabs">
        <button className={`seg ${mode === "overture" ? "on" : ""}`} onClick={() => setMode("overture")}>Business directory (best)</button>
        <button className={`seg ${mode === "file" ? "on" : ""}`} onClick={() => setMode("file")}>OpenStreetMap file</button>
        <button className={`seg ${mode === "live" ? "on" : ""}`} onClick={() => setMode("live")}>Live map servers</button>
      </div>
      {mode === "overture" ? <OverturePanel status={status} onStarted={onStarted} />
        : mode === "file" ? <MapFilePanel status={status} onStarted={onStarted} /> : <LivePanel status={status} onStarted={onStarted} />}
      <RunStatus {...status} />
    </div>
  );
}

function ProspectDrawer({ p, onClose, onChange }: { p: Prospect; onClose: () => void; onChange: (p: Prospect) => void }) {
  const pitch = useApi(() => api.get<Pitch>(`/prospects/${p.id}/pitch`), [p.id, p.gaps.length]);
  const act = useAction();
  const [notes, setNotes] = useState(p.notes ?? "");
  const [note, setNote] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => setNotes(p.notes ?? ""), [p.id, p.notes]);
  const save = async (body: Partial<Prospect>, ok: string) => {
    const r = await act.run(() => api.patch<Prospect>(`/prospects/${p.id}`, body), ok);
    if (r) onChange(r);
  };
  const log = async (channel: string, outcome: string) => {
    const r = await act.run(() => api.post<Prospect>(`/prospects/${p.id}/contact`, { channel, outcome, note: note || null }), "Saved");
    if (r) { onChange(r); setNote(""); }
  };
  const verifyPhone = async (verified: boolean) => {
    const r = await act.run(() => api.post<Prospect>(`/prospects/${p.id}/phone-verified`, undefined, { verified }), verified ? "Phone marked as working" : "Undone");
    if (r) onChange(r);
  };
  const setSocial = async (activity: string | null) => {
    const r = await act.run(() => api.post<Prospect>(`/prospects/${p.id}/social-activity`, undefined, { activity }), "Saved");
    if (r) onChange(r);
  };
  const audit = async () => {
    const r = await act.run(() => api.post<Prospect>(`/prospects/${p.id}/audit`), "Website checked");
    if (r) onChange(r);
  };
  const copy = async () => {
    if (!pitch.data) return;
    try { await navigator.clipboard.writeText(pitch.data.message); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  };
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} aria-label={p.name}>
        <div className="row between gap drawer-head">
          <div className="row gap" style={{ minWidth: 0 }}>
            <ScoreRing score={p.score} />
            <div style={{ minWidth: 0 }}>
              <h2 className="wrap">{p.name}</h2>
              {p.new_listing && <span className="badge good" style={{ marginRight: 4 }}>🆕 New</span>}
          <div className="muted small">{p.type_label} · {p.area ?? "—"}{p.country ? `, ${p.country}` : ""}</div>
            </div>
          </div>
          <button className="btn sm" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="quick-actions">
          {pitch.data?.links.call && <a className="btn" href={pitch.data.links.call}>📞 Call</a>}
          {pitch.data?.links.whatsapp && <a className="btn" href={pitch.data.links.whatsapp} target="_blank" rel="noopener noreferrer">💬 WhatsApp</a>}
          {pitch.data?.links.email && <a className="btn" href={pitch.data.links.email}>✉️ Email</a>}
          <a className="btn" href={p.source_url} target="_blank" rel="noopener noreferrer">📍 Map</a>
          {p.website && <button className="btn" disabled={act.busy} onClick={audit}>🔎 {p.audited_at ? "Re-check website" : "Check website"}</button>}
        </div>
        <Msg msg={act.msg} />

        <section>
          <div className="row gap-s"><h3 style={{ margin: 0 }}>How sure are we?</h3><NeedBadge level={p.need_level} /></div>
          <ul className="gap-list small" style={{ marginTop: 6 }}>{p.need_reasons.map((r) => <li key={r}>✓ {r}</li>)}</ul>
        </section>

        <section>
          <h3>Why they may need us</h3>
          {p.gaps.length === 0 ? <p className="muted small">No gaps found yet.{p.website && !p.audited_at && " Check their website to find some."}</p> : (
            <ul className="gap-list">
              {p.gaps.map((g, i) => <li key={i}><strong>{g.label}</strong><span className="muted small"> — {g.detail}</span></li>)}
            </ul>
          )}
          <div className="chips" style={{ marginTop: 8 }}>
            {p.recommended_services.map((s) => <span key={s} className="chip on static">{SHORT_SERVICE[s] ?? s}</span>)}
          </div>
        </section>

        <section>
          <h3>Social media</h3>
          {p.social_links.length === 0 ? (
            <p className="muted small">No social pages listed. Search their name on Instagram or Facebook. A busy page with no website is a strong sign they need us.</p>
          ) : (
            <>
              <div className="quick-actions">
                {p.social_links.map((l) => {
                  const url = /^https?:/i.test(l) ? l : /^@?[\w.]+$/.test(l) ? `https://instagram.com/${l.replace(/^@/, "")}` : null;
                  const label = /facebook|fb\.com/i.test(l) ? "Facebook" : /instagram/i.test(l) ? "Instagram" : /youtube/i.test(l) ? "YouTube" : /linkedin/i.test(l) ? "LinkedIn" : "Page";
                  return url ? <a key={l} className="btn sm" href={url} target="_blank" rel="noopener noreferrer">↗ {label}</a> : <span key={l} className="small">{l}</span>;
                })}
              </div>
              <p className="muted xs" style={{ margin: "6px 0" }}>Open their page and tell us how active it is. IOI can’t read social sites itself.</p>
            </>
          )}
          <div className="row gap-s" style={{ flexWrap: "wrap" }}>
            {([["very_active", "🔥 Very active"], ["some", "Some posts"], ["inactive", "Inactive / dead"]] as const).map(([k, label]) => (
              <button key={k} className={`chip ${p.audit?.social_activity === k ? "on" : ""}`} disabled={act.busy} onClick={() => setSocial(p.audit?.social_activity === k ? null : k)}>{label}</button>
            ))}
          </div>
        </section>

        <section>
          <h3>Contact details <span className="muted xs">(from the public listing)</span></h3>
          <dl className="kv">
            <dt>Phone</dt>
            <dd>
              {p.phone ? (
                <div className="stack-s">
                  <div className="row gap-s"><strong className="mono">{p.phone_normalized ?? p.phone}</strong> <PhoneBadge p={p} /></div>
                  {p.phone_normalized && p.phone_normalized.replace(/\D/g, "") !== p.phone.replace(/\D/g, "") && <span className="muted xs">Listed as “{p.phone}”</span>}
                  {p.phone_normalized && (
                    p.phone_verified
                      ? <button className="link-btn xs" onClick={() => verifyPhone(false)}>Undo “number works”</button>
                      : <button className="btn sm good" disabled={act.busy} onClick={() => verifyPhone(true)}>✓ I called, the number works</button>
                  )}
                </div>
              ) : <span className="muted">not listed</span>}
            </dd>
            <dt>Email</dt><dd>{p.email ?? <span className="muted">not listed</span>}</dd>
            <dt>Website</dt><dd>{p.website ? <ExtLink href={/^https?:/i.test(p.website) ? p.website : `http://${p.website}`}>{p.website}</ExtLink> : <span className="muted">none</span>}</dd>
            {p.social_links.length > 0 && <><dt>Social</dt><dd>{p.social_links.map((s) => <div key={s}>{/^https?:/i.test(s) ? <ExtLink href={s}>{s}</ExtLink> : s}</div>)}</dd></>}
            <dt>Address</dt><dd>{p.address ?? "—"}</dd>
            {p.opening_hours && <><dt>Hours</dt><dd>{p.opening_hours}</dd></>}
          </dl>
        </section>

        <section>
          <div className="row between"><h3>Message draft</h3><button className="btn sm" onClick={copy} disabled={!pitch.data}>{copied ? "Copied ✓" : "Copy"}</button></div>
          {pitch.data ? <pre className="pitch">{pitch.data.message}</pre> : <Loading />}
          {pitch.data && <p className="muted xs">Call opener: “{pitch.data.call_script}”</p>}
          <p className="muted xs">Nothing is sent automatically. Review it and send it yourself.</p>
        </section>

        <section>
          <h3>Log what happened</h3>
          <input placeholder="Optional note (e.g. spoke to owner, call back Monday)" value={note} onChange={(e) => setNote(e.target.value)} style={{ width: "100%" }} />
          <div className="row gap-s" style={{ marginTop: 8, flexWrap: "wrap" }}>
            <button className="btn sm" disabled={act.busy} onClick={() => log("call", "contacted")}>Contacted</button>
            <button className="btn sm good" disabled={act.busy} onClick={() => log("call", "interested")}>Interested</button>
            <button className="btn sm" disabled={act.busy} onClick={() => log("call", "not_interested")}>Not interested</button>
            <button className="btn sm good" disabled={act.busy} onClick={() => log("other", "won")}>Won</button>
            <button className="btn sm" disabled={act.busy} onClick={() => save({ status: "shortlisted" }, "Shortlisted")}>⭐ Shortlist</button>
            <button className="btn sm danger" disabled={act.busy} onClick={() => save({ status: "rejected" }, "Skipped")}>Skip</button>
          </div>
          <p className="small muted">Status: <strong>{STATUS_LABEL[p.status] ?? p.status}</strong>{p.next_follow_up && <> · follow up {fmtDate(p.next_follow_up)}</>}</p>
          {p.contact_log.length > 0 && (
            <ul className="list-plain small">
              {[...p.contact_log].reverse().map((c, i) => <li key={i}>{fmtDate(c.at, true)} · {c.channel} · <strong>{STATUS_LABEL[c.outcome] ?? c.outcome}</strong>{c.note && <span className="muted"> — {c.note}</span>}</li>)}
            </ul>
          )}
        </section>

        <section>
          <h3>Notes</h3>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
          <button className="btn sm" disabled={act.busy || notes === (p.notes ?? "")} onClick={() => save({ notes }, "Notes saved")}>Save notes</button>
        </section>

        <details className="small">
          <summary className="muted">How the score was worked out</summary>
          <ul>{p.score_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          <p className="muted xs">Source: <ExtLink href={p.source_url}>OpenStreetMap record</ExtLink> (ODbL). Facts come only from this listing or the website check.</p>
        </details>
      </aside>
    </div>
  );
}

function UpgradeBar({ onDone, pending, need, setNeed }: { onDone: () => void; pending: number; need: string; setNeed: (v: string) => void }) {
  const act = useAction();
  const run = async () => {
    const r = await act.run(() => api.post("/prospects/check-websites", { limit: 200 }), "Checking 200 websites in the background (about 5–10 minutes). Results appear as they finish.");
    if (r) setTimeout(onDone, 60000);
  };
  return (
    <div className="alert info small">
      <span>
        Businesses that have a website. We check each homepage (HTTPS, mobile-friendly, SEO basics, WhatsApp/chat, enquiry form, outdated) and list the ones
        that are broken or weak. <strong>{pending.toLocaleString()}</strong> not checked yet.{" "}
        <button className="link-btn" onClick={() => setNeed(need === "check_site" ? "upgrade" : "check_site")}>{need === "check_site" ? "Show weak sites" : "Show unchecked"}</button>
      </span>
      <button className="btn sm primary" disabled={act.busy} onClick={run}>Check 200 websites</button>
      <Msg msg={act.msg} />
    </div>
  );
}

export function ProspectCard({ p, onOpen }: { p: Prospect; onOpen: () => void }) {
  return (
    <button className="p-card" onClick={onOpen}>
      <ScoreRing score={p.score} />
      <div className="p-body">
        <div className="row between gap-s">
          <strong className="wrap">{p.name}</strong>
          {p.status !== "new" && <span className={`badge st-${p.status}`}>{STATUS_LABEL[p.status] ?? p.status}</span>}
        </div>
        <div className="muted small">{p.type_label} · {p.area ?? "—"}{p.state && p.state !== p.area ? `, ${p.state}` : ""}</div>
        <div className="row gap-s">{p.quality_level && <span className={`badge ${QUALITY[p.quality_level][1]}`}>{QUALITY[p.quality_level][0]}</span>}<NeedBadge level={p.need_level} /><PhoneBadge p={p} />{p.social_links.length > 0 && <span className="badge" title="Has social media pages">👥 {p.audit?.social_activity === "very_active" ? "very active" : "social"}</span>}</div>
        <div className="chips tight">
          {p.gaps.slice(0, 3).map((g) => <span key={g.key} className="chip warn static">{g.label}</span>)}
          {p.gaps.length > 3 && <span className="chip static">+{p.gaps.length - 3}</span>}
        </div>
        <div className="muted xs">Pitch: {p.recommended_services.slice(0, 3).map((s) => SHORT_SERVICE[s] ?? s).join(" · ")}</div>
      </div>
      <div className="p-contact xs muted">
        {p.phone ? "📞" : ""}{p.email ? " ✉️" : ""}{p.social_links.length ? " 👥" : ""}
      </div>
    </button>
  );
}

export default function Prospects() {
  const [segment, setSegment] = useState("");
  const [status, setStatus] = useState("open");
  const [area, setArea] = useState("");
  const [noSite, setNoSite] = useState(true);
  const [phone, setPhone] = useState("");
  const [need, setNeed] = useState("definite");
  const [group, setGroup] = useState<"none" | "upgrade" | "colleges">("none");
  const [quality, setQuality] = useState("good");
  const [stateF, setStateF] = useState("");
  const [focus, setFocus] = useState("");
  const [service, setService] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [showFind, setShowFind] = useState(false);
  const [view, setView] = useState<"list" | "map">(() => (new URLSearchParams(window.location.search).get("view") === "map" ? "map" : "list"));
  const [open, setOpen] = useState<Prospect | null>(null);
  const summary = useApi(() => api.get<Summary & { by_area: Record<string, number> }>("/prospects/summary"));
  const groupFilters = () =>
    group === "upgrade" ? { has_website: true, need: need === "check_site" ? "check_site" : "upgrade", segment: segment || undefined }
      : group === "colleges" ? { segment: "college" }
      : { segment, need, has_website: noSite ? false : undefined };
  const list = useApi(
    () => api.get<Page>("/prospects", { ...groupFilters(), status, area, q, service, phone, quality, state: stateF, focus, offset, limit: 30 }),
    [segment, status, area, q, service, noSite, phone, need, group, quality, stateF, focus, offset],
  );
  useEffect(() => setOffset(0), [segment, status, area, q, service, noSite, phone, need, group, quality, stateF, focus]);
  const s = summary.data;
  useEffect(() => { if (s && s.total === 0) setShowFind(true); }, [s?.total]);  // nothing yet → show the finder
  const refresh = () => { list.reload(); summary.reload(); };
  const exportUrl = `/api/prospects/export.csv?${new URLSearchParams(Object.entries({ ...Object.fromEntries(Object.entries(groupFilters()).map(([k, v]) => [k, v === undefined ? "" : String(v)])), status, area, service, phone, quality, state: stateF }).filter(([, v]) => v) as [string, string][]).toString()}`;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Prospects</h1>
          <p className="muted">Businesses and professionals who could use our help. They haven’t asked yet, but they have no website or a weak one, or they could use CRM, AI or ERP.</p>
        </div>
        <div className="row gap">
          <a className="btn" href={exportUrl}>Export CSV</a>
          <button className="btn primary" onClick={() => setShowFind((v) => !v)}>{showFind ? "Close" : "＋ Find prospects"}</button>
        </div>
      </header>
      {showFind && <section className="card"><FindPanel onStarted={refresh} /></section>}
      {s && (
        <div className="stat-row">
          <div className="stat"><span className="stat-num">{s.total}</span><span>prospects</span></div>
          <div className="stat"><span className="stat-num">{s.no_website}</span><span>no website</span></div>
          <div className="stat hot"><span className="stat-num">{s.definite}</span><span>definitely need us</span></div>
          <div className="stat"><span className="stat-num">{s.follow_ups_due}</span><span>follow-ups due</span></div>
        </div>
      )}
      <div className="seg-tabs big-tabs" role="tablist">
        {([["none", "🚫 No website", s?.no_website], ["upgrade", "🛠️ Website needs upgrade", s?.by_need?.upgrade], ["colleges", "🎓 Colleges", undefined]] as const).map(([k, label, n]) => (
          <button key={k} className={`seg ${group === k ? "on" : ""}`} onClick={() => setGroup(k)}>{label}{n != null && <span className="seg-count">{Number(n).toLocaleString()}</span>}</button>
        ))}
      </div>
      {group !== "colleges" && <div className="row gap-s" style={{ margin: "0 0 10px", flexWrap: "wrap" }}>
        <span className="small muted">Focus:</span>
        {FOCUS.map(([k, v]) => <button key={k} className={`chip ${focus === k ? "on" : ""}`} onClick={() => setFocus(k)}>{v}{k === "new" && s?.new_listings ? ` (${s.new_listings.toLocaleString()})` : ""}</button>)}
      </div>}
      {group === "upgrade" && <UpgradeBar onDone={refresh} pending={s?.by_need?.check_site ?? 0} need={need} setNeed={setNeed} />}
      {group === "none" && <div className="seg-tabs" role="tablist">
        {SEGMENTS.filter((sg) => sg.id !== "college").map((sg) => (
          <button key={sg.id} role="tab" aria-selected={segment === sg.id} className={`seg ${segment === sg.id ? "on" : ""}`} onClick={() => setSegment(sg.id)} title={sg.hint}>
            {sg.label}{s && sg.id && <span className="seg-count">{s.by_segment[sg.id] ?? 0}</span>}
          </button>
        ))}
      </div>}
      <div className="filters">
        <input placeholder="Search name or type…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="open">To work on</option>
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Area">
          <option value="">All places</option>
          {s && Object.keys(s.by_area).sort().map((a) => <option key={a} value={a}>{a} ({s.by_area[a]})</option>)}
        </select>
        <select value={service} onChange={(e) => setService(e.target.value)} aria-label="Service">
          <option value="">Any service</option>
          {Object.entries(SHORT_SERVICE).slice(0, 7).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        {group === "none" && <select value={need} onChange={(e) => setNeed(e.target.value)} aria-label="How sure">
          <option value="definite">Definitely needs us</option>
          <option value="likely">Likely or definitely</option>
          <option value="">Show everyone</option>
        </select>}
        <select value={quality} onChange={(e) => setQuality(e.target.value)} aria-label="Business quality">
          <option value="established">Established businesses</option>
          <option value="good">Good and established</option>
          <option value="">Include small businesses</option>
        </select>
        <select value={stateF} onChange={(e) => setStateF(e.target.value)} aria-label="State">
          <option value="">All states</option>
          {s && Object.entries(s.by_state ?? {}).map(([k, v]) => <option key={k} value={k}>{k === "unknown" ? "State unknown" : k} ({v.toLocaleString()})</option>)}
        </select>
        <select value={phone} onChange={(e) => setPhone(e.target.value)} aria-label="Phone">
          <option value="">Any phone</option>
          <option value="usable">Valid phone number</option>
          <option value="mobile">Mobile only (WhatsApp)</option>
          <option value="verified">Number confirmed by me</option>
        </select>
        {group === "none" && <label className="check"><input type="checkbox" checked={noSite} onChange={(e) => setNoSite(e.target.checked)} /> No website only</label>}
      </div>
      <div className="seg-tabs">
        <button className={`seg ${view === "list" ? "on" : ""}`} onClick={() => setView("list")}>☰ List</button>
        <button className={`seg ${view === "map" ? "on" : ""}`} onClick={() => setView("map")}>🗺️ Map</button>
      </div>
      {view === "map" && (
        <Suspense fallback={<Loading />}>
          <ProspectMap
            filters={{ ...groupFilters(), status, q, service, phone, quality, state: stateF, focus }}
            onOpen={async (id) => { try { setOpen(await api.get<Prospect>(`/prospects/${id}`)); } catch { /* ignore */ } }}
          />
        </Suspense>
      )}
      {view === "list" && <>
      <ErrorBox error={list.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.items.length === 0 && (
        <Empty>
          No prospects here yet. <button className="link-btn" onClick={() => setShowFind(true)}>Find prospects</button> in your cities to start.
        </Empty>
      )}
      <div className="p-grid">
        {list.data?.items.map((p) => <ProspectCard key={p.id} p={p} onOpen={() => setOpen(p)} />)}
      </div>
      {list.data && <Pager total={list.data.total} limit={list.data.limit} offset={list.data.offset} onChange={setOffset} />}
      </>}
      {open && (
        <ProspectDrawer
          p={open}
          onClose={() => setOpen(null)}
          onChange={(np) => { setOpen(np); list.setData((d) => d && { ...d, items: d.items.map((x) => (x.id === np.id ? np : x)) }); summary.reload(); }}
        />
      )}
    </>
  );
}

export { ProspectDrawer };
