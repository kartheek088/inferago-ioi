import { Link } from "react-router-dom";
import ThisWeek from "../components/ThisWeek";
import { api } from "../api";
import { Card, DemoBadge, Empty, EligibilityBadge, ErrorBox, Kpi, Loading, PageHeader, PIPELINE_LABEL, PipelineBadge, StatusBadge, fmtDate, useApi } from "../components/ui";

interface Summary {
  totals: Record<string, number>;
  by_pipeline: Record<string, number>;
  by_status: Record<string, number>;
  by_eligibility: Record<string, number>;
  by_category: Record<string, number>;
  by_country: Record<string, number>;
  top_opportunities: { id: number; title: string; priority: number; pipeline: string; eligibility: string | null; country: string | null; is_demo: boolean }[];
  recent_runs: { id: number; source: string; status: string; started_at: string; items_new: number; error: string | null }[];
  source_health: { key: string; name: string; enabled: boolean; status: string; last_success_at: string | null; failure_status: string | null }[];
}

function Dist({ data, labels }: { data: Record<string, number>; labels?: Record<string, string> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (!entries.length) return <Empty>No data yet</Empty>;
  return (
    <div className="dist">
      {entries.map(([k, v]) => (
        <div className="dist-row" key={k}>
          <span className="wrap">{labels?.[k] ?? k.replace(/_/g, " ")}</span>
          <div className="bar">
            <div className="fill" style={{ width: `${(v / max) * 100}%` }} />
          </div>
          <span className="mono">{v}</span>
        </div>
      ))}
    </div>
  );
}

export default function Overview() {
  const { data, error, loading, reload } = useApi(() => api.get<Summary>("/dashboard/summary"));
  return (
    <>
      <PageHeader title="Stats" subtitle="Live counts from the database." actions={<button className="btn" onClick={reload}>Refresh</button>} />
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data && <Loading />}
      {data && (
        <>
          {data.totals.demo_opportunities > 0 && (
            <div className="alert warn">{data.totals.demo_opportunities} demonstration fixture(s) are loaded and marked DEMO. They are not real leads.</div>
          )}
          <ThisWeek />
          <div className="kpis">
            <Kpi label="Active opportunities" value={data.totals.opportunities} hint={`${data.totals.opportunities_7d} new in 7 days`} to="/opportunities" />
            <Kpi label="Organisations" value={data.totals.organisations} to="/organisations" />
            <Kpi label="Raw records collected" value={data.totals.raw_records} to="/evidence" />
            <Kpi label="Research in progress" value={data.totals.research_queued} to="/research" />
            <Kpi label="Drafts awaiting approval" value={data.totals.drafts_pending_approval} to="/outreach" />
            <Kpi label="Follow-ups due (24h)" value={data.totals.follow_ups_due} to="/follow-ups" />
            <Kpi label="Confirmed relationships" value={data.totals.relationships_confirmed} hint={`${data.totals.relationships_hypotheses} hypotheses`} to="/chains" />
          </div>
          {data.totals.opportunities === 0 && (
            <div className="alert info">
              No opportunities yet. <Link to="/discover">Run a discovery</Link> against a live source, or import a tender document.
            </div>
          )}
          <div className="grid grid-2">
            <Card title="Top priorities" actions={<Link to="/opportunities">All →</Link>}>
              {data.top_opportunities.length === 0 ? (
                <Empty>No ranked opportunities</Empty>
              ) : (
                <ul className="list-plain">
                  {data.top_opportunities.map((o) => (
                    <li key={o.id} className="row between gap">
                      <span style={{ minWidth: 0, flex: 1 }} className="wrap clamp-2" title={o.title}>
                        <Link to={`/opportunities/${o.id}`}>{o.title}</Link> <DemoBadge show={o.is_demo} />
                      </span>
                      <span className="row gap-s">
                        <PipelineBadge pipeline={o.pipeline} />
                        <EligibilityBadge outcome={o.eligibility} />
                        <strong className="mono">{o.priority}</strong>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Recent collection runs" actions={<Link to="/sources">Sources →</Link>}>
              {data.recent_runs.length === 0 ? (
                <Empty>No runs yet</Empty>
              ) : (
                <ul className="list-plain">
                  {data.recent_runs.map((r) => (
                    <li key={r.id} className="row between gap">
                      <span>
                        {r.source} <span className="muted small">· {fmtDate(r.started_at, true)}</span>
                        {r.error && <div className="bad-text xs wrap">{r.error}</div>}
                      </span>
                      <span className="row gap-s">
                        <StatusBadge status={r.status} />
                        <span className="small">+{r.items_new}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="By pipeline">
              <Dist data={data.by_pipeline} labels={PIPELINE_LABEL} />
            </Card>
            <Card title="Eligibility outcomes">
              <Dist data={data.by_eligibility} />
            </Card>
            <Card title="By country (explicit only)">
              <Dist data={data.by_country} />
            </Card>
            <Card title="By status">
              <Dist data={data.by_status} />
            </Card>
          </div>
          <Card title="Enabled source health">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Source</th><th>Connector</th><th>Last success</th><th>Failure</th></tr>
                </thead>
                <tbody>
                  {data.source_health.map((s) => (
                    <tr key={s.key}>
                      <td>{s.name}</td>
                      <td><StatusBadge status={s.status} /></td>
                      <td>{fmtDate(s.last_success_at, true)}</td>
                      <td className="bad-text small wrap">{s.failure_status ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
