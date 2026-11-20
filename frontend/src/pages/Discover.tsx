import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, ErrorBox, Msg, PageHeader, Pager, StatusBadge, fmtDate, useAction, useApi } from "../components/ui";
import type { DiscoveryJob, Page, Source } from "../types";

interface ImportResult {
  status: string;
  opportunity_id: number | null;
  reason: string | null;
  document?: { file_name: string; pages: number; needs_manual_review: boolean; review_reason: string | null; fields: Record<string, { value: string; page_reference: string | null; method?: string } | null> };
}

export default function Discover() {
  const sources = useApi(() => api.get<Source[]>("/sources"));
  const settings = useApi(() => api.get<{ search_terms: string[] }>("/settings"));
  const [offset, setOffset] = useState(0);
  const jobs = useApi(() => api.get<Page<DiscoveryJob>>("/discovery/jobs", { limit: 10, offset }), [offset]);
  const [selected, setSelected] = useState<string[]>([]);
  const [terms, setTerms] = useState("");
  const run = useAction();
  const imp = useAction();
  const doc = useAction();
  const [url, setUrl] = useState("");
  const [orgName, setOrgName] = useState("");
  const [note, setNote] = useState("");
  const [result, setResult] = useState<ImportResult>();
  const [file, setFile] = useState<File | null>(null);
  const [buyer, setBuyer] = useState("");
  const [docUrl, setDocUrl] = useState("");

  const runnable = (sources.data ?? []).filter((s) => s.connector && s.enabled);

  useEffect(() => {
    if (settings.data && !terms) setTerms(settings.data.search_terms.join("\n"));
  }, [settings.data, terms]);

  // Poll while any job is running.
  useEffect(() => {
    if (!jobs.data?.items.some((j) => j.status === "running")) return;
    const t = setInterval(jobs.reload, 3000);
    return () => clearInterval(t);
  }, [jobs.data, jobs.reload]);

  const start = async () => {
    const query_terms = terms.split("\n").map((t) => t.trim()).filter(Boolean);
    const r = await run.run(() => api.post<DiscoveryJob>("/discovery/jobs", { source_keys: selected, query_terms }), "Discovery started — results appear below as sources finish.");
    if (r) jobs.reload();
  };

  const importUrl = async (e: FormEvent) => {
    e.preventDefault();
    const r = await imp.run(() => api.post<ImportResult>("/imports/url", { url, organisation_name: orgName || null, note: note || null }));
    if (r) {
      setResult(r);
      imp.setMsg({ kind: r.status === "rejected" ? "err" : "ok", text: `${r.status}${r.reason ? ` — ${r.reason}` : ""}` });
    }
  };

  const importDoc = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    if (buyer) fd.append("buyer", buyer);
    if (docUrl) fd.append("source_url", docUrl);
    const r = await doc.run(() => api.upload<ImportResult>("/imports/document", fd));
    if (r) {
      setResult(r);
      doc.setMsg({ kind: "ok", text: `Document ${r.status}${r.document?.needs_manual_review ? " — flagged for manual review" : ""}` });
    }
  };

  return (
    <>
      <PageHeader title="Discover" subtitle="Run live connectors, import a public URL, or analyse a tender document. Nothing is submitted or sent anywhere." />
      <div className="grid grid-2">
        <Card title="Run discovery">
          <ErrorBox error={sources.error} />
          <div className="stack">
            <div>
              <div className="muted small">Live, enabled sources</div>
              {runnable.length === 0 && <div className="muted small">No runnable sources. Enable one on the Sources page.</div>}
              {runnable.map((s) => (
                <label key={s.key} className="row gap-s" style={{ padding: "4px 0" }}>
                  <input type="checkbox" checked={selected.includes(s.key)} onChange={(e) => setSelected((cur) => (e.target.checked ? [...cur, s.key] : cur.filter((k) => k !== s.key)))} />
                  {s.name} <StatusBadge status={s.connector_status} />
                </label>
              ))}
            </div>
            <label className="field">
              Search terms (one per line; used by keyword-capable connectors)
              <textarea value={terms} onChange={(e) => setTerms(e.target.value)} rows={7} />
            </label>
            <button className="btn primary" disabled={!selected.length || run.busy} onClick={start}>
              {run.busy ? "Starting…" : "Run discovery"}
            </button>
            <Msg msg={run.msg} />
          </div>
        </Card>
        <div>
          <Card title="Manual URL import">
            <form className="stack" onSubmit={importUrl}>
              <label className="field">Public URL<input required type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" /></label>
              <label className="field">Organisation name (optional)<input value={orgName} onChange={(e) => setOrgName(e.target.value)} /></label>
              <label className="field">Note (optional)<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
              <div className="muted xs">Fetched once, robots.txt respected, private network addresses blocked.</div>
              <button className="btn" disabled={imp.busy}>{imp.busy ? "Importing…" : "Import & analyse"}</button>
              <Msg msg={imp.msg} />
            </form>
          </Card>
          <Card title="Tender / procurement document (PDF, DOCX)">
            <form className="stack" onSubmit={importDoc}>
              <input type="file" accept=".pdf,.docx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              <label className="field">Buyer (optional)<input value={buyer} onChange={(e) => setBuyer(e.target.value)} /></label>
              <label className="field">Where it was published (optional URL)<input type="url" value={docUrl} onChange={(e) => setDocUrl(e.target.value)} /></label>
              <button className="btn" disabled={!file || doc.busy}>{doc.busy ? "Analysing…" : "Upload & analyse"}</button>
              <Msg msg={doc.msg} />
            </form>
          </Card>
        </div>
      </div>
      {result && (
        <Card title="Import result">
          {result.opportunity_id ? <Link to={`/opportunities/${result.opportunity_id}`}>Open opportunity #{result.opportunity_id} →</Link> : <span className="muted">{result.reason}</span>}
          {result.document && (
            <>
              {result.document.needs_manual_review && <div className="alert warn">{result.document.review_reason}</div>}
              <table className="pad-t">
                <thead><tr><th>Field</th><th>Extracted value</th><th>Page</th></tr></thead>
                <tbody>
                  {Object.entries(result.document.fields).map(([k, v]) => (
                    <tr key={k}>
                      <td className="small">{k.replace(/_/g, " ")}</td>
                      <td className="wrap small">{v ? <>{v.value}{v.method === "ai" && <span className="muted xs"> · AI-located, quote verified</span>}</> : <span className="muted">Not found (not fabricated)</span>}</td>
                      <td className="mono">{v?.page_reference ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Card>
      )}
      <Card title="Search history" actions={<button className="btn sm" onClick={jobs.reload}>Refresh</button>}>
        <ErrorBox error={jobs.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Started</th><th>Sources</th><th>Terms</th><th>Status</th><th>New</th><th>Dup</th><th>Rejected</th><th>Problems</th></tr></thead>
            <tbody>
              {jobs.data?.items.map((j) => (
                <tr key={j.id}>
                  <td>{j.id}</td>
                  <td className="small">{fmtDate(j.created_at, true)}</td>
                  <td className="small">{j.source_keys.join(", ")}</td>
                  <td className="small muted">{j.query_terms.length ? `${j.query_terms.length} term(s)` : "defaults"}</td>
                  <td><StatusBadge status={j.status} /></td>
                  <td>{j.stats.new ?? "—"}</td>
                  <td>{j.stats.duplicate ?? "—"}</td>
                  <td>{j.stats.rejected ?? "—"}</td>
                  <td className="bad-text xs wrap">{j.stats.failed_sources?.map((f) => `${f.source}: ${f.error}`).join("; ") ?? j.stats.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {jobs.data && <Pager total={jobs.data.total} limit={10} offset={offset} onChange={setOffset} />}
      </Card>
    </>
  );
}
