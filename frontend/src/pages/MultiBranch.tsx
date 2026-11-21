import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorBox, ExtLink, Loading, Msg, Pager, fmtDate, useAction, useApi } from "../components/ui";

interface Branch { name: string; address: string | null; city: string | null; state: string | null; phone: string | null; source_url: string }
interface Chain {
  id: number; name: string; type_label: string; segment: string; branch_count: number; cities: string[]; states: string[];
  main_state: string | null; phones: string[]; socials: string[]; has_website: boolean; evidence: string; evidence_detail: string | null;
  branches: Branch[]; services: string[]; score: number; score_reasons: string[]; status: string; notes: string | null;
  contact_log: { at: string; channel: string; outcome: string; note: string | null }[]; next_follow_up: string | null;
}
interface Page { items: Chain[]; total: number; limit: number; offset: number }
interface Summary { total: number; no_website: number; branches: number; strong: number; by_state: Record<string, number> }

const SERVICE: Record<string, string> = { website: "Website", marketing: "SEO & Google listings", crm: "Multi-branch CRM", integration: "Billing / POS integration",
  internal_apps: "Branch dashboard", ai: "WhatsApp / AI bot", erp: "ERP" };
const STATUS: Record<string, string> = { new: "New", contacted: "Contacted", no_answer: "No answer", callback: "Call back", interested: "Interested",
  qualified: "Qualified", proposal: "Proposal sent", won: "Won 🎉", not_interested: "Not interested", rejected: "Skip", shortlisted: "Shortlisted" };

function wa(phone: string, name: string, branches: number, sender: { name: string; link: string } | null) {
  const d = phone.replace(/\D/g, "");
  const me = sender?.name ? `I'm ${sender.name} from Inferago Tech Services` : "I'm from Inferago Tech Services";
  const msg = `Hi ${name} team 🙏\n\n${me}, a small registered (Udyam MSME) tech team in Tamil Nadu. I noticed you have ${branches} branches. ` +
    `I can show you, free, how one simple system could put every branch on Google and track all branch enquiries in one place.\n\n` +
    `Shall I send it? Just reply yes. If you'd rather not hear from me, reply no and I won't message again.` +
    (sender?.link ? `\n\nAbout us: ${sender.link}` : "");
  return `https://wa.me/${d}?text=${encodeURIComponent(msg)}`;
}

function Detail({ c, onChange }: { c: Chain; onChange: (c: Chain) => void }) {
  const act = useAction();
  const sender = useApi(() => api.get<{ sender_name: string; sender_link: string }>("/prospects/outreach-status"));
  const [note, setNote] = useState("");
  const log = async (outcome: string, channel = "call") => {
    const r = await act.run(() => api.post<Chain>(`/multi-branch/${c.id}/contact`, { channel, outcome, note: note || null,
      callback_at: outcome === "callback" ? new Date(Date.now() + 86400000).toISOString() : null }), "Saved");
    if (r) { onChange(r); setNote(""); }
  };
  return (
    <div className="bp-detail">
      <p className="small"><strong>Why we think it's one business:</strong> {c.evidence_detail}</p>
      <div className="chips">{c.services.map((s) => <span key={s} className="chip on static">{SERVICE[s] ?? s}</span>)}</div>
      <div className="quick-actions">
        {c.phones.slice(0, 3).map((ph) => <a key={ph} className="btn sm" href={`tel:${ph}`}>📞 {ph}</a>)}
        {c.phones[0] && <a className="btn sm" href={wa(c.phones[0], c.name, c.branch_count, sender.data ? { name: sender.data.sender_name, link: sender.data.sender_link } : null)} target="_blank" rel="noopener noreferrer">💬 WhatsApp</a>}
        {c.socials.slice(0, 2).map((s) => /^https?:/.test(s) && <a key={s} className="btn sm" href={s} target="_blank" rel="noopener noreferrer">👥 Page</a>)}
      </div>
      <details open className="small">
        <summary className="muted">{c.branches.length} branches</summary>
        <ul className="list-plain small">
          {c.branches.map((b, i) => (
            <li key={i}>{b.name} · {b.city ?? "—"}{b.state ? `, ${b.state}` : ""}{b.address ? <span className="muted"> · {b.address}</span> : null}
              {b.phone && <> · <a href={`tel:${b.phone}`}>{b.phone}</a></>} · <ExtLink href={b.source_url}>map</ExtLink></li>
          ))}
        </ul>
      </details>
      <input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row gap-s" style={{ flexWrap: "wrap" }}>
        <button className="btn sm" disabled={act.busy} onClick={() => log("no_answer")}>No answer</button>
        <button className="btn sm" disabled={act.busy} onClick={() => log("callback")}>Call back tomorrow</button>
        <button className="btn sm" disabled={act.busy} onClick={() => log("contacted", "whatsapp")}>Sent WhatsApp</button>
        <button className="btn sm good" disabled={act.busy} onClick={() => log("interested")}>Interested</button>
        <button className="btn sm good" disabled={act.busy} onClick={() => log("qualified")}>Qualified</button>
        <button className="btn sm" disabled={act.busy} onClick={() => log("not_interested")}>Not interested</button>
        <button className="btn sm danger" disabled={act.busy} onClick={() => log("rejected")}>Skip</button>
      </div>
      <Msg msg={act.msg} />
      {c.contact_log.length > 0 && (
        <ul className="list-plain xs">{[...c.contact_log].reverse().map((x, i) => <li key={i}>{fmtDate(x.at, true)} · {x.channel} · <strong>{STATUS[x.outcome] ?? x.outcome}</strong>{x.note && ` — ${x.note}`}</li>)}</ul>
      )}
      <details className="small"><summary className="muted">How the score was worked out</summary><ul>{c.score_reasons.map((r) => <li key={r}>{r}</li>)}</ul></details>
    </div>
  );
}

export default function MultiBranch() {
  const [state, setState] = useState("");
  const [noSite, setNoSite] = useState(true);
  const [strong, setStrong] = useState(false);
  const [minB, setMinB] = useState("3");
  const [status, setStatus] = useState("open");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const summary = useApi(() => api.get<Summary>("/multi-branch/summary"));
  const list = useApi(() => api.get<Page>("/multi-branch", { state, q, status, has_website: noSite ? false : undefined, evidence: strong ? "shared_contact" : undefined,
    min_branches: minB, offset, limit: 25 }), [state, q, status, noSite, strong, minB, offset]);
  const act = useAction();
  const find = async () => {
    const r = await act.run(() => api.post("/multi-branch/find"), "Search started (about 1–2 minutes). Refresh when it finishes.");
    if (r) setTimeout(() => { list.reload(); summary.reload(); }, 90000);
  };
  const s = summary.data;
  const reset = () => setOffset(0);
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Multi-branch businesses</h1>
          <p className="muted">Local and regional businesses with several branches: sweets and bakery chains, clinics, salons, schools, showrooms. One deal can cover every branch. Big national brands are left out.</p>
        </div>
        <button className="btn primary" disabled={act.busy} onClick={find}>🔄 Find again</button>
      </header>
      <Msg msg={act.msg} />
      {s && (
        <div className="stat-row">
          <div className="stat"><span className="stat-num">{s.total.toLocaleString()}</span><span>multi-branch businesses</span></div>
          <div className="stat"><span className="stat-num">{s.branches.toLocaleString()}</span><span>branches in total</span></div>
          <div className="stat hot"><span className="stat-num">{s.no_website.toLocaleString()}</span><span>with no website</span></div>
          <div className="stat"><span className="stat-num">{s.strong.toLocaleString()}</span><span>confirmed by shared phone/page</span></div>
        </div>
      )}
      <div className="filters">
        <input placeholder="Search name or type…" value={q} onChange={(e) => { setQ(e.target.value); reset(); }} />
        <select value={state} onChange={(e) => { setState(e.target.value); reset(); }} aria-label="State">
          <option value="">All states</option>
          {s && Object.entries(s.by_state).map(([k, v]) => <option key={k} value={k}>{k === "unknown" ? "State unknown" : k} ({v})</option>)}
        </select>
        <select value={minB} onChange={(e) => { setMinB(e.target.value); reset(); }} aria-label="Branches">
          <option value="3">3+ branches</option><option value="5">5+ branches</option><option value="10">10+ branches</option>
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); reset(); }} aria-label="Status">
          <option value="open">To work on</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={noSite} onChange={(e) => { setNoSite(e.target.checked); reset(); }} /> No website</label>
        <label className="check"><input type="checkbox" checked={strong} onChange={(e) => { setStrong(e.target.checked); reset(); }} /> Confirmed same business only</label>
      </div>
      <ErrorBox error={list.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {list.data?.items.length === 0 && <Empty>Nothing here yet. Click <strong>Find again</strong> (needs the business directory downloaded).</Empty>}
      <div className="bp-list">
        {list.data?.items.map((c) => (
          <article key={c.id} className={`bp-card ${open === c.id ? "open" : ""}`}>
            <button className="bp-head" onClick={() => setOpen(open === c.id ? null : c.id)}>
              <span className={`bp-score ${c.score >= 75 ? "hot" : c.score >= 55 ? "warm" : ""}`}>{Math.round(c.score)}</span>
              <span className="bp-main">
                <strong>{c.name} <span className="badge info">{c.branch_count} branches</span></strong>
                <span className="row gap-s small muted" style={{ marginTop: 4 }}>
                  <span className="badge">{c.type_label}</span>
                  {c.main_state && <span className="badge good">📍 {c.main_state}</span>}
                  {!c.has_website && <span className="badge warn">No website</span>}
                  {c.evidence === "shared_contact" && <span className="badge good">✓ same business</span>}
                  {c.status !== "new" && <span className="badge">{STATUS[c.status] ?? c.status}</span>}
                  <span>{c.cities.slice(0, 4).join(", ")}{c.cities.length > 4 ? ` +${c.cities.length - 4}` : ""}</span>
                </span>
              </span>
              <span aria-hidden className="muted">{open === c.id ? "▾" : "▸"}</span>
            </button>
            {open === c.id && <Detail c={c} onChange={(nc) => list.setData((d) => d && { ...d, items: d.items.map((x) => (x.id === nc.id ? nc : x)) })} />}
          </article>
        ))}
      </div>
      {list.data && <Pager total={list.data.total} limit={list.data.limit} offset={list.data.offset} onChange={setOffset} />}
    </>
  );
}
