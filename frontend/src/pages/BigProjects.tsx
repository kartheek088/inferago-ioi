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
  state: string | null;
  fit: string | null;
  links: { company: string; role: string; quote: string; url: string; confirmed: boolean | null }[];
  contact_log: { at: string; channel: string; outcome: string; note: string | null }[];
  next_follow_up: string | null;
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
  follow_ups_due: number;
  by_state: Record<string, number>;
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
const STATUS: Record<string, string> = { new: "New", shortlisted: "Shortlisted", contacted: "Contacted", interested: "Interested", not_interested: "Not interested", won: "Won 🎉", rejected: "Skip", follow_up: "Follow-ups" };

function Detail({ lead, onChange }: { lead: Lead; onChange: (l: Lead) => void }) {
  const ap = useApi(() => api.get<Approach>(`/big-projects/${lead.id}/approach`), [lead.id]);
  const act = useAction();
  const [notes, setNotes] = useState(lead.notes ?? "");
  const [copied, setCopied] = useState(false);
  const [channel, setChannel] = useState("call");
  const [logNote, setLogNote] = useState("");
  const logContact = async (outcome: string) => {
    const r = await act.run(() => api.post<Lead>(`/big-projects/${lead.id}/contact`, { channel, outcome, note: logNote || null }), "Saved");
    if (r) { onChange(r); setLogNote(""); }
  };
  const confirm = async (i: number, ok: boolean) => {
    const r = await act.run(() => api.post<Lead>(`/big-projects/${lead.id}/links/${i}`, { confirmed: ok }));
    if (r) onChange(r);
  };
  const save = async (body: Partial<Lead>, ok: string) => {
    const r = await act.run(() => api.patch<Lead>(`/big-projects/${lead.id}`, body), ok);
    if (r) onChange(r);
  };
  return (
    <div className="bp-detail">
      {lead.summary && <p className="small">{lead.summary}</p>}
      {lead.fit && <p className="small fit"><strong>Where we fit:</strong> {lead.fit}</p>}
      <div className="chips">{lead.services.map((s) => <span key={s} className="chip on static">{SERVICE[s] ?? s}</span>)}</div>
      {lead.links.length > 0 && (
        <div>
          <strong className="small">Connected companies (from the article): a way in through local vendors</strong>
          <ul className="list-plain small">
            {lead.links.map((l, i) => (
              <li key={i}>
                <div className="row between gap-s">
                  <span><strong>{l.company}</strong> <span className="badge">{l.role}</span> {l.confirmed === true && <span className="badge good">✓ confirmed</span>}{l.confirmed === false && <span className="badge bad">wrong</span>}</span>
                  <span className="row gap-s">
                    <a className="btn sm" href={`https://www.google.com/search?q=${encodeURIComponent(l.company + " contact")}`} target="_blank" rel="noopener noreferrer">🔎</a>
                    <button className="btn sm" onClick={() => confirm(i, true)}>✓</button>
                    <button className="btn sm" onClick={() => confirm(i, false)}>✕</button>
                  </span>
                </div>
                <div className="xs muted">“{l.quote}”</div>
              </li>
            ))}
          </ul>
        </div>
      )}
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
      <strong className="small">Log what happened</strong>
      <div className="row gap-s" style={{ flexWrap: "wrap" }}>
        <select value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="How">
          <option value="call">Call</option><option value="whatsapp">WhatsApp</option><option value="email">Email</option>
          <option value="linkedin">LinkedIn</option><option value="intro">Intro via vendor</option><option value="visit">Visit</option>
        </select>
        <input placeholder="Note" value={logNote} onChange={(e) => setLogNote(e.target.value)} style={{ flex: 1, minWidth: 160 }} />
      </div>
      <div className="row gap-s" style={{ flexWrap: "wrap" }}>
        <button className="btn sm" disabled={act.busy} onClick={() => save({ status: "shortlisted" }, "Shortlisted")}>⭐ Shortlist</button>
        <button className="btn sm" disabled={act.busy} onClick={() => logContact("contacted")}>Contacted</button>
        <button className="btn sm good" disabled={act.busy} onClick={() => logContact("interested")}>Interested</button>
        <button className="btn sm" disabled={act.busy} onClick={() => logContact("not_interested")}>Not interested</button>
        <button className="btn sm good" disabled={act.busy} onClick={() => logContact("won")}>Won</button>
        <button className="btn sm danger" disabled={act.busy} onClick={() => save({ status: "rejected" }, "Skipped")}>Skip</button>
      </div>
      {lead.next_follow_up && <p className="xs muted">Follow up on {fmtDate(lead.next_follow_up)}</p>}
      {lead.contact_log.length > 0 && <ul className="list-plain xs">{[...lead.contact_log].reverse().map((x, i) => <li key={i}>{fmtDate(x.at, true)} · {x.channel} · <strong>{STATUS[x.outcome] ?? x.outcome}</strong>{x.note && ` — ${x.note}`}</li>)}</ul>}
      <textarea placeholder="Notes (who you spoke to, next step…)" value={notes} onChange={(e) => setNotes(e.target.value)} style={{ minHeight: 60 }} />
      <button className="btn sm" disabled={act.busy || notes === (lead.notes ?? "")} onClick={() => save({ notes }, "Notes saved")}>Save notes</button>
      <Msg msg={act.msg} />
      <details className="small"><summary className="muted">How the score was worked out</summary><ul>{lead.score_reasons.map((r) => <li key={r}>{r}</li>)}</ul></details>
    </div>
  );
}

export default function BigProjects() {
  const [type, setType] = useState("");
  const [state, setState] = useState("");
  const [status, setStatus] = useState("open");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const summary = useApi(() => api.get<Summary>("/big-projects/summary"));
  const list = useApi(() => api.get<Page>("/big-projects", { project_type: type, state, status, q, offset, limit: 25 }), [type, state, status, q, offset]);
  const act = useAction();
  const find = async () => {
    const r = await act.run(() => api.post<{ new: number; matched: number; articles: number; links_found: number; feeds_failed: string[] }>("/big-projects/find"));
    if (r) {
      act.setMsg({ kind: r.feeds_failed.length ? "err" : "ok", text: `Read ${r.articles} news articles: ${r.matched} private projects where we fit, ${r.new} new, ${r.links_found} connected companies found.${r.feeds_failed.length ? ` Some sources failed: ${r.feeds_failed.join("; ")}` : ""}` });
      list.reload(); summary.reload();
    }
  };
  const s = summary.data;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Big projects</h1>
          <p className="muted">Private companies opening a hospital, hotel, showroom, housing project or factory, or expanding. These projects need websites, booking/lead CRMs, WhatsApp bots, ERP and automation, and are built with local vendors, so you can get in directly or through them. No tenders or government work.</p>
        </div>
        <div className="row gap">
          <a className="btn" href={`/api/big-projects/export.csv?${new URLSearchParams(Object.entries({ state, status }).filter(([, v]) => v) as [string, string][]).toString()}`}>Export CSV</a>
          <button className="btn primary" disabled={act.busy} onClick={find}>{act.busy ? "Reading the news…" : "🔄 Check the news now"}</button>
        </div>
      </header>
      <Msg msg={act.msg} />
      {s && (
        <div className="stat-row">
          <div className="stat"><span className="stat-num">{s.total}</span><span>open projects</span></div>
          <div className="stat hot"><span className="stat-num">{s.tamil_nadu}</span><span>in Tamil Nadu</span></div>
          <div className="stat"><span className="stat-num">{Object.keys(s.by_state).filter((k) => k !== "unknown").length}</span><span>states</span></div>
          <div className="stat"><span className="stat-num">{s.follow_ups_due}</span><span>follow-ups due</span></div>
        </div>
      )}
      {s?.last_run && <p className="muted xs">Last checked {fmtDate(s.last_run.at, true)} · checks automatically twice a day · sources: {Object.keys(s.feeds).join(", ")}</p>}
      <div className="seg-tabs">
        {[["", "All"], ["new_facility", "New hospital / hotel / plant / outlet"], ["expansion", "Expansion"], ["launch", "New brand / outlets"], ["partnership", "Partnership"]].map(([k, v]) => (
          <button key={k} className={`seg ${type === k ? "on" : ""}`} onClick={() => setType(k)}>{v}{s && k && <span className="seg-count">{s.by_type[k] ?? 0}</span>}</button>
        ))}
      </div>
      <div className="filters">
        <input placeholder="Search company or headline…" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
        <select value={state} onChange={(e) => { setState(e.target.value); setOffset(0); }} aria-label="State">
          <option value="">All states</option>
          {s && Object.entries(s.by_state).map(([k, v]) => <option key={k} value={k}>{k === "unknown" ? "State not named" : k} ({v})</option>)}
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} aria-label="Status">
          <option value="open">To work on</option>
          <option value="follow_up">Follow-ups</option>
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
                  {(l.state || l.location) && <span className="badge good">📍 {[l.location, l.state].filter(Boolean).join(", ")}</span>}
                  {l.links.length > 0 && <span className="badge info">🔗 {l.links.length} connected</span>}
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
