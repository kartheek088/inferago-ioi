import { FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Card, DemoBadge, Empty, ErrorBox, ExtLink, Loading, Msg, PageHeader, Pager, StatusBadge, useAction, useApi } from "../components/ui";
import type { Contact, Opportunity, Organisation, OrgRelationship, Page } from "../types";
import { OpportunityTable } from "./Opportunities";

export default function Organisations() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, error, loading, reload } = useApi(() => api.get<Page<Organisation>>("/organisations", { q: query, limit: 50, offset }), [query, offset]);
  return (
    <>
      <PageHeader title="Organisations" subtitle="Buyers, vendors and partners referenced by evidence. A company existing does not establish demand." />
      <Card>
        <form className="filters" onSubmit={(e) => { e.preventDefault(); setOffset(0); setQuery(q); }}>
          <label className="field">Search<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="name or domain" /></label>
          <button className="btn">Search</button>
        </form>
        <ErrorBox error={error} onRetry={reload} />
        {loading && !data ? <Loading /> : data && (data.items.length === 0 ? <Empty>No organisations yet</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Domain</th><th>Geography</th><th>External vendors</th></tr></thead>
              <tbody>
                {data.items.map((o) => (
                  <tr key={o.id}>
                    <td><Link to={`/organisations/${o.id}`}>{o.name}</Link> <DemoBadge show={o.is_demo} /></td>
                    <td className="small">{o.domain ?? <span className="muted">—</span>} {o.domain && (o.domain_verified ? <span className="badge good xs">verified</span> : <span className="badge neutral xs">unverified</span>)}</td>
                    <td className="small">{o.country ?? <span className="muted">Unknown</span>}{o.region ? ` · ${o.region}` : ""}</td>
                    <td>{o.accepts_external_vendors === null ? <span className="muted small">unknown</span> : o.accepts_external_vendors ? <span className="badge good">accepted</span> : <span className="badge bad">no</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
        {data && <Pager total={data.total} limit={50} offset={offset} onChange={setOffset} />}
      </Card>
    </>
  );
}

interface OrgDetail {
  organisation: Organisation;
  opportunities: Opportunity[];
  contacts: Contact[];
  relationships: OrgRelationship[];
}

export function OrganisationDetail() {
  const { id } = useParams();
  const d = useApi(() => api.get<OrgDetail>(`/organisations/${id}`), [id]);
  const act = useAction();
  const [edit, setEdit] = useState<Partial<Organisation> | null>(null);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!edit) return;
    const body = { ...edit, website: edit.website || null };
    if (await act.run(() => api.patch(`/organisations/${id}`, body), "Saved; related opportunities re-scored")) { setEdit(null); d.reload(); }
  };
  const o = d.data?.organisation;
  return (
    <>
      <ErrorBox error={d.error} onRetry={d.reload} />
      {!d.data ? <Loading /> : o && (
        <>
          <PageHeader title={o.name} subtitle={<span>{o.website ? <ExtLink href={o.website} /> : "No website"} {o.domain_verified && <span className="badge good">domain verified</span>}</span>}
            actions={<button className="btn" onClick={() => setEdit(edit ? null : { website: o.website, country: o.country, region: o.region, industry: o.industry, description: o.description })}>{edit ? "Cancel" : "Edit"}</button>} />
          <Msg msg={act.msg} />
          {edit && (
            <Card title="Edit organisation">
              <form className="filters" onSubmit={save}>
                <label className="field">Website<input type="url" value={edit.website ?? ""} onChange={(e) => setEdit({ ...edit, website: e.target.value })} /></label>
                <label className="field">Country<input value={edit.country ?? ""} onChange={(e) => setEdit({ ...edit, country: e.target.value || null })} /></label>
                <label className="field">Region<input value={edit.region ?? ""} onChange={(e) => setEdit({ ...edit, region: e.target.value || null })} /></label>
                <label className="field">Industry<input value={edit.industry ?? ""} onChange={(e) => setEdit({ ...edit, industry: e.target.value || null })} /></label>
                <label className="field" style={{ flex: 1 }}>Description<input value={edit.description ?? ""} onChange={(e) => setEdit({ ...edit, description: e.target.value || null })} /></label>
                <button className="btn primary">Save</button>
              </form>
            </Card>
          )}
          <Card title="Profile">
            <dl className="kv">
              <dt>Geography</dt><dd>{o.country ?? "Unknown"}{o.region ? `, ${o.region}` : ""}</dd>
              <dt>Industry</dt><dd>{o.industry ?? "—"}</dd>
              <dt>External vendors</dt><dd>{o.accepts_external_vendors === null ? "Unknown" : o.accepts_external_vendors ? "Accepted (evidence on vendor page)" : "Not accepted"}</dd>
              <dt>Description</dt><dd className="wrap">{o.description ?? "—"}</dd>
            </dl>
          </Card>
          <Card title={`Opportunities (${d.data.opportunities.length})`}><OpportunityTable items={d.data.opportunities} /></Card>
          <div className="grid grid-2">
            <Card title="Contact routes">
              {d.data.contacts.length === 0 ? <Empty>None recorded</Empty> : (
                <ul className="list-plain">{d.data.contacts.map((c) => (
                  <li key={c.id} className="small wrap">{c.contact_type.replace(/_/g, " ")}: <strong>{c.value}</strong> {c.verified ? <span className="badge good xs">verified</span> : <span className="badge warn xs">unverified</span>}<div className="muted xs">source: <ExtLink href={c.source_url} /></div></li>
                ))}</ul>
              )}
            </Card>
            <Card title="Relationships">
              {d.data.relationships.length === 0 ? <Empty>None discovered</Empty> : (
                <ul className="list-plain">{d.data.relationships.map((r) => (
                  <li key={r.id} className="small"><StatusBadge status={r.verification_status} /> {r.relationship_type.replace(/_/g, " ")} → {r.target_org_name ?? r.target_label} <ExtLink href={r.evidence_url}>evidence</ExtLink></li>
                ))}</ul>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
