import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ThisWeek from "../components/ThisWeek";
import { Empty, ErrorBox, Loading, fmtDate, useApi } from "../components/ui";
import { Prospect, ProspectCard, ProspectDrawer } from "./Prospects";

interface Page { items: Prospect[]; total: number }
interface Dash {
  totals: Record<string, number>;
  top_opportunities: { id: number; title: string; priority: number; pipeline: string; eligibility: string | null; country: string | null; is_demo: boolean }[];
}

const PIPE: Record<string, string> = { A_direct: "Client", B_vendor: "Vendor / tender", C_chain: "Lead", none: "" };

export default function Today() {
  const due = useApi(() => api.get<Page>("/prospects", { sort: "follow_up", status: "open", limit: 50 }));
  const hot = useApi(() => api.get<Page>("/prospects", { status: "new", min_score: 60, limit: 6 }));
  const dash = useApi(() => api.get<Dash>("/dashboard/summary"));
  const [open, setOpen] = useState<Prospect | null>(null);
  const now = Date.now();
  const dueNow = (due.data?.items ?? []).filter((p) => p.next_follow_up && new Date(`${p.next_follow_up}Z`).getTime() <= now + 86400000);
  const hour = new Date().getHours();
  const hello = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  return (
    <>
      <header className="hero">
        <div>
          <h1>{hello} 👋</h1>
          <p className="muted">Here’s what needs you today. Start at the top and work down.</p>
        </div>
        <div className="row gap">
          <Link className="btn primary" to="/call">💬 Start outreach</Link>
          <Link className="btn" to="/prospects">Prospects</Link>
          <Link className="btn" to="/discover">Find projects & tenders</Link>
        </div>
      </header>
      <ErrorBox error={due.error || hot.error || dash.error} onRetry={() => { due.reload(); hot.reload(); dash.reload(); }} />

      <section className="today-step">
        <div className="step-num">1</div>
        <div className="step-body">
          <h2>Follow up <span className="muted small">people waiting to hear back</span></h2>
          {due.loading && !due.data ? <Loading /> : dueNow.length === 0 ? (
            <p className="muted small">Nothing due. 👍</p>
          ) : (
            <ul className="list-plain">
              {dueNow.map((p) => (
                <li key={p.id} className="row between gap">
                  <button className="link-btn" onClick={() => setOpen(p)}>{p.name}</button>
                  <span className="muted small">{p.type_label} · due {fmtDate(p.next_follow_up)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="today-step">
        <div className="step-num">2</div>
        <div className="step-body">
          <div className="row between"><h2>Contact hot prospects <span className="muted small">no website or a weak one, easy to reach</span></h2><Link to="/prospects" className="small">All prospects →</Link></div>
          {hot.loading && !hot.data ? <Loading /> : hot.data?.items.length ? (
            <div className="p-grid">{hot.data.items.map((p) => <ProspectCard key={p.id} p={p} onOpen={() => setOpen(p)} />)}</div>
          ) : (
            <Empty>No hot prospects yet. <Link to="/prospects">Find prospects</Link> in your cities.</Empty>
          )}
        </div>
      </section>

      <section className="today-step">
        <div className="step-num">3</div>
        <div className="step-body">
          <div className="row between"><h2>Reply to project requests <span className="muted small">people and companies asking for work</span></h2><Link to="/opportunities" className="small">All projects →</Link></div>
          {dash.loading && !dash.data ? <Loading /> : dash.data?.top_opportunities.length ? (
            <ul className="list-plain">
              {dash.data.top_opportunities.slice(0, 6).map((o) => (
                <li key={o.id} className="row between gap">
                  <Link to={`/opportunities/${o.id}`} className="wrap clamp-2" style={{ flex: 1, minWidth: 0 }}>{o.title}</Link>
                  <span className="row gap-s">
                    {PIPE[o.pipeline] && <span className="badge">{PIPE[o.pipeline]}</span>}
                    {o.country && <span className="badge info">{o.country}</span>}
                    <strong className="mono small">{Math.round(o.priority)}</strong>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No project requests yet. <Link to="/discover">Run a search</Link>.</Empty>
          )}
          {dash.data && dash.data.totals.drafts_pending_approval > 0 && (
            <p className="small"><Link to="/outreach">{dash.data.totals.drafts_pending_approval} message draft(s) waiting for your approval →</Link></p>
          )}
        </div>
      </section>

      <section className="today-step">
        <div className="step-num">4</div>
        <div className="step-body"><ThisWeek /></div>
      </section>

      {open && (
        <ProspectDrawer p={open} onClose={() => setOpen(null)} onChange={(np) => { setOpen(np); due.reload(); hot.reload(); }} />
      )}
    </>
  );
}
