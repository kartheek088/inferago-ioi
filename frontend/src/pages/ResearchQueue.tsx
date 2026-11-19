import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, ErrorBox, Loading, Msg, PageHeader, Pager, StatusBadge, fmtDate, useAction, useApi } from "../components/ui";
import type { Opportunity, Page, ResearchTask } from "../types";
import { OpportunityTable } from "./Opportunities";

export default function ResearchQueue() {
  const [offset, setOffset] = useState(0);
  const queue = useApi(() => api.get<Page<Opportunity>>("/research/queue", { limit: 20, offset }), [offset]);
  const tasks = useApi(() => api.get<Page<ResearchTask>>("/research/tasks", { limit: 30 }));
  const settings = useApi(() => api.get<{ research_budget: Record<string, number> }>("/settings"));
  const act = useAction();
  const b = settings.data?.research_budget;
  const runBatch = async () => {
    if (await act.run(() => api.post("/research/batch"), "Research batch started in the background. Refresh in a minute.")) setTimeout(() => { queue.reload(); tasks.reload(); }, 4000);
  };
  return (
    <>
      <PageHeader title="Research Queue" subtitle="Broad collection → cheap filtering → ranking → deep research for promising candidates → human review."
        actions={<><button className="btn" onClick={() => { queue.reload(); tasks.reload(); }}>Refresh</button><button className="btn primary" disabled={act.busy} onClick={runBatch}>Run research batch</button></>} />
      <Msg msg={act.msg} />
      {b && (
        <div className="kpis">
          <div className="kpi"><div className="kpi-value">{b.raw_target}</div><div className="kpi-label">raw target</div></div>
          <div className="kpi"><div className="kpi-value">{b.shortlist_target}</div><div className="kpi-label">shortlist target</div></div>
          <div className="kpi"><div className="kpi-value">{b.deep_research_target}</div><div className="kpi-label">deep research / batch</div></div>
          <div className="kpi"><div className="kpi-value">{b.max_requests_per_task}</div><div className="kpi-label">requests / task</div></div>
          <div className="kpi"><div className="kpi-value">{b.min_priority_for_research}</div><div className="kpi-label">min priority</div></div>
          <div className="kpi"><div className="kpi-value">{b.max_ai_calls_per_batch}</div><div className="kpi-label">AI calls / batch</div></div>
        </div>
      )}
      <div className="muted small" style={{ marginBottom: 12 }}>Targets are planning budgets, not guaranteed results. Change them in Settings.</div>
      <Card title="Awaiting research (by priority)">
        <ErrorBox error={queue.error} onRetry={queue.reload} />
        {queue.loading && !queue.data ? <Loading /> : queue.data && <><OpportunityTable items={queue.data.items} /><Pager total={queue.data.total} limit={20} offset={offset} onChange={setOffset} /></>}
      </Card>
      <Card title="Recent research tasks">
        <ErrorBox error={tasks.error} />
        {tasks.data?.items.length === 0 ? <Empty>No research tasks yet</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>#</th><th>Opportunity</th><th>Status</th><th>Requests</th><th>Contacts found</th><th>Relationships</th><th>Domain verified</th><th>Completed</th></tr></thead>
              <tbody>
                {tasks.data?.items.map((t) => (
                  <tr key={t.id}>
                    <td>{t.id}</td>
                    <td><Link to={`/opportunities/${t.opportunity_id}`}>#{t.opportunity_id}</Link></td>
                    <td><StatusBadge status={t.status} />{t.error && <div className="bad-text xs">{t.error}</div>}</td>
                    <td className="mono">{t.requests_used}/{t.request_budget}</td>
                    <td>{t.findings.contacts_found ?? 0}</td>
                    <td>{t.findings.relationships_found ?? 0}</td>
                    <td>{t.findings.domain_verified ? "yes" : "no"}</td>
                    <td className="small">{fmtDate(t.completed_at, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
