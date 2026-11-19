import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, EligibilityBadge, ErrorBox, Loading, PageHeader, Pager, useApi } from "../components/ui";
import type { Assessment, Opportunity, Organisation, Page } from "../types";
import { OpportunityTable } from "./Opportunities";

const VENDOR_CATS = ["", "vendor_onboarding", "subcontracting", "implementation_partnership", "government_tender", "private_procurement"];

export default function VendorIntelligence() {
  const [category, setCategory] = useState("");
  const [offset, setOffset] = useState(0);
  const opps = useApi(() => api.get<Page<Opportunity>>("/opportunities", { pipeline: "B_vendor", category, limit: 25, offset }), [category, offset]);
  const orgs = useApi(() => api.get<Page<Organisation>>("/organisations", { accepts_external_vendors: true, limit: 50 }));
  const vreg = useApi(() => api.get<Page<Assessment>>("/eligibility", { scope: "vendor_registration", limit: 50 }));
  const vregKnown = vreg.data?.items.filter((a) => a.outcome !== "unknown") ?? [];
  return (
    <>
      <PageHeader title="Vendor Intelligence" subtitle="Pipeline B: vendor onboarding, subcontracting, implementation partnerships and procurement. A contract award does not prove subcontracting." />
      <Card title="Vendor & subcontracting opportunities" actions={
        <select value={category} onChange={(e) => { setCategory(e.target.value); setOffset(0); }} aria-label="Category">
          {VENDOR_CATS.map((c) => <option key={c} value={c}>{c ? c.replace(/_/g, " ") : "All categories"}</option>)}
        </select>}>
        <ErrorBox error={opps.error} onRetry={opps.reload} />
        {opps.loading && !opps.data ? <Loading /> : opps.data && <><OpportunityTable items={opps.data.items} /><Pager total={opps.data.total} limit={25} offset={offset} onChange={setOffset} /></>}
      </Card>
      <div className="grid grid-2">
        <Card title="Organisations with evidence they accept external vendors">
          <ErrorBox error={orgs.error} />
          {orgs.data?.items.length === 0 ? <Empty>None confirmed yet. Research finds vendor/supplier pages on official sites.</Empty> : (
            <ul className="list-plain">{orgs.data?.items.map((o) => <li key={o.id}><Link to={`/organisations/${o.id}`}>{o.name}</Link> <span className="muted small">{o.domain}</span></li>)}</ul>
          )}
        </Card>
        <Card title="Vendor registration assessments (separate from project eligibility)">
          <ErrorBox error={vreg.error} />
          {vregKnown.length === 0 ? <Empty>No vendor-registration requirements identified yet.</Empty> : (
            <ul className="list-plain">{vregKnown.map((a) => (
              <li key={a.id} className="row between gap"><Link to={`/opportunities/${a.opportunity_id}`}>Opportunity #{a.opportunity_id}</Link><EligibilityBadge outcome={a.outcome} /></li>
            ))}</ul>
          )}
        </Card>
      </div>
    </>
  );
}
