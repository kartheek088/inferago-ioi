import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, ErrorBox, Msg, PageHeader, StatusBadge, fmtDate, useAction, useApi } from "../components/ui";
import type { CallTask, FollowUp, Page } from "../types";

const OUTCOMES = ["interested", "not_interested", "call_back", "wrong_contact", "existing_vendor", "wants_company_profile", "wants_proposal", "shared_vendor_details", "no_answer"];

function CallRow({ t, onDone }: { t: CallTask; onDone: () => void }) {
  const act = useAction();
  const [outcome, setOutcome] = useState("interested");
  const [notes, setNotes] = useState("");
  return (
    <tr>
      <td><Link to={`/opportunities/${t.opportunity_id}`}>#{t.opportunity_id}</Link></td>
      <td className="small">{fmtDate(t.scheduled_for, true)}</td>
      <td><StatusBadge status={t.outcome ?? t.status} /></td>
      <td>
        {t.status === "open" ? (
          <div className="row gap-s">
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)} aria-label="Outcome">{OUTCOMES.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}</select>
            <input placeholder="notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <button className="btn sm" disabled={act.busy} onClick={async () => { if (await act.run(() => api.post(`/call-tasks/${t.id}/outcome`, { outcome, notes: notes || null }))) onDone(); }}>Record</button>
          </div>
        ) : <span className="small wrap">{t.notes}</span>}
        <Msg msg={act.msg} />
      </td>
    </tr>
  );
}

export default function FollowUps() {
  const [status, setStatus] = useState("open");
  const fus = useApi(() => api.get<Page<FollowUp>>("/follow-ups", { status, limit: 200 }), [status]);
  const calls = useApi(() => api.get<Page<CallTask>>("/call-tasks", { limit: 100 }));
  const act = useAction();
  const [nc, setNc] = useState({ opportunity_id: "", scheduled_for: "" });
  const reload = () => { fus.reload(); calls.reload(); };
  const addCall = async (e: FormEvent) => {
    e.preventDefault();
    if (await act.run(() => api.post("/call-tasks", { opportunity_id: Number(nc.opportunity_id), scheduled_for: nc.scheduled_for || null }), "Call task created")) reload();
  };
  const now = Date.now();
  return (
    <>
      <PageHeader title="Follow-ups" subtitle="Tasks generated from call outcomes and manually-sent outreach. Calls are made by you; IOI only tracks them." />
      <Card title="Follow-up tasks" actions={<select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="open">Open</option><option value="done">Done</option><option value="cancelled">Cancelled</option><option value="">All</option></select>}>
        <ErrorBox error={fus.error} />
        {fus.data?.items.length === 0 ? <Empty>Nothing to follow up</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Due</th><th>Action</th><th>Opportunity</th><th>Reason</th><th>Status</th><th /></tr></thead>
              <tbody>
                {fus.data?.items.map((f) => {
                  const overdue = f.status === "open" && f.due_date && new Date(`${f.due_date}Z`).getTime() < now;
                  return (
                    <tr key={f.id}>
                      <td className={`small ${overdue ? "bad-text" : ""}`}>{fmtDate(f.due_date)}{overdue && " (overdue)"}</td>
                      <td className="wrap">{f.action}</td>
                      <td><Link to={`/opportunities/${f.opportunity_id}`}>#{f.opportunity_id}</Link></td>
                      <td className="small muted">{f.reason}</td>
                      <td><StatusBadge status={f.status} /></td>
                      <td>{f.status === "open" && <span className="row gap-s">
                        <button className="btn sm" onClick={async () => { if (await act.run(() => api.patch(`/follow-ups/${f.id}`, { status: "done" }))) fus.reload(); }}>Done</button>
                        <button className="btn sm danger" onClick={async () => { if (await act.run(() => api.patch(`/follow-ups/${f.id}`, { status: "cancelled" }))) fus.reload(); }}>Cancel</button>
                      </span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Call tasks">
        <div className="muted small">A call task needs an approved outreach draft for the opportunity (human approval gate).</div>
        <form className="filters pad-t" onSubmit={addCall}>
          <label className="field">Opportunity ID<input required type="number" value={nc.opportunity_id} onChange={(e) => setNc({ ...nc, opportunity_id: e.target.value })} style={{ width: 120 }} /></label>
          <label className="field">Scheduled for<input type="datetime-local" value={nc.scheduled_for} onChange={(e) => setNc({ ...nc, scheduled_for: e.target.value })} /></label>
          <button className="btn">Create call task</button>
        </form>
        <Msg msg={act.msg} />
        {calls.data?.items.length === 0 ? <Empty>No call tasks</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Opportunity</th><th>Scheduled</th><th>Status</th><th>Outcome</th></tr></thead>
              <tbody>{calls.data?.items.map((t) => <CallRow key={t.id} t={t} onDone={reload} />)}</tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
