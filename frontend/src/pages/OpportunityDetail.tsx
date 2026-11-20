import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import {
  Card, DemoBadge, Empty, EligibilityBadge, ErrorBox, ExtLink, Geo, Loading, Msg, PageHeader, PipelineBadge,
  ScoreBreakdown, StatusBadge, Tabs, fmtDate, useAction, useApi,
} from "../components/ui";
import type { Assessment, Contact, Draft, Evidence, Opportunity, OrgRelationship, Page, Requirement, ResearchTask } from "../types";
import { STATUSES } from "./Opportunities";

type Tab = "overview" | "claude" | "evidence" | "eligibility" | "scores" | "research" | "contacts" | "chains" | "outreach";

const REQ_KEYS = [
  "country_restriction", "india_providers_accepted", "legal_entity", "proprietorship_acceptance", "gst", "pan", "udyam_msme",
  "min_turnover", "prior_experience", "similar_work_certificates", "workforce", "technical_certifications", "security_certifications",
  "insurance", "emd", "digital_signature", "registration_fee", "tax_invoicing", "subcontracting_permission", "consortium_permission",
  "vendor_registration", "project_restriction",
];

export default function OpportunityDetail() {
  const { id } = useParams();
  const oid = Number(id);
  const [tab, setTab] = useState<Tab>("overview");
  const opp = useApi(() => api.get<Opportunity>(`/opportunities/${oid}`), [oid]);
  const act = useAction();
  const o = opp.data;

  const setStatus = async (status: string) => {
    if (await act.run(() => api.patch(`/opportunities/${oid}`, { status }), `Status set to ${status}`)) opp.reload();
  };

  return (
    <>
      <ErrorBox error={opp.error} onRetry={opp.reload} />
      {opp.loading && !o && <Loading />}
      {o && (
        <>
          <PageHeader
            title={o.title}
            subtitle={
              <span className="row gap-s">
                <PipelineBadge pipeline={o.pipeline} />
                <EligibilityBadge outcome={o.eligibility_outcome} />
                <StatusBadge status={o.status} />
                <DemoBadge show={o.is_demo} />
                {o.merged_into_id && <Link to={`/opportunities/${o.merged_into_id}`}>Merged into #{o.merged_into_id}</Link>}
                <span className="muted">Priority {o.priority ?? "—"}</span>
              </span>
            }
            actions={
              <>
                <select value={o.status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
                  {STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
                </select>
                <button className="btn" onClick={async () => { if (await act.run(() => api.post(`/opportunities/${oid}/reclassify`), "Reclassified")) opp.reload(); }}>Reclassify</button>
                <button className="btn" onClick={async () => { if (await act.run(() => api.post(`/opportunities/${oid}/evaluate`), "Eligibility & scores recomputed")) opp.reload(); }}>Re-evaluate</button>
              </>
            }
          />
          <Msg msg={act.msg} />
          {o.needs_manual_review && <div className="alert warn">Flagged for manual review (e.g. scanned document — text could not be reliably extracted).</div>}
          <Tabs<Tab>
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "overview", label: "Overview" }, { id: "claude", label: "AI review" }, { id: "evidence", label: "Evidence" }, { id: "eligibility", label: "Eligibility" },
              { id: "scores", label: "Scores" }, { id: "research", label: "Research" }, { id: "contacts", label: "Contacts" },
              { id: "chains", label: "Relationships" }, { id: "outreach", label: "Outreach" },
            ]}
          />
          {tab === "overview" && <OverviewTab o={o} />}
          {tab === "claude" && <ClaudeTab oid={oid} onChange={opp.reload} />}
          {tab === "evidence" && <EvidenceTab oid={oid} />}
          {tab === "eligibility" && <EligibilityTab oid={oid} onChange={opp.reload} />}
          {tab === "scores" && (
            <div className="grid grid-3">
              {o.scores.map((s) => <ScoreBreakdown key={s.score_type} score={s} />)}
            </div>
          )}
          {tab === "research" && <ResearchTab oid={oid} onChange={opp.reload} />}
          {tab === "contacts" && <ContactsTab o={o} onChange={opp.reload} />}
          {tab === "chains" && <RelationshipsTab o={o} />}
          {tab === "outreach" && <OutreachTab o={o} />}
        </>
      )}
    </>
  );
}

function OverviewTab({ o }: { o: Opportunity }) {
  return (
    <div className="grid grid-2">
      <Card title="Details">
        <dl className="kv">
          <dt>Organisation</dt><dd>{o.organisation_id ? <Link to={`/organisations/${o.organisation_id}`}>{o.organisation_name}</Link> : <span className="muted">Not identified</span>}</dd>
          <dt>Category</dt><dd>{o.category.replace(/_/g, " ")} <span className="muted small">({Math.round(o.classification_confidence * 100)}% · {o.classification_method})</span></dd>
          <dt>Services matched</dt><dd>{o.services_matched.join(", ") || <span className="muted">none</span>}</dd>
          <dt>Signals</dt><dd>{o.signals_matched.join(", ") || <span className="muted">none</span>}</dd>
          <dt>Geography</dt><dd><Geo country={o.country} region={o.region} />{o.geography_basis && <div className="muted xs">{o.geography_basis}</div>}</dd>
          <dt>Remote</dt><dd>{o.remote_ok === null ? <span className="muted">unknown</span> : o.remote_ok ? "yes" : "no"}</dd>
          <dt>Budget</dt><dd>{o.budget_text ?? <span className="muted">not stated</span>}</dd>
          <dt>Deadline</dt><dd>{fmtDate(o.deadline)}</dd>
          <dt>Published</dt><dd>{fmtDate(o.published_at, true)}</dd>
          <dt>Retrieved</dt><dd>{fmtDate(o.retrieved_at, true)}</dd>
          <dt>Source</dt><dd>{o.source_key} · <ExtLink href={o.canonical_url}>original</ExtLink></dd>
        </dl>
      </Card>
      <Card title="Why it was classified this way">
        <ul>{o.classification_evidence.map((e, i) => <li key={i} className="small wrap">{e}</li>)}</ul>
        <h3>Original text</h3>
        <div className="excerpt">{o.description ?? o.summary}</div>
      </Card>
    </div>
  );
}

function EvidenceTab({ oid }: { oid: number }) {
  const ev = useApi(() => api.get<Evidence[]>(`/opportunities/${oid}/evidence`), [oid]);
  return (
    <Card title="Preserved evidence (provenance)">
      <ErrorBox error={ev.error} />
      {ev.data?.length === 0 && <Empty>No evidence</Empty>}
      {ev.data?.map((e) => (
        <div key={e.id} className="stack" style={{ marginBottom: 16 }}>
          <div className="row gap-s small">
            <span className="badge neutral">{e.evidence_type}</span>
            <ExtLink href={e.url}>{e.url ?? e.document_name}</ExtLink>
            {e.document_name && <span className="muted">{e.document_name}</span>}
            {e.page_reference && <span className="badge info">{e.page_reference}</span>}
            <span className="muted">published {fmtDate(e.published_at)} · retrieved {fmtDate(e.retrieved_at, true)}</span>
          </div>
          <div className="excerpt">{e.excerpt}</div>
        </div>
      ))}
    </Card>
  );
}

function EligibilityTab({ oid, onChange }: { oid: number; onChange: () => void }) {
  const el = useApi(() => api.get<Record<string, Assessment | null>>(`/opportunities/${oid}/eligibility`), [oid]);
  const reqs = useApi(() => api.get<Requirement[]>(`/opportunities/${oid}/requirements`), [oid]);
  const act = useAction();
  const [form, setForm] = useState({ requirement_key: "gst", scope: "project", mandatory: true, text: "", params: "{}" });
  const reload = () => { el.reload(); reqs.reload(); onChange(); };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    let parameters = {};
    try { parameters = JSON.parse(form.params || "{}"); } catch { act.setMsg({ kind: "err", text: "Parameters must be JSON" }); return; }
    if (await act.run(() => api.post(`/opportunities/${oid}/requirements`, { requirement_key: form.requirement_key, scope: form.scope, mandatory: form.mandatory, text: form.text, parameters }), "Requirement added; eligibility re-assessed")) {
      setForm({ ...form, text: "", params: "{}" });
      reload();
    }
  };
  return (
    <>
      <div className="alert info small">Deterministic engine. Unknown requirements are never treated as satisfied. Decision support only — not legal or tax advice.</div>
      <div className="grid grid-2">
        {(["project", "vendor_registration"] as const).map((scope) => {
          const a = el.data?.[scope];
          return (
            <Card key={scope} title={scope === "project" ? "Project eligibility" : "Vendor registration eligibility"} actions={a && <EligibilityBadge outcome={a.outcome} />}>
              {!a ? <Empty>Not assessed</Empty> : (
                <div className="stack small">
                  <div className="wrap">{a.reason}</div>
                  <div><strong>Next action:</strong> {a.next_action}</div>
                  {a.mandatory_failures.length > 0 && <ReqList title="Mandatory failures" items={a.mandatory_failures} tone="bad" />}
                  {a.satisfied.length > 0 && <ReqList title="Satisfied" items={a.satisfied} tone="good" />}
                  {a.missing.length > 0 && <ReqList title="Missing / needs clarification" items={a.missing} tone="warn" />}
                  {a.clarifications.length > 0 && (
                    <div><strong>Questions to clarify</strong><ul>{a.clarifications.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
                  )}
                  <div className="muted xs">Assessed {fmtDate(a.created_at, true)}</div>
                </div>
              )}
            </Card>
          );
        })}
      </div>
      <Card title="Requirements">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Key</th><th>Scope</th><th>Mandatory</th><th>Text</th><th>Page</th><th>Origin</th><th /></tr></thead>
            <tbody>
              {reqs.data?.map((r) => (
                <tr key={r.id}>
                  <td className="small">{r.requirement_key}</td>
                  <td className="small">{r.scope}</td>
                  <td>{r.mandatory ? "yes" : "no"}</td>
                  <td className="small wrap">{r.text}{Object.keys(r.parameters).length > 0 && <div className="muted mono xs">{JSON.stringify(r.parameters)}</div>}</td>
                  <td className="mono">{r.page_reference ?? ""}</td>
                  <td className="small">{r.origin}</td>
                  <td><button className="btn sm danger" onClick={async () => { if (await act.run(() => api.del(`/opportunities/${oid}/requirements/${r.id}`), "Removed")) reload(); }}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3>Add requirement manually</h3>
        <form className="filters" onSubmit={add}>
          <label className="field">Type<select value={form.requirement_key} onChange={(e) => setForm({ ...form, requirement_key: e.target.value })}>{REQ_KEYS.map((k) => <option key={k}>{k}</option>)}</select></label>
          <label className="field">Scope<select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}><option value="project">project</option><option value="vendor_registration">vendor registration</option></select></label>
          <label className="field">Mandatory<select value={String(form.mandatory)} onChange={(e) => setForm({ ...form, mandatory: e.target.value === "true" })}><option value="true">yes</option><option value="false">no</option></select></label>
          <label className="field" style={{ flex: 1, minWidth: 220 }}>Requirement text<input required value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} /></label>
          <label className="field">Parameters (JSON)<input className="mono" value={form.params} onChange={(e) => setForm({ ...form, params: e.target.value })} placeholder='{"allowed_countries":["India"]}' /></label>
          <button className="btn" disabled={act.busy}>Add</button>
        </form>
        <Msg msg={act.msg} />
      </Card>
    </>
  );
}

function ReqList({ title, items, tone }: { title: string; items: { key: string; reason: string; page_reference: string | null; mandatory: boolean }[]; tone: string }) {
  return (
    <div>
      <strong>{title}</strong>
      <ul>
        {items.map((r, i) => (
          <li key={i}><span className={`badge ${tone} xs`}>{r.key}</span> {r.reason}{r.page_reference && <span className="muted"> ({r.page_reference})</span>}{!r.mandatory && <span className="muted"> · optional</span>}</li>
        ))}
      </ul>
    </div>
  );
}

interface AIReview {
  id: number; status: string; trigger: string; model: string | null; verdict: string | null; opportunity_open: string | null;
  rule_outcome: string | null; agrees_with_rules: boolean | null; summary: string | null; next_step: string | null;
  requirement_reviews: { requirement: string; mandatory: boolean; met: string; reason: string; source_quote: string | null; source_url: string | null; quote_verified: boolean }[];
  facts: { kind: string; value: string; quote: string; source: string }[];
  open_questions: string[]; sources: string[]; actions: string[]; turns: number; tokens: number; error: string | null; created_at: string;
}

function ClaudeTab({ oid, onChange }: { oid: number; onChange: () => void }) {
  const reviews = useApi(() => api.get<AIReview[]>(`/opportunities/${oid}/ai-reviews`), [oid]);
  const act = useAction();
  const start = async () => {
    if (await act.run(() => api.post(`/opportunities/${oid}/ai-review`, undefined, { wait: true }), "Review finished")) { reviews.reload(); onChange(); }
  };
  const r = reviews.data?.[0];
  return (
    <Card title="AI review — retrieve, verify, check eligibility" actions={<button className="btn primary" disabled={act.busy} onClick={start}>{act.busy ? "AI is reviewing… (1–3 min)" : r ? "Review again" : "Review with AI"}</button>}>
      <Msg msg={act.msg} />
      <div className="muted small">The AI agent reads the opportunity and the source pages (robots.txt respected), records only facts it can quote exactly, and gives an eligibility opinion. The rule engine stays authoritative for mandatory conditions; disagreements are flagged for you.</div>
      {!reviews.data ? <Loading /> : !r ? <Empty>Not reviewed yet</Empty> : (
        <div className="stack" style={{ marginTop: 14 }}>
          <div className="row gap-s small"><StatusBadge status={r.status} /><span className="muted">#{r.id} · {fmtDate(r.created_at, true)} · {r.model} · {r.turns} turns · {r.tokens.toLocaleString()} tokens · {r.trigger}</span></div>
          {r.error && <div className="alert err">{r.error}</div>}
          {r.verdict && (
            <dl className="kv">
              <dt>AI verdict</dt><dd><EligibilityBadge outcome={r.verdict} /></dd>
              <dt>Rule engine</dt><dd><EligibilityBadge outcome={r.rule_outcome} /> {r.agrees_with_rules === false && <span className="alert warn small">Disagreement — review manually (rules stay authoritative)</span>}{r.agrees_with_rules === true && <span className="muted small"> agrees</span>}</dd>
              <dt>Still open?</dt><dd>{r.opportunity_open}</dd>
              <dt>Summary</dt><dd className="wrap">{r.summary}</dd>
              <dt>Next step</dt><dd className="wrap">{r.next_step}</dd>
            </dl>
          )}
          {r.requirement_reviews.length > 0 && (
            <table>
              <thead><tr><th>Requirement</th><th>Met?</th><th>Reason</th><th>Source</th></tr></thead>
              <tbody>{r.requirement_reviews.map((q, i) => (
                <tr key={i}>
                  <td className="small">{q.requirement}{q.mandatory && <span className="muted xs"> · mandatory</span>}</td>
                  <td className="small">{q.met}</td>
                  <td className="wrap small">{q.reason}</td>
                  <td className="wrap xs">{q.source_quote ? <>“{q.source_quote}” <span className={q.quote_verified ? "muted" : "alert warn"}>{q.quote_verified ? "✓ verified" : "unverified quote"}</span></> : <span className="muted">—</span>}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
          {r.facts.length > 0 && (
            <div><strong className="small">Verified facts</strong>
              <ul className="small">{r.facts.map((f, i) => <li key={i}><b>{f.kind}</b>: {f.value} <span className="muted xs">— “{f.quote}” ({f.source.startsWith("http") ? <ExtLink href={f.source}>source</ExtLink> : f.source})</span></li>)}</ul>
            </div>
          )}
          {r.open_questions.length > 0 && <div><strong className="small">Questions for the buyer</strong><ul className="small">{r.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></div>}
          {(r.actions.length > 0 || r.sources.length > 0) && <div className="muted xs">Actions: {r.actions.join("; ") || "none"}</div>}
        </div>
      )}
    </Card>
  );
}

function ResearchTab({ oid, onChange }: { oid: number; onChange: () => void }) {
  const tasks = useApi(() => api.get<Page<ResearchTask>>("/research/tasks", { opportunity_id: oid }), [oid]);
  const act = useAction();
  const run = async (force: boolean) => {
    if (await act.run(() => api.post<ResearchTask>(`/opportunities/${oid}/research`, undefined, { force }), "Research finished")) { tasks.reload(); onChange(); }
  };
  return (
    <Card title="Research" actions={<span className="row gap-s"><button className="btn primary" disabled={act.busy} onClick={() => run(false)}>{act.busy ? "Researching…" : "Research now"}</button><button className="btn" disabled={act.busy} onClick={() => run(true)}>Force re-research</button></span>}>
      <Msg msg={act.msg} />
      <div className="muted small">Visits only the organisation's own public site (robots.txt respected) within the request budget. Records contact routes that are actually published.</div>
      {tasks.data?.items.length === 0 && <Empty>Not researched yet</Empty>}
      {tasks.data?.items.map((t) => (
        <div key={t.id} className="stack" style={{ marginTop: 14 }}>
          <div className="row gap-s small"><StatusBadge status={t.status} /><span className="muted">#{t.id} · {fmtDate(t.created_at, true)} · {t.requests_used}/{t.request_budget} requests · {t.ai_calls_used} AI calls</span></div>
          {t.error && <div className="alert err">{t.error}</div>}
          {t.brief && <pre>{t.brief}</pre>}
        </div>
      ))}
    </Card>
  );
}

function ContactsTab({ o, onChange }: { o: Opportunity; onChange: () => void }) {
  const contacts = useApi(() => api.get<Page<Contact>>("/contacts", { opportunity_id: o.id }), [o.id]);
  const orgContacts = useApi(() => (o.organisation_id ? api.get<Page<Contact>>("/contacts", { organisation_id: o.organisation_id }) : Promise.resolve(undefined)), [o.organisation_id]);
  const act = useAction();
  const [f, setF] = useState({ contact_type: "official_email", value: "", source_url: "", person_name: "", role: "", verified: false });
  const all = [...(contacts.data?.items ?? []), ...(orgContacts.data?.items ?? [])].filter((c, i, arr) => arr.findIndex((x) => x.id === c.id) === i);
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (await act.run(() => api.post("/contacts", { ...f, opportunity_id: o.id, organisation_id: o.organisation_id, person_name: f.person_name || null, role: f.role || null }), "Contact recorded")) {
      contacts.reload(); orgContacts.reload(); onChange();
    }
  };
  return (
    <Card title="Contact routes">
      <div className="muted small">Only publicly published business routes, each with the page it came from. Guessed addresses are never generated.</div>
      {all.length === 0 && <Empty>No contact routes found yet</Empty>}
      {all.length > 0 && (
        <div className="table-wrap pad-t">
          <table>
            <thead><tr><th>Type</th><th>Value</th><th>Verified</th><th>Source</th><th>Verified on</th></tr></thead>
            <tbody>
              {all.map((c) => (
                <tr key={c.id}>
                  <td className="small">{c.contact_type.replace(/_/g, " ")}</td>
                  <td className="wrap">{/^https?:/.test(c.value) ? <ExtLink href={c.value} /> : c.value}{c.person_name && <div className="muted xs">{c.person_name} {c.role && `· ${c.role}`}</div>}</td>
                  <td>{c.verified ? <span className="badge good">verified</span> : <span className="badge warn">unverified</span>}<div className="muted xs">{c.verification_method}</div></td>
                  <td className="small wrap"><ExtLink href={c.source_url} /></td>
                  <td className="small">{fmtDate(c.verification_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h3>Record a public contact route</h3>
      <form className="filters" onSubmit={add}>
        <label className="field">Type<select value={f.contact_type} onChange={(e) => setF({ ...f, contact_type: e.target.value })}>{["official_email", "contact_page", "published_phone", "vendor_onboarding_page", "decision_maker"].map((t) => <option key={t}>{t}</option>)}</select></label>
        <label className="field">Value<input required value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} /></label>
        <label className="field">Published at (URL)<input required type="url" value={f.source_url} onChange={(e) => setF({ ...f, source_url: e.target.value })} /></label>
        <label className="field">Name<input value={f.person_name} onChange={(e) => setF({ ...f, person_name: e.target.value })} /></label>
        <label className="field">Role<input value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} /></label>
        <label className="row gap-s small"><input type="checkbox" checked={f.verified} onChange={(e) => setF({ ...f, verified: e.target.checked })} /> I verified it on the source page</label>
        <button className="btn" disabled={act.busy}>Add</button>
      </form>
      <Msg msg={act.msg} />
    </Card>
  );
}

function RelationshipsTab({ o }: { o: Opportunity }) {
  const rels = useApi(() => (o.organisation_id ? api.get<Page<OrgRelationship>>("/relationships/organisations", { org_id: o.organisation_id }) : Promise.resolve(undefined)), [o.organisation_id]);
  if (!o.organisation_id) return <Empty>No organisation linked — relationships are tracked per organisation.</Empty>;
  return (
    <Card title="Organisation relationships" actions={<Link to="/chains">Open chain explorer →</Link>}>
      {rels.data?.items.length === 0 && <Empty>No relationships discovered</Empty>}
      <ul className="list-plain">
        {rels.data?.items.map((r) => (
          <li key={r.id}>
            <div className="row gap-s"><StatusBadge status={r.verification_status} /><strong>{r.source_org_name}</strong> — {r.relationship_type.replace(/_/g, " ")} → <strong>{r.target_org_name ?? r.target_label}</strong><span className="muted small">conf {r.confidence}</span></div>
            <div className="excerpt xs">{r.evidence_excerpt}</div>
            <ExtLink href={r.evidence_url} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

function OutreachTab({ o }: { o: Opportunity }) {
  const drafts = useApi(() => api.get<Page<Draft>>("/outreach/drafts", { opportunity_id: o.id }), [o.id]);
  const act = useAction();
  const nav = useNavigate();
  const create = async () => {
    const d = await act.run(() => api.post<Draft>(`/opportunities/${o.id}/outreach-drafts`));
    if (d) nav(`/outreach?draft=${d.id}`);
  };
  return (
    <Card title="Outreach drafts" actions={<button className="btn primary" disabled={act.busy || o.eligibility_outcome === "not_eligible"} onClick={create}>Generate draft</button>}>
      {o.eligibility_outcome === "not_eligible" && <div className="alert err small">Not eligible (mandatory failure) — drafting is blocked.</div>}
      <Msg msg={act.msg} />
      <div className="muted small">Drafts are never sent automatically. Each requires human approval, after which you send it yourself.</div>
      {drafts.data?.items.length === 0 && <Empty>No drafts yet</Empty>}
      <ul className="list-plain">
        {drafts.data?.items.map((d) => (
          <li key={d.id} className="row between"><Link to={`/outreach?draft=${d.id}`}>{d.email_subject}</Link><StatusBadge status={d.status} /></li>
        ))}
      </ul>
    </Card>
  );
}
