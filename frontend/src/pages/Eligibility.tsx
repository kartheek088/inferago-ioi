import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, EligibilityBadge, ErrorBox, Loading, PageHeader, Pager, fmtDate, useApi } from "../components/ui";
import type { Assessment, Page } from "../types";
import { OUTCOMES } from "./Opportunities";

export default function Eligibility() {
  const [outcome, setOutcome] = useState("");
  const [scope, setScope] = useState("project");
  const [offset, setOffset] = useState(0);
  const profile = useApi(() => api.get<{ profile: Record<string, unknown> }>("/profile"));
  const { data, error, loading, reload } = useApi(() => api.get<Page<Assessment>>("/eligibility", { outcome, scope, limit: 25, offset }), [outcome, scope, offset]);
  const p = profile.data?.profile;
  return (
    <>
      <PageHeader title="Eligibility" subtitle="Latest deterministic assessment per opportunity. Mandatory failures override scores; unknown is never treated as satisfied." />
      {p && (
        <Card title="Profile used for every assessment (real data only)">
          <div className="row gap small">
            <span className="badge neutral">Sole proprietorship</span>
            <span className="badge good">Udyam/MSME registered</span>
            <span className="badge good">PAN (proprietor-linked)</span>
            <span className="badge bad">GST not registered</span>
            <span className="badge bad">No corporate project credentials</span>
            <span className="badge neutral">Turnover: {p.annual_turnover_inr ? String(p.annual_turnover_inr) : "not established"}</span>
            <span className="badge neutral">Dedicated employees: {String(p.dedicated_employees)}</span>
            <span className="badge neutral">{String(p.region)}, {String(p.country)}</span>
          </div>
          <div className="muted xs pad-t">Decision support only — not legal or tax advice.</div>
        </Card>
      )}
      <Card>
        <div className="filters">
          <label className="field">Scope<select value={scope} onChange={(e) => { setScope(e.target.value); setOffset(0); }}><option value="project">Project</option><option value="vendor_registration">Vendor registration</option></select></label>
          <label className="field">Outcome<select value={outcome} onChange={(e) => { setOutcome(e.target.value); setOffset(0); }}><option value="">All</option>{OUTCOMES.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}</select></label>
        </div>
        <ErrorBox error={error} onRetry={reload} />
        {loading && !data ? <Loading /> : data && (data.items.length === 0 ? <Empty>No assessments match</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Opportunity</th><th>Outcome</th><th>Mandatory failures</th><th>Open questions</th><th>Next action</th><th>Assessed</th></tr></thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id}>
                    <td><Link to={`/opportunities/${a.opportunity_id}`}>#{a.opportunity_id}</Link></td>
                    <td><EligibilityBadge outcome={a.outcome} /></td>
                    <td className="small wrap">{a.mandatory_failures.map((f) => f.key).join(", ") || "—"}</td>
                    <td className="small wrap">{a.clarifications.slice(0, 2).join(" · ") || "—"}</td>
                    <td className="small wrap">{a.next_action}</td>
                    <td className="small">{fmtDate(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
        {data && <Pager total={data.total} limit={25} offset={offset} onChange={setOffset} />}
      </Card>
    </>
  );
}
