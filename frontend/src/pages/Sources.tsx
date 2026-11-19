import { FormEvent, Fragment, useState } from "react";
import { api } from "../api";
import { Card, ErrorBox, ExtLink, Loading, Msg, PageHeader, StatusBadge, fmtDate, useAction, useApi } from "../components/ui";
import type { DiscoveryJob, Page, Source, SourceRun } from "../types";

function SourceRow({ s, onChange, onRuns }: { s: Source; onChange: () => void; onRuns: (id: number) => void }) {
  const act = useAction();
  const [feed, setFeed] = useState(String(s.config.feed_url ?? ""));
  const patch = async (body: Record<string, unknown>, ok: string) => { if (await act.run(() => api.patch(`/sources/${s.id}`, body), ok)) onChange(); };
  const runnable = Boolean(s.connector) && s.connector_status !== "planned";
  return (
    <tr>
      <td className="wrap" style={{ maxWidth: 320 }}>
        <strong>{s.name}</strong>
        <div className="muted xs">{s.category.replace(/_/g, " ")} · {s.access_method}{s.country ? ` · ${s.country}` : ""}{s.region ? ` / ${s.region}` : ""}</div>
        {s.base_url && <div className="xs"><ExtLink href={s.base_url} /></div>}
        {s.coverage && <div className="xs">{s.coverage}</div>}
        {s.terms_notes && <div className="muted xs">Terms: {s.terms_notes}</div>}
        {s.api_auth_requirements && <div className="muted xs">Auth: {s.api_auth_requirements}</div>}
        {s.connector === "rss" && (
          <div className="row gap-s pad-t">
            <input type="url" placeholder="https://… feed URL" value={feed} onChange={(e) => setFeed(e.target.value)} />
            <button className="btn sm" onClick={() => patch({ config: { feed_url: feed } }, "Feed URL saved")}>Save</button>
          </div>
        )}
        <Msg msg={act.msg} />
      </td>
      <td><StatusBadge status={s.connector_status} /></td>
      <td>
        <label className="row gap-s small"><input type="checkbox" disabled={!runnable} checked={s.enabled} onChange={(e) => patch({ enabled: e.target.checked }, e.target.checked ? "Enabled" : "Disabled")} /> enabled</label>
        <label className="row gap-s small"><input type="checkbox" disabled={!runnable || !s.enabled} checked={s.schedule_enabled} onChange={(e) => patch({ schedule_enabled: e.target.checked }, "Schedule updated")} /> scheduled</label>
        {s.collection_frequency_minutes && <div className="muted xs">every {s.collection_frequency_minutes} min · {s.rate_limit_per_minute}/min · max {s.max_items_per_run}</div>}
      </td>
      <td className="small">
        <div>checked {fmtDate(s.last_checked_at, true)}</div>
        <div>success {fmtDate(s.last_success_at, true)}</div>
        {s.failure_status && <div className="bad-text xs wrap">{s.failure_status} ({s.consecutive_failures}×)</div>}
      </td>
      <td>
        <div className="row gap-s">
          {s.connector && <button className="btn sm primary" disabled={!s.enabled || act.busy}
            onClick={async () => { if (await act.run(() => api.post<DiscoveryJob>("/discovery/jobs", { source_keys: [s.key], query_terms: [] }), "Run started — see run history")) setTimeout(onChange, 1500); }}>Run now</button>}
          <button className="btn sm" onClick={() => onRuns(s.id)}>Runs</button>
        </div>
      </td>
    </tr>
  );
}

export default function Sources() {
  const sources = useApi(() => api.get<Source[]>("/sources"));
  const [runsFor, setRunsFor] = useState<number | undefined>();
  const runs = useApi(() => api.get<Page<SourceRun>>("/source-runs", { source_id: runsFor, limit: 30 }), [runsFor]);
  const [openRun, setOpenRun] = useState<number | undefined>();
  const act = useAction();
  const [nf, setNf] = useState({ key: "", name: "", feed_url: "", terms_notes: "" });
  const addFeed = async (e: FormEvent) => {
    e.preventDefault();
    if (await act.run(() => api.post("/sources", { ...nf, terms_notes: nf.terms_notes || null }), "Feed source added (disabled until you enable it)")) { setNf({ key: "", name: "", feed_url: "", terms_notes: "" }); sources.reload(); }
  };
  const groups = ["live", "credential_gated", "manual", "planned"];
  return (
    <>
      <PageHeader title="Sources" subtitle="Global source registry. Only 'live' and configured 'credential gated' sources run automatically; 'planned' sources have no connector and are never presented as live." actions={<button className="btn" onClick={() => { sources.reload(); runs.reload(); }}>Refresh</button>} />
      <ErrorBox error={sources.error} onRetry={sources.reload} />
      {!sources.data ? <Loading /> : groups.map((g) => {
        const rows = sources.data!.filter((s) => s.connector_status === g);
        if (!rows.length) return null;
        return (
          <Card key={g} title={<span className="row gap-s"><StatusBadge status={g} /> {rows.length} source(s)</span>}>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Source</th><th>Status</th><th>Collection</th><th>Health</th><th>Actions</th></tr></thead>
                <tbody>{rows.map((s) => <SourceRow key={s.id} s={s} onChange={() => { sources.reload(); runs.reload(); }} onRuns={setRunsFor} />)}</tbody>
              </table>
            </div>
          </Card>
        );
      })}
      <Card title="Add a permitted RSS/Atom feed">
        <form className="filters" onSubmit={addFeed}>
          <label className="field">Key<input required pattern="[a-z0-9_]{3,60}" value={nf.key} onChange={(e) => setNf({ ...nf, key: e.target.value })} placeholder="n8n_forum" /></label>
          <label className="field">Name<input required value={nf.name} onChange={(e) => setNf({ ...nf, name: e.target.value })} /></label>
          <label className="field">Feed URL<input required type="url" value={nf.feed_url} onChange={(e) => setNf({ ...nf, feed_url: e.target.value })} /></label>
          <label className="field" style={{ flex: 1 }}>Permission / terms note<input value={nf.terms_notes} onChange={(e) => setNf({ ...nf, terms_notes: e.target.value })} /></label>
          <button className="btn">Add feed</button>
        </form>
        <Msg msg={act.msg} />
      </Card>
      <Card title={`Collection logs${runsFor ? ` — source #${runsFor}` : ""}`} actions={runsFor ? <button className="btn sm" onClick={() => setRunsFor(undefined)}>All sources</button> : undefined}>
        <ErrorBox error={runs.error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Run</th><th>Source</th><th>Trigger</th><th>Status</th><th>Fetched</th><th>New</th><th>Dup</th><th>Rejected</th><th>Requests</th><th>Started</th><th /></tr></thead>
            <tbody>
              {runs.data?.items.map((r) => (
                <Fragment key={r.id}>
                  <tr>
                    <td>{r.id}</td>
                    <td>{sources.data?.find((s) => s.id === r.source_id)?.key}</td>
                    <td className="small">{r.trigger}</td>
                    <td><StatusBadge status={r.status} />{r.error_message && <div className="bad-text xs wrap" style={{ maxWidth: 260 }}>{r.error_message}</div>}</td>
                    <td>{r.items_fetched}</td><td>{r.items_new}</td><td>{r.items_duplicate}</td><td>{r.items_rejected}</td><td>{r.requests_made}</td>
                    <td className="small">{fmtDate(r.started_at, true)}</td>
                    <td><button className="btn sm" onClick={() => setOpenRun(openRun === r.id ? undefined : r.id)}>Log</button></td>
                  </tr>
                  {openRun === r.id && <tr><td colSpan={11}><pre>{r.log.join("\n") || "(empty)"}</pre></td></tr>}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
