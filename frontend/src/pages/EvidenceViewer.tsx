import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, ErrorBox, ExtLink, Loading, PageHeader, Pager, fmtDate, useApi } from "../components/ui";
import type { Evidence, Page } from "../types";

export default function EvidenceViewer() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, error, loading, reload } = useApi(() => api.get<Page<Evidence>>("/evidence", { q: query, evidence_type: type, limit: 20, offset }), [query, type, offset]);
  return (
    <>
      <PageHeader title="Evidence Viewer" subtitle="Every excerpt preserved with its URL / document page and publication vs. retrieval time." />
      <Card>
        <form className="filters" onSubmit={(e) => { e.preventDefault(); setOffset(0); setQuery(q); }}>
          <label className="field">Search text<input value={q} onChange={(e) => setQ(e.target.value)} /></label>
          <label className="field">Type<select value={type} onChange={(e) => { setType(e.target.value); setOffset(0); }}><option value="">All</option>{["post", "page", "document", "manual"].map((t) => <option key={t}>{t}</option>)}</select></label>
          <button className="btn">Search</button>
        </form>
        <ErrorBox error={error} onRetry={reload} />
        {loading && !data ? <Loading /> : data && (data.items.length === 0 ? <Empty>No evidence found</Empty> : data.items.map((e) => (
          <div key={e.id} className="stack" style={{ marginBottom: 18 }}>
            <div className="row gap-s small">
              <span className="badge neutral">{e.evidence_type}</span>
              {e.opportunity_id && <Link to={`/opportunities/${e.opportunity_id}`}>Opportunity #{e.opportunity_id}</Link>}
              {e.organisation_id && <Link to={`/organisations/${e.organisation_id}`}>Org #{e.organisation_id}</Link>}
              {e.page_reference && <span className="badge info">{e.page_reference}</span>}
              {e.document_name && <span className="muted">{e.document_name}</span>}
              <ExtLink href={e.url} />
              <span className="muted">published {fmtDate(e.published_at)} · retrieved {fmtDate(e.retrieved_at, true)}</span>
            </div>
            <div className="excerpt">{e.excerpt}</div>
          </div>
        )))}
        {data && <Pager total={data.total} limit={20} offset={offset} onChange={setOffset} />}
      </Card>
    </>
  );
}
