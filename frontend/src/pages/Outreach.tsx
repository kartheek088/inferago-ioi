import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, getActor } from "../api";
import { Card, Empty, ErrorBox, ExtLink, Loading, Msg, PageHeader, StatusBadge, fmtDate, useAction, useApi } from "../components/ui";
import type { Draft, Page } from "../types";

interface Approval { id: number; decision: string; decided_by: string; note: string | null; decided_at: string }

function DraftEditor({ id, onChanged }: { id: number; onChanged: () => void }) {
  const d = useApi(() => api.get<Draft>(`/outreach/drafts/${id}`), [id]);
  const approvals = useApi(() => api.get<Page<Approval>>("/approvals", { draft_id: id }), [id]);
  const act = useAction();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [opening, setOpening] = useState("");
  const [approver, setApprover] = useState(getActor());
  const [note, setNote] = useState("");
  useEffect(() => {
    if (d.data) { setSubject(d.data.email_subject); setBody(d.data.email_body); setOpening(d.data.call_opening); }
  }, [d.data]);
  const refresh = () => { d.reload(); approvals.reload(); onChanged(); };
  const x = d.data;
  if (!x) return d.error ? <ErrorBox error={d.error} /> : <Loading />;
  const dirty = subject !== x.email_subject || body !== x.email_body || opening !== x.call_opening;
  return (
    <Card title={<span className="row gap-s">Draft #{x.id} <StatusBadge status={x.status} /> <span className="muted small">by {x.generated_by}</span></span>}
      actions={<Link to={`/opportunities/${x.opportunity_id}`}>Opportunity #{x.opportunity_id} →</Link>}>
      <div className="alert info small">IOI never sends email, places calls, submits bids or registers as a vendor. After approval, send it yourself and click “Mark sent manually”.</div>
      <Msg msg={act.msg} />
      <div className="grid grid-2">
        <div className="stack">
          <label className="field">Email subject<input value={subject} onChange={(e) => setSubject(e.target.value)} /></label>
          <label className="field">Email body<textarea rows={12} value={body} onChange={(e) => setBody(e.target.value)} /></label>
          <label className="field">Call opening<textarea rows={3} value={opening} onChange={(e) => setOpening(e.target.value)} /></label>
          <div className="row gap">
            <button className="btn" disabled={!dirty || act.busy} onClick={async () => { if (await act.run(() => api.patch(`/outreach/drafts/${id}`, { email_subject: subject, email_body: body, call_opening: opening }), x.status === "approved" ? "Saved — approval invalidated, resubmit required" : "Saved")) refresh(); }}>Save edits</button>
            {(x.status === "draft" || x.status === "rejected") && <button className="btn primary" disabled={dirty || act.busy} onClick={async () => { if (await act.run(() => api.post(`/outreach/drafts/${id}/submit`), "Submitted for approval")) refresh(); }}>Submit for approval</button>}
            {x.status === "approved" && <button className="btn primary" disabled={act.busy} onClick={async () => { if (await act.run(() => api.post(`/outreach/drafts/${id}/mark-sent`), "Recorded as sent by you; follow-up created")) refresh(); }}>Mark sent manually</button>}
          </div>
          {x.status === "pending_approval" && (
            <div className="card" style={{ marginTop: 12 }}>
              <h3 style={{ marginTop: 0 }}>Human approval</h3>
              <div className="filters">
                <label className="field">Approver<input value={approver} onChange={(e) => setApprover(e.target.value)} /></label>
                <label className="field" style={{ flex: 1 }}>Note<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
              </div>
              <div className="row gap">
                <button className="btn primary" disabled={!approver.trim() || act.busy} onClick={async () => { if (await act.run(() => api.post(`/outreach/drafts/${id}/decision`, { decision: "approved", decided_by: approver, note: note || null }), "Approved")) refresh(); }}>Approve</button>
                <button className="btn danger" disabled={!approver.trim() || act.busy} onClick={async () => { if (await act.run(() => api.post(`/outreach/drafts/${id}/decision`, { decision: "rejected", decided_by: approver, note: note || null }), "Rejected")) refresh(); }}>Reject</button>
              </div>
            </div>
          )}
          {approvals.data && approvals.data.items.length > 0 && (
            <div className="small">
              <strong>Approval history</strong>
              <ul>{approvals.data.items.map((a) => <li key={a.id}>{a.decision} by {a.decided_by} · {fmtDate(a.decided_at, true)}{a.note ? ` — ${a.note}` : ""}</li>)}</ul>
            </div>
          )}
        </div>
        <div className="stack small">
          <div><strong>Company background</strong><div className="wrap">{x.company_background}</div></div>
          <div><strong>Why shortlisted</strong><div className="wrap">{x.why_shortlisted}</div></div>
          <div><strong>Buying signal</strong><div className="excerpt xs">{x.buying_signal}</div></div>
          <div><strong>Relevant Inferago capability</strong><div>{x.relevant_capability}</div></div>
          <div><strong>Contact route</strong><div className="wrap">{x.contact_route}</div></div>
          <div><strong>Evidence</strong><ul>{x.evidence_links.map((l) => <li key={l} className="wrap"><ExtLink href={l} /></li>)}</ul></div>
          <div><strong>Discovery questions</strong><ul>{x.discovery_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></div>
          <div><strong>Likely objections</strong><ul>{x.likely_objections.map((q, i) => <li key={i}>{q}</li>)}</ul></div>
          <div><strong>Recommended next action</strong><div>{x.recommended_next_action}</div></div>
        </div>
      </div>
    </Card>
  );
}

export default function Outreach() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState("");
  const drafts = useApi(() => api.get<Page<Draft>>("/outreach/drafts", { status, limit: 100 }), [status]);
  const selected = Number(params.get("draft") ?? 0);
  return (
    <>
      <PageHeader title="Outreach" subtitle="Prepare, edit and approve outreach. All outbound communication requires explicit human approval." />
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 320px) minmax(0, 1fr)" }}>
        <Card title="Drafts" actions={
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="">All</option>{["draft", "pending_approval", "approved", "rejected", "sent_manually"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
          </select>}>
          <ErrorBox error={drafts.error} />
          {drafts.data?.items.length === 0 && <Empty>No drafts. Generate one from an opportunity's Outreach tab.</Empty>}
          <ul className="list-plain">
            {drafts.data?.items.map((d) => (
              <li key={d.id}>
                <a href="#" onClick={(e) => { e.preventDefault(); setParams({ draft: String(d.id) }); }} style={{ fontWeight: d.id === selected ? 700 : 400 }}>{d.email_subject}</a>
                <div className="row gap-s xs"><StatusBadge status={d.status} /><span className="muted">{fmtDate(d.updated_at)}</span></div>
              </li>
            ))}
          </ul>
        </Card>
        <div>{selected ? <DraftEditor key={selected} id={selected} onChanged={drafts.reload} /> : <Empty>Select a draft</Empty>}</div>
      </div>
    </>
  );
}
