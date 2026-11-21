import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorBox, ExtLink, Loading, Msg, Pager, fmtDate, useAction, useApi } from "../components/ui";

interface Lead {
  id: number;
  url: string;
  title: string;
  summary: string | null;
  feed: string;
  published_at: string | null;
  company: string | null;
  project_type: string;
  amount_text: string | null;
  location: string | null;
  services: string[];
  score: number;
  score_reasons: string[];
  status: string;
  notes: string | null;
}
interface Page { items: Lead[]; total: number; limit: number; offset: number }
interface Summary {
  total: number;
  tamil_nadu: number;
  by_type: Record<string, number>;
  type_labels: Record<string, string>;
  feeds: Record<string, string>;
  last_run: { at: string; new: number; matched: number; articles: number; feeds_ok: number; feeds_failed: string[] } | null;
}
interface Approach { message: string; links: { article: string; find_company: string | null; linkedin_search: string | null }; how_to: string[]; note: string }

const SERVICE: Record<string, string> = {
  website: "Website", marketing: "SEO & marketing", crm: "CRM", ai: "AI", erp: "ERP / SAP", strategy: "Strategy",
  automation: "Automation", integration: "Integration", backend: "Custom software", api: "APIs", internal_apps: "Dashboards / internal apps",
};
const STATUS: Record<string, string> = { new: "New", shortlisted: "Shortlisted", contacted: "Contacted", interested: "Interested", not_interested: "Not interested", won: "Won 🎉", rejected: "Skip" };

function Detail({ lead, onChange }: { lead: Lead; onChange: (l: Lead) => void }) {
  const ap = useApi(() => api.get<Approach>(`/big-projects/${lead.id}/approach`), [lead.id]);
  const act = useAction();
  const [notes, setNotes] = useState(lead.notes ?? "");
  const [copied, setCopied] = useState(false);
  const save = async (body: Partial<Lead>, ok: string) => {
    const r = await act.run(() => api.patch<Lead>(`/big-projects/${lead.id}`, body), ok);
    if (r) onChange(r);
  };
  return (
    <div className="bp-detail">
      {lead.summary && <p className="small">{lead.summary}</p>}
      <div className="chips">{lead.services.map((s) => <span key={s} className="chip on static">{SERVICE[s] ?? s}</span>)}</div>
      {ap.data && (
        <>
          <div className="quick-actions">
            <a className="btn sm" href={ap.data.links.article} target="_blank" rel="noopener noreferrer">📰 Read article</a>
            {ap.data.links.find_company && <a className="btn sm" href={ap.data.links.find_company} target="_blank" rel="noopener noreferrer">🔎 Find company contact</a>}
            {ap.data.links.linkedin_search && <a className="btn sm" href={ap.data.links.linkedin_search} target="_blank" rel="noopener noreferrer">👥 LinkedIn</a>}
          </div>
          <ol className="small">{ap.data.how_to.map((h) => <li key={h}>{h}</li>)}</ol>
          <div className="row between"><strong className="small">Message draft</strong>
            <button className="btn sm" onClick={async () => { try { await navigator.clipboard.writeText(ap.data!.message); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ } }}>{copied ? "Copied ✓" : "Copy"}</button>
          </div>
          <pre className="pitch">{ap.data.message}</pre>
          <p className="muted xs">{ap.data.note}</p>
        </>
      )}
      <div className="row gap-s" style={{ flexWrap: "wrap" }}>
        <button className="btn sm" disabled={act.busy} onClick={() => save({ status: "shortlisted" }, "Shortlisted")}>⭐ Shortlist</button>
        <button className="btn sm" disabled={act.busy} onClick={() => save({ status: "contacted" }, "Marked contacted")}>Contacted</button>
        <button className="btn sm good" disabled={act.busy} onClick={() => save({ status: "interested" }, "Marked interested")}>Interested</button>
        <button className="btn sm good" disabled={act.busy} onClick={() => save({ status: "won" }, "Won!")}>Won</button>
        <button className="btn sm danger" disabled={act.busy} onClick={() => save({ status: "rejected" }, "Skipped")}>Skip</button>
      </div>
      <textarea placeholder="Notes (who you spoke to, next step…)" value={notes} onChange={(e) => setNotes(e.target.value)} style={{ minHeight: 60 }} />
      <button className="btn sm" disabled={act.busy || notes === (lead.notes ?? "")} onClick={() => save({ notes }, "Notes saved")}>Save notes</button>
      <Msg msg={act.msg} />
      <details className="small"><summary className="muted">How the score was worked out</summary><ul>{lead.score_reasons.map((r) => <li key={r}>{r}</li>)}</ul></details>
    </div>
  );
}

export default function BigProjects() {
  const [type, setType] = useState("");
  const [near, setNear] = useState("");
  const [status, setStatus] = useState("open");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const summary = useApi(() => api.get<Summary>("/big-projects/summary"));
  const list = useApi(() => api.get<Page>("/big-projects", { project_type: type, near, status, q, offset, limit: 25 }), [type, near, status, q, offset]);
  const act = useAction();
  const find = async () => {
    const r = await act.run(() => api.post<{ new: number; matched: number; articles: number; feeds_failed: string[] }>("/big-projects/find"));
    if (r) {
      act.setMsg({ kind: r.feeds_failed.length ? "err" : "ok", text: `Read ${r.articles} news articles, ${r.matched} were about projects, ${r.new} new.${r.feeds_failed.length ? ` Some sources failed: ${r.feeds_failed.join("; ")}` : ""}` });
      list.reload(); summary.reload();
    }
  };
  const s = summary.data;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Big projects</h1>
          <p className="muted">Companies in the news that just won a contract, are building a plant, or are expanding. They often need outside help to deliver: software, dashboards, automation, ERP/CRM, websites. You can approach them directly as a vendor or delivery partner.</p>
        </div>
        <button className="btn primary" disabled={act.busy} onClick={find}>{act.busy ? "Reading the news…" : "🔄 Check the news now"}</button>
      </header>
      <Msg msg={act.msg} />
      {s && (
        <div className="stat-row">
          <div className="stat"><span className="stat-num">{s.total}</span><span>open projects</span></div>
          <div className="stat hot"><span className="stat-num">{s.tamil_nadu}</span><span>in Tamil Nadu</span></div>
          <div className="stat"><span className="stat-num">{s.by_type.contract_won ?? 0}</span><span>contracts won</span></div>
          <div className="stat"><span className="stat-num">{(s.by_type.new_facility ?? 0) + (s.by_type.investment ?? 0)}</span><span>new plants & expansions</span></div>
        </div>
      )}
      {s?.last_run && <p className="muted xs">Last checked {fmtDate(s.last_run.at, true)} · checks automatically twice a day · sources: {Object.keys(s.feeds).join(", ")}</p>}
      <div className="seg-tabs">
        {[["", "All"], ["contract_won", "Won a contract"], ["new_facility", "New plant / facility"], ["investment", "Investment / expansion"], ["mou", "MoU / partnership"]].map(([k, v]) => (
          <button key={k} className={`seg ${type === k ? "on" : ""}`} onClick={() => setType(k)}>{v}{s && k && <span className="seg-count">{s.by_type[k] ?? 0}</span>}</button>
        ))}
      </div>
      <div className="filters">
        <input placeholder="Search company or headline…" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        <select value={near} onChange={(e) => { setNear(e.target.value); setOffset(0); }} aria-label="Where">
          <option value="">Anywhere</option>
          <option value="tamil_nadu">Tamil Nadu only</option>
          <option value="india">Place named in the news</option>
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} aria-label="Status">
          <option value="open">To work on</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <ErrorBox error={list.error || summary.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {list.data && list.data.items.length === 0 && <Empty>No projects yet. Click <strong>Check the news now</strong>.</Empty>}
      <div className="bp-list">
        {list.data?.items.map((l) => (
          <article key={l.id} className={`bp-card ${open === l.id ? "open" : ""}`}>
            <button className="bp-head" onClick={() => setOpen(open === l.id ? null : l.id)}>
              <span className={`bp-score ${l.score >= 60 ? "hot" : l.score >= 45 ? "warm" : ""}`}>{Math.round(l.score)}</span>
              <span className="bp-main">
                <strong className="wrap">{l.title}</strong>
                <span className="row gap-s small muted" style={{ marginTop: 4 }}>
                  <span className="badge">{s?.type_labels[l.project_type] ?? l.project_type}</span>
                  {l.company && <span className="badge info" title="Read from the headline — check it">🏢 {l.company}</span>}
                  {l.amount_text && <span className="badge warn">{l.amount_text}</span>}
                  {l.location && <span className="badge good">📍 {l.location}</span>}
                  {l.status !== "new" && <span className="badge">{STATUS[l.status] ?? l.status}</span>}
                  <span>{l.feed} · {fmtDate(l.published_at)}</span>
                </span>
              </span>
              <span aria-hidden className="muted">{open === l.id ? "▾" : "▸"}</span>
            </button>
            {open === l.id && <Detail lead={l} onChange={(nl) => list.setData((d) => d && { ...d, items: d.items.map((x) => (x.id === nl.id ? nl : x)) })} />}
          </article>
        ))}
      </div>
      {list.data && <Pager total={list.data.total} limit={list.data.limit} offset={list.data.offset} onChange={setOffset} />}
      <p className="muted xs">Read from public news feeds that allow it. Company names come from headlines; check the article before contacting. Nothing is sent automatically. <ExtLink href="https://www.thehindubusinessline.com">BusinessLine</ExtLink></p>
    </>
  );
}
