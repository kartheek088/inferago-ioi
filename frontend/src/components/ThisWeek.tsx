import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { ActionItem } from "../types";
import { Card, Empty, ErrorBox, Msg, fmtDate, useAction, useApi } from "./ui";

const CAT_TONE: Record<string, string> = { security: "bad", compliance: "warn", partner: "info", routine: "neutral", general: "neutral" };

function Target({ a }: { a: ActionItem }) {
  if (a.opportunity_id) return <Link to={`/opportunities/${a.opportunity_id}`}>{a.title}</Link>;
  if (a.url?.startsWith("/")) return <Link to={a.url}>{a.title}</Link>;
  if (a.url && /^https?:\/\//.test(a.url)) return <a href={a.url} target="_blank" rel="noopener noreferrer">{a.title} ↗</a>;
  return <span>{a.title}</span>;
}

export default function ThisWeek() {
  const [showDone, setShowDone] = useState(false);
  const list = useApi(() => api.get<ActionItem[]>("/actions", { status: showDone ? "" : "open" }), [showDone]);
  const act = useAction();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");

  const toggle = async (a: ActionItem) => {
    if (await act.run(() => api.patch(`/actions/${a.id}`, { status: a.status === "done" ? "open" : "done" }))) list.reload();
  };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (await act.run(() => api.post("/actions", { title, due_date: due || null }))) { setTitle(""); setDue(""); list.reload(); }
  };
  const items = list.data ?? [];
  const open = items.filter((a) => a.status === "open").length;
  const now = Date.now();

  return (
    <Card
      title={<span>This week <span className="muted small">· {open} open</span></span>}
      actions={<label className="row gap-s small"><input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> show done</label>}
    >
      <ErrorBox error={list.error} onRetry={list.reload} />
      <Msg msg={act.msg?.kind === "err" ? act.msg : undefined} />
      {items.length === 0 && !list.loading && <Empty>All done. Add your next action below.</Empty>}
      <ul className="list-plain">
        {items.map((a) => {
          const overdue = a.status === "open" && a.due_date && new Date(`${a.due_date}Z`).getTime() < now;
          return (
            <li key={a.id} className="row gap" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
              <input type="checkbox" aria-label={`Mark "${a.title}" done`} checked={a.status === "done"} onChange={() => toggle(a)} style={{ marginTop: 3 }} />
              <div style={{ minWidth: 0, flex: 1, opacity: a.status === "done" ? 0.55 : 1, textDecoration: a.status === "done" ? "line-through" : "none" }}>
                <div className="row gap-s"><Target a={a} /> <span className={`badge xs ${CAT_TONE[a.category] ?? "neutral"}`}>{a.category}</span></div>
                {a.detail && <div className="muted xs wrap">{a.detail}</div>}
              </div>
              <span className={`small ${overdue ? "bad-text" : "muted"}`} style={{ whiteSpace: "nowrap" }}>{a.due_date ? `${overdue ? "overdue · " : ""}${fmtDate(a.due_date)}` : ""}</span>
            </li>
          );
        })}
      </ul>
      <form className="filters pad-t" onSubmit={add} style={{ marginBottom: 0 }}>
        <label className="field" style={{ flex: 1, minWidth: 200 }}>New action<input required minLength={2} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Reply to Collabify contract post" /></label>
        <label className="field">Due<input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>
        <button className="btn" disabled={act.busy}>Add</button>
      </form>
    </Card>
  );
}
