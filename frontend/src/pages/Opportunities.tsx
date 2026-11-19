import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Card, DemoBadge, Empty, EligibilityBadge, ErrorBox, Geo, Loading, OppLink, PageHeader, Pager, PipelineBadge, ScorePills, StatusBadge, fmtDate, useApi } from "../components/ui";
import type { Opportunity, Page } from "../types";

export const CATEGORIES = [
  "direct_software_project", "vendor_onboarding", "subcontracting", "implementation_partnership", "government_tender",
  "private_procurement", "weak_buying_signal", "general_organisation",
];
export const OUTCOMES = ["eligible", "potentially_eligible", "partner_route", "unclear", "unknown", "not_eligible"];
export const STATUSES = ["new", "shortlisted", "researching", "qualified", "outreach", "needs_manual_review", "rejected", "archived"];

export function OpportunityTable({ items }: { items: Opportunity[] }) {
  if (!items.length) return <Empty>No opportunities match these filters.</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th>Priority</th><th>Opportunity</th><th>Pipeline</th><th>Eligibility</th><th>Scores</th><th>Geography</th><th>Status</th><th>Published</th></tr>
        </thead>
        <tbody>
          {items.map((o) => (
            <tr key={o.id}>
              <td className="mono"><strong>{o.priority ?? "—"}</strong></td>
              <td className="title-cell wrap">
                <span className="clamp-2" title={o.title}><OppLink id={o.id} title={o.title} /> <DemoBadge show={o.is_demo} /></span>
                <div className="muted xs">
                  {o.organisation_name ?? "Organisation unknown"} · {o.category.replace(/_/g, " ")} · {o.source_key}
                  {o.budget_text && ` · ${o.budget_text}`}
                </div>
              </td>
              <td><PipelineBadge pipeline={o.pipeline} /></td>
              <td><EligibilityBadge outcome={o.eligibility_outcome} /></td>
              <td><ScorePills scores={o.scores} /></td>
              <td className="small"><Geo country={o.country} region={o.region} /></td>
              <td><StatusBadge status={o.status} /></td>
              <td className="small">{fmtDate(o.published_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Opportunities() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const f = Object.fromEntries(params.entries());
  const offset = Number(f.offset ?? 0);
  const { data, error, loading, reload } = useApi(
    () => api.get<Page<Opportunity>>("/opportunities", { ...f, limit: 50, offset }),
    [params.toString()],
  );
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    next.delete("offset");
    setParams(next);
  };
  const sel = (k: string, label: string, options: string[]) => (
    <label className="field">
      {label}
      <select value={f[k] ?? ""} onChange={(e) => set(k, e.target.value)}>
        <option value="">All</option>
        {options.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
      </select>
    </label>
  );
  return (
    <>
      <PageHeader title="Opportunities" subtitle="Ranked by priority = the pipeline's effective score + explicit-geography bonus. Disqualified items rank 0." />
      <Card>
        <form className="filters" onSubmit={(e) => { e.preventDefault(); set("q", q); }}>
          <label className="field">Search<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="title or text" /></label>
          {sel("pipeline", "Pipeline", ["A_direct", "B_vendor", "C_chain"])}
          {sel("category", "Category", CATEGORIES)}
          {sel("eligibility", "Eligibility", OUTCOMES)}
          {sel("status", "Status", STATUSES)}
          <label className="field">Country<input defaultValue={f.country ?? ""} onBlur={(e) => set("country", e.target.value)} placeholder="India / unknown" style={{ width: 120 }} /></label>
          <label className="field">Min priority<input type="number" defaultValue={f.min_priority ?? ""} onBlur={(e) => set("min_priority", e.target.value)} style={{ width: 90 }} /></label>
          {sel("sort", "Sort", ["priority", "newest", "collected", "deadline"])}
          <label className="field">Demo data
            <select value={f.include_demo ?? "true"} onChange={(e) => set("include_demo", e.target.value)}>
              <option value="true">Include</option><option value="false">Exclude</option>
            </select>
          </label>
          <button className="btn">Apply</button>
        </form>
        <ErrorBox error={error} onRetry={reload} />
        {loading && !data ? <Loading /> : data && (
          <>
            <OpportunityTable items={data.items} />
            <Pager total={data.total} limit={50} offset={offset} onChange={(o) => { const n = new URLSearchParams(params); n.set("offset", String(o)); setParams(n); }} />
          </>
        )}
      </Card>
    </>
  );
}
