import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorBox, ExtLink, Loading, Msg, Pager, fmtDate, useAction, useApi } from "../components/ui";

// Chennai-only lead intelligence: wholesale distributors and equipment sales & service companies.
// Every claim links to its source. Nothing is sent from here: approval only records the owner's decision.

interface Signal {
  id: number; lead_id: number | null; signal_type: string; strength: string; title: string | null; excerpt: string; url: string;
  source_name: string | null; published_at: string | null; detected_by: string; review_status: string; reviewed_by: string | null;
}
interface Route { value: string; source_url: string; official: boolean }
interface Op { key: string; label: string; excerpt: string; url?: string }
interface Lead {
  id: number; name: string; industry: string | null; industry_strength: string; industry_subtype: string | null; industry_reasons: string[];
  directory_category: string | null; address: string | null; locality: string | null; pincode: string | null;
  location_status: string; location_verified: boolean; location_basis: string | null; location_evidence_url: string | null;
  website: string | null; phones: Route[]; emails: Route[]; activity_status: string; activity_evidence: string | null;
  operations: Op[]; eligibility_blocker: string | null; source: string; source_url: string;
  category: "A" | "B" | "C" | "D"; category_reasons: string[]; sales_difficulty: string; difficulty_reasons: string[];
  evidence_confidence: string; potential_problem: string | null; suggested_solution: string | null; next_action: string | null;
  status: string; outreach_approved_by: string | null; outreach_approved_at: string | null; notes: string | null;
  website_checked_at: string | null; website_check_error: string | null; last_verified_at: string | null; signals: Signal[];
}
interface Page { items: Lead[]; total: number; limit: number; offset: number }
interface Run { id: number; areas: string[]; status: string; log: string[]; started_at: string; finished_at: string | null }
interface Summary {
  scope: string; chennai_only: boolean; total: number; by_category: Record<string, number>; by_industry: Record<string, number>;
  by_difficulty: Record<string, number>; verified_location: number; official_contact: number; websites_checked: number;
  websites_pending: number; recent_signals: number; signals_to_review: number; market_news: number; ready_for_review: number;
  approved: number; contacted: number; source_file: string | null; runs: Run[];
}
interface Brief {
  research_brief: { fact: string; source: string | null }[]; why_inferago: string[]; recommended_solution: string | null;
  services: string[]; outreach_draft: string; draft_is_edited: boolean; qualification_questions: string[]; notice: string;
}

const CAT: Record<string, { label: string; cls: string }> = {
  A: { label: "A · High contract potential", cls: "good" }, B: { label: "B · Promising", cls: "info" },
  C: { label: "C · Watchlist", cls: "warn" }, D: { label: "D · Rejected", cls: "bad" },
};
const IND: Record<string, string> = { wholesale_distribution: "Wholesale distributor", equipment_sales_service: "Equipment sales & service" };
const DIFF: Record<string, string> = { easier: "Easier to approach", moderate: "Moderate", difficult: "Difficult", unknown: "Unknown" };
const SIG: Record<string, string> = {
  explicit_software_request: "Asked for software / automation", vendor_request: "Looking for tech vendor / partner",
  operational_problem: "Operational problem", integration_need: "System needs integration", new_facility: "New service centre / warehouse / branch",
  expansion: "Expansion", modernisation: "Modernisation initiative",
};
const LOC: Record<string, string> = { chennai_city: "Chennai city", gcma_outside: "Outside city (metro area)", outside: "Outside Chennai", unknown: "Location unclear" };

type View = "ready" | "A" | "B" | "C" | "D" | "signals" | "all";
const VIEWS: { id: View; label: string }[] = [
  { id: "ready", label: "Ready for review" }, { id: "A", label: "A · High potential" }, { id: "B", label: "B · Promising" },
  { id: "C", label: "C · Watchlist" }, { id: "signals", label: "Recent signals" }, { id: "D", label: "Rejected" }, { id: "all", label: "All active" },
];

function Src({ href, children }: { href: string | null | undefined; children?: React.ReactNode }) {
  return href ? <ExtLink href={href}>{children ?? "source"}</ExtLink> : <span className="muted">no source</span>;
}

function SignalRow({ s, onDone }: { s: Signal; onDone: () => void }) {
  const act = useAction();
  const review = async (decision: string) => { if (await act.run(() => api.post(`/lead-signals/${s.id}/review`, { decision }))) onDone(); };
  return (
    <li>
      <span className={`badge ${s.review_status === "confirmed" ? "good" : s.review_status === "rejected" ? "bad" : "warn"}`}>
        {s.review_status === "hypothesis" ? "unconfirmed" : s.review_status}</span>{" "}
      <strong>{SIG[s.signal_type] ?? s.signal_type}</strong> · {s.published_at ? fmtDate(s.published_at) : <em>date unknown</em>} ·{" "}
      <ExtLink href={s.url}>{s.source_name ?? "source"}</ExtLink>
      <div className="excerpt small">“{s.excerpt}”</div>
      {s.review_status === "hypothesis" && (
        <span className="row gap-s">
          <button className="btn sm good" disabled={act.busy} onClick={() => review("confirmed")}>Confirm (I read the source)</button>
          <button className="btn sm danger" disabled={act.busy} onClick={() => review("rejected")}>Reject</button>
        </span>
      )}
      <Msg msg={act.msg} />
    </li>
  );
}

function AddSignal({ lead, onDone }: { lead: Lead; onDone: () => void }) {
  const act = useAction();
  const [f, setF] = useState({ signal_type: "explicit_software_request", url: "", excerpt: "", published_at: "" });
  const save = async () => {
    const body = { ...f, published_at: f.published_at ? `${f.published_at}T00:00:00` : null };
    if (await act.run(() => api.post(`/leads/${lead.id}/signals`, body), "Signal added")) { setF({ ...f, url: "", excerpt: "", published_at: "" }); onDone(); }
  };
  return (
    <details className="small">
      <summary className="muted">+ Add a signal you found (link and date required for it to count)</summary>
      <div className="stack-s pad-t">
        <select value={f.signal_type} onChange={(e) => setF({ ...f, signal_type: e.target.value })}>
          {Object.entries(SIG).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input placeholder="Source URL (https://…)" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
        <input type="date" value={f.published_at} onChange={(e) => setF({ ...f, published_at: e.target.value })} aria-label="Published date" />
        <textarea rows={2} placeholder="Exact quote from the source" value={f.excerpt} onChange={(e) => setF({ ...f, excerpt: e.target.value })} />
        <button className="btn sm primary" disabled={act.busy || !f.url || f.excerpt.length < 10} onClick={save}>Save signal</button>
        <Msg msg={act.msg} />
      </div>
    </details>
  );
}

function Outreach({ lead, onChange }: { lead: Lead; onChange: (l: Lead) => void }) {
  const brief = useApi(() => api.get<Brief>(`/leads/${lead.id}/brief`), [lead.id, lead.status, lead.signals.length]);
  const act = useAction();
  const [draft, setDraft] = useState<string | null>(null);
  const b = brief.data;
  if (!b) return brief.error ? <ErrorBox error={brief.error} /> : <Loading />;
  const text = draft ?? b.outreach_draft;
  const saveDraft = async () => { const r = await act.run(() => api.patch<Lead>(`/leads/${lead.id}`, { outreach_draft: text }), "Draft saved (approval reset)"); if (r) { onChange(r); setDraft(null); brief.reload(); } };
  const approve = async () => { const r = await act.run(() => api.post<Lead>(`/leads/${lead.id}/approve-outreach`), "Approved. Contact them yourself, then mark contacted."); if (r) onChange(r); };
  const contacted = async () => { const r = await act.run(() => api.post<Lead>(`/leads/${lead.id}/mark-contacted`), "Marked contacted"); if (r) onChange(r); };
  return (
    <div className="stack-s">
      <h4>Research brief</h4>
      <ul className="list-plain small">{b.research_brief.map((f, i) => <li key={i}>{f.fact} {f.source && <>· <Src href={f.source} /></>}</li>)}</ul>
      <h4>Why they may need Inferago</h4>
      <ul className="small">{b.why_inferago.map((w) => <li key={w}>{w}</li>)}</ul>
      {b.recommended_solution && <p className="small"><strong>Suggested solution:</strong> {b.recommended_solution} <span className="muted">({b.services.join(", ")})</span></p>}
      <h4>Qualification questions</h4>
      <ol className="small">{b.qualification_questions.map((q) => <li key={q}>{q}</li>)}</ol>
      <h4>Outreach draft {lead.outreach_approved_by && <span className="badge good">approved by {lead.outreach_approved_by}</span>}</h4>
      <textarea rows={9} value={text} onChange={(e) => setDraft(e.target.value)} />
      <div className="row gap-s" style={{ flexWrap: "wrap" }}>
        {draft !== null && <button className="btn sm" disabled={act.busy} onClick={saveDraft}>Save edits</button>}
        {(lead.category === "A" || lead.category === "B") && lead.status !== "approved" && lead.status !== "contacted" && draft === null &&
          <button className="btn sm good" disabled={act.busy} onClick={approve}>Approve outreach</button>}
        {lead.status === "approved" && <button className="btn sm" disabled={act.busy} onClick={contacted}>I contacted them</button>}
        <button className="btn sm" onClick={() => navigator.clipboard?.writeText(text)}>Copy</button>
      </div>
      <p className="xs muted">{b.notice}</p>
      <Msg msg={act.msg} />
    </div>
  );
}

function Detail({ lead, onChange }: { lead: Lead; onChange: (l: Lead) => void }) {
  const act = useAction();
  const [tab, setTab] = useState<"why" | "outreach">("why");
  const [note, setNote] = useState(lead.notes ?? "");
  const reload = async () => { const r = await api.get<Lead>(`/leads/${lead.id}`); onChange(r); };
  const verify = async () => { const r = await act.run(() => api.post<Lead>(`/leads/${lead.id}/verify-website`), "Website checked"); if (r) onChange(r); };
  const patch = async (body: Record<string, unknown>, ok: string) => { const r = await act.run(() => api.patch<Lead>(`/leads/${lead.id}`, body), ok); if (r) onChange(r); };
  const routes = [...lead.phones.map((p) => ({ ...p, kind: "📞" })), ...lead.emails.map((e) => ({ ...e, kind: "✉️" }))];
  return (
    <div className="bp-detail">
      <div className="row gap-s" style={{ flexWrap: "wrap" }}>
        <button className={`btn sm ${tab === "why" ? "primary" : ""}`} onClick={() => setTab("why")}>Why selected · evidence</button>
        <button className={`btn sm ${tab === "outreach" ? "primary" : ""}`} onClick={() => setTab("outreach")}>Brief & outreach draft</button>
      </div>
      {tab === "why" ? (
        <div className="stack-s">
          <p className="small"><strong>{CAT[lead.category].label}:</strong></p>
          <ul className="small">{lead.category_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          <p className="small"><strong>Next action:</strong> {lead.next_action}</p>
          <p className="small"><strong>Location:</strong> {LOC[lead.location_status]} {lead.location_verified ? <span className="badge good">verified</span> : <span className="badge warn">not verified</span>}
            {" "}— {lead.location_basis} <Src href={lead.location_evidence_url ?? lead.source_url} /></p>
          <p className="small"><strong>Industry:</strong> {lead.industry ? IND[lead.industry] : "none"} ({lead.industry_strength}) — {lead.industry_reasons.join("; ")}</p>
          <p className="small"><strong>Activity:</strong> {lead.activity_status.replace("_", " ")} — {lead.activity_evidence ?? "unknown"}</p>
          {lead.operations.length > 0 && (
            <details className="small" open><summary className="muted">Operations seen on their website ({lead.operations.length})</summary>
              <ul className="list-plain">{lead.operations.map((o) => <li key={o.key}><strong>{o.label}</strong>: “{o.excerpt.slice(0, 160)}” <Src href={o.url} /></li>)}</ul>
            </details>
          )}
          <p className="small"><strong>Buying signals</strong> <span className="muted">(expansion or hiring is not software demand; only confirmed, dated, recent requests or problems qualify for A)</span></p>
          {lead.signals.length === 0 ? <p className="small muted">None recorded.</p> :
            <ul className="list-plain small">{lead.signals.map((s) => <SignalRow key={s.id} s={s} onDone={reload} />)}</ul>}
          <AddSignal lead={lead} onDone={reload} />
          <p className="small"><strong>Contact routes:</strong>{" "}
            {routes.length === 0 ? <span className="muted">none published</span> : routes.map((r) => (
              <span key={r.value} className="chip static">{r.kind} {r.value} · {r.official ? "official site" : "directory"} · <Src href={r.source_url} /></span>
            ))}
          </p>
          <p className="small"><strong>Sales difficulty (estimate):</strong> {DIFF[lead.sales_difficulty]} — {lead.difficulty_reasons.join("; ")}</p>
          {lead.potential_problem && <p className="small"><strong>Possible problem (to check, not confirmed):</strong> {lead.potential_problem}</p>}
          <p className="xs muted">Evidence confidence: {lead.evidence_confidence} · Website checked: {lead.website_checked_at ? fmtDate(lead.website_checked_at) : "not yet"}
            {lead.website_check_error && ` (${lead.website_check_error})`} · Last verified: {lead.last_verified_at ? fmtDate(lead.last_verified_at) : "never"} · Found via <Src href={lead.source_url}>{lead.source}</Src></p>
          <div className="row gap-s" style={{ flexWrap: "wrap" }}>
            {lead.website && <button className="btn sm" disabled={act.busy} onClick={verify}>🔎 Verify website</button>}
            {lead.website && <a className="btn sm" href={lead.website} target="_blank" rel="noopener noreferrer">Open website</a>}
            {lead.status !== "rejected" ? <button className="btn sm danger" disabled={act.busy} onClick={() => patch({ status: "rejected" }, "Rejected")}>Reject</button>
              : <button className="btn sm" disabled={act.busy} onClick={() => patch({ status: "new" }, "Restored")}>Restore</button>}
            <button className="btn sm" disabled={act.busy} onClick={() => patch({ status: "duplicate" }, "Marked duplicate")}>Duplicate</button>
          </div>
          <textarea rows={2} placeholder="Notes" value={note} onChange={(e) => setNote(e.target.value)} />
          {note !== (lead.notes ?? "") && <button className="btn sm" disabled={act.busy} onClick={() => patch({ notes: note }, "Saved")}>Save note</button>}
          <Msg msg={act.msg} />
        </div>
      ) : <Outreach lead={lead} onChange={onChange} />}
    </div>
  );
}

function AddLead({ onDone }: { onDone: () => void }) {
  const act = useAction();
  const empty = { name: "", industry: "", address: "", website: "", phone: "", email: "", source_url: "", location_evidence_url: "" };
  const [f, setF] = useState(empty);
  const save = async () => {
    const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v || null]));
    if (await act.run(() => api.post("/leads", body), "Lead added")) { setF(empty); onDone(); }
  };
  const field = (k: keyof typeof empty, ph: string) => <input placeholder={ph} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />;
  return (
    <details className="card pad">
      <summary><strong>+ Add a company you found</strong> <span className="muted small">(exhibitor list, association directory, a post you read)</span></summary>
      <div className="grid-2 pad-t">
        {field("name", "Company name *")}
        <select value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })}>
          <option value="">Industry: detect from name</option>
          {Object.entries(IND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        {field("address", "Address (with locality and PIN)")}
        {field("website", "Official website")}
        {field("phone", "Public business phone")}
        {field("email", "Public business email")}
        {field("source_url", "Where you found it (URL) *")}
        {field("location_evidence_url", "Official page showing the Chennai address (optional)")}
      </div>
      <button className="btn sm primary" disabled={act.busy || !f.name || !f.source_url} onClick={save}>Add lead</button>
      <Msg msg={act.msg} />
    </details>
  );
}

function MarketNews() {
  const list = useApi(() => api.get<Signal[]>("/lead-signals", { unmatched: true }));
  if (!list.data?.length) return null;
  return (
    <details className="card pad small">
      <summary><strong>Chennai market news not matched to a company ({list.data.length})</strong> <span className="muted">— if one names a company, add it as a lead</span></summary>
      <ul className="list-plain">{list.data.map((s) => (
        <li key={s.id}>{s.published_at ? fmtDate(s.published_at) : "date unknown"} · <ExtLink href={s.url}>{s.title ?? s.url}</ExtLink> · {SIG[s.signal_type]}</li>
      ))}</ul>
    </details>
  );
}

export default function Leads() {
  const [view, setView] = useState<View>("ready");
  const [industry, setIndustry] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [confidence, setConfidence] = useState("");
  const [days, setDays] = useState("");
  const [verified, setVerified] = useState(false);
  const [officialContact, setOfficialContact] = useState(false);
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const summary = useApi(() => api.get<Summary>("/leads/summary"));
  const query = {
    q, industry, difficulty, confidence, offset, limit: 25,
    category: ["A", "B", "C", "D"].includes(view) ? view : undefined,
    ready: view === "ready" ? true : undefined,
    signal_days: view === "signals" ? (days || 90) : days || undefined,
    verified: verified ? true : undefined, official_contact: officialContact ? true : undefined,
  };
  const list = useApi(() => api.get<Page>("/leads", query), [JSON.stringify(query)]);
  const act = useAction();
  const s = summary.data;
  const reset = () => setOffset(0);
  const start = async (path: string, body: unknown, ok: string) => {
    const r = await act.run(() => api.post(path, body), ok);
    if (r) setTimeout(() => { summary.reload(); list.reload(); }, 8000);
  };
  const replace = (l: Lead) => list.setData(list.data && { ...list.data, items: list.data.items.map((x) => (x.id === l.id ? l : x)) });
  const running = s?.runs.find((r) => r.status === "running" || r.status === "stopping");
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Chennai leads</h1>
          <p className="muted">Wholesale distributors and equipment sales & service companies in <strong>Chennai city only</strong>.
            A few credible prospects with a reason to buy, not thousands of names. Nothing is sent automatically.</p>
        </div>
      </header>
      {s && !s.chennai_only && <div className="alert warn">Nationwide discovery is switched ON (IOI_DISCOVERY_SCOPE=all).</div>}
      <Msg msg={act.msg} />
      {s && (
        <div className="stat-row">
          <div className="stat hot"><span className="stat-num">{s.by_category.A}</span><span>A · high contract potential</span></div>
          <div className="stat"><span className="stat-num">{s.by_category.B}</span><span>B · promising</span></div>
          <div className="stat"><span className="stat-num">{s.by_category.C}</span><span>C · watchlist</span></div>
          <div className="stat"><span className="stat-num">{s.by_category.D}</span><span>rejected</span></div>
          <div className="stat"><span className="stat-num">{s.recent_signals}</span><span>signals (90 days)</span></div>
          <div className="stat"><span className="stat-num">{s.official_contact}</span><span>verified contact routes</span></div>
          <div className="stat"><span className="stat-num">{s.ready_for_review}</span><span>ready for review</span></div>
        </div>
      )}
      {s && (
        <div className="card pad small">
          <strong>Pipeline</strong> <span className="muted">(run in order; each step is cheap and only the best go to the next)</span>
          <div className="row gap-s pad-t" style={{ flexWrap: "wrap" }}>
            <button className="btn sm" disabled={act.busy || !!running || !s.source_file} title={s.source_file ?? "No Overture file"}
              onClick={() => start("/leads/collect", { max_keep: 2000 }, "Collecting from the local directory file (about a minute)…")}>1 · Collect Chennai candidates</button>
            <button className="btn sm" disabled={act.busy || !!running || s.websites_pending === 0}
              onClick={() => start("/leads/research", { limit: 25 }, "Checking the top 25 official websites (a few minutes)…")}>2 · Verify top 25 websites ({s.websites_pending} left)</button>
            <button className="btn sm" disabled={act.busy || !!running} onClick={() => start("/leads/news", {}, "Reading Chennai business news…")}>3 · Scan news for signals</button>
            {running && <button className="btn sm danger" onClick={() => start(`/leads/runs/${running.id}/stop`, {}, "Stopping…")}>Stop</button>}
            <button className="btn sm" onClick={() => { summary.reload(); list.reload(); }}>↻ Refresh</button>
          </div>
          {s.runs[0] && <p className="xs muted pad-t">Last run #{s.runs[0].id} ({s.runs[0].status}): {s.runs[0].log.slice(-1)[0] ?? "started"}</p>}
          {s.signals_to_review > 0 && <p className="small">⚠️ {s.signals_to_review} detected signal(s) need your review — open the lead, read the source, then confirm or reject.</p>}
        </div>
      )}
      <AddLead onDone={() => { summary.reload(); list.reload(); }} />
      <MarketNews />
      <div className="tabs">
        {VIEWS.map((v) => <button key={v.id} className={`tab ${view === v.id ? "active" : ""}`} onClick={() => { setView(v.id); reset(); }}>{v.label}</button>)}
      </div>
      <div className="filters">
        <input placeholder="Search name or locality…" value={q} onChange={(e) => { setQ(e.target.value); reset(); }} />
        <select value={industry} onChange={(e) => { setIndustry(e.target.value); reset(); }} aria-label="Industry">
          <option value="">Both industries</option>{Object.entries(IND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={difficulty} onChange={(e) => { setDifficulty(e.target.value); reset(); }} aria-label="Sales difficulty">
          <option value="">Any difficulty</option>{Object.entries(DIFF).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={confidence} onChange={(e) => { setConfidence(e.target.value); reset(); }} aria-label="Evidence">
          <option value="">Any evidence</option><option value="high">High evidence</option><option value="medium">Medium evidence</option><option value="low">Low evidence</option>
        </select>
        <select value={days} onChange={(e) => { setDays(e.target.value); reset(); }} aria-label="Signal recency">
          <option value="">Any recency</option><option value="30">Signal ≤ 30 days</option><option value="90">Signal ≤ 90 days</option><option value="180">Signal ≤ 180 days</option>
        </select>
        <label className="check"><input type="checkbox" checked={verified} onChange={(e) => { setVerified(e.target.checked); reset(); }} /> Verified location</label>
        <label className="check"><input type="checkbox" checked={officialContact} onChange={(e) => { setOfficialContact(e.target.checked); reset(); }} /> Official contact</label>
      </div>
      <ErrorBox error={list.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {list.data?.items.length === 0 && <Empty>{view === "ready" ? "No A/B leads with a contact route yet. Run the pipeline steps above, then review signals." : "Nothing here."}</Empty>}
      <div className="bp-list">
        {list.data?.items.map((l) => (
          <article key={l.id} className={`bp-card ${open === l.id ? "open" : ""}`}>
            <button className="bp-head" onClick={() => setOpen(open === l.id ? null : l.id)}>
              <span className={`bp-score ${l.category === "A" ? "hot" : l.category === "B" ? "warm" : ""}`}>{l.category}</span>
              <span className="bp-main">
                <strong>{l.name}</strong>
                <span className="row gap-s small muted" style={{ marginTop: 4, flexWrap: "wrap" }}>
                  <span className={`badge ${CAT[l.category].cls}`}>{CAT[l.category].label}</span>
                  {l.industry && <span className="badge">{IND[l.industry]}{l.industry_subtype && l.industry_subtype !== "other" ? ` · ${l.industry_subtype}` : ""}</span>}
                  <span className={`badge ${l.location_verified ? "good" : "warn"}`}>{l.locality ?? LOC[l.location_status]}{l.location_verified ? " ✓" : ""}</span>
                  <span className="badge">{DIFF[l.sales_difficulty]}</span>
                  {l.signals.filter((x) => x.review_status !== "rejected").length > 0 && <span className="badge info">{l.signals.filter((x) => x.review_status !== "rejected").length} signal(s)</span>}
                  {l.status !== "new" && <span className="badge">{l.status}</span>}
                </span>
                <span className="small clamp-2" style={{ marginTop: 4 }}>{l.category_reasons[l.category_reasons.length - 1]}</span>
              </span>
            </button>
            {open === l.id && <Detail lead={l} onChange={replace} />}
          </article>
        ))}
      </div>
      {list.data && <Pager total={list.data.total} limit={list.data.limit} offset={list.data.offset} onChange={setOffset} />}
    </>
  );
}
