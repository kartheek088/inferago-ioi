import { FormEvent, useMemo, useState } from "react";
import { api } from "../api";
import { Card, Empty, ErrorBox, ExtLink, Loading, Msg, PageHeader, StatusBadge, useAction, useApi } from "../components/ui";
import type { Organisation, Page } from "../types";

interface Graph {
  nodes: { id: string; label: string; kind: string }[];
  edges: { id: number; source: string; target: string; type: string; status: string; confidence: number; evidence_url: string; evidence_excerpt: string }[];
  note: string;
}

const REL_TYPES = ["partner_programme", "implementation_partner", "vendor_of", "customer_of", "contractor_for", "technology_provider", "announced_project", "referral_route", "branch_or_division", "awarded_contract"];

function GraphView({ g }: { g: Graph }) {
  // Simple deterministic radial layout: sources on the left, targets on the right.
  const layout = useMemo(() => {
    const sources = Array.from(new Set(g.edges.map((e) => e.source)));
    const targets = Array.from(new Set(g.edges.map((e) => e.target))).filter((t) => !sources.includes(t));
    const h = Math.max(sources.length, targets.length) * 46 + 40;
    const pos: Record<string, { x: number; y: number }> = {};
    sources.forEach((s, i) => (pos[s] = { x: 170, y: 30 + i * 46 + (h - 40 - sources.length * 46) / 2 }));
    targets.forEach((t, i) => (pos[t] = { x: 590, y: 30 + i * 46 + (h - 40 - targets.length * 46) / 2 }));
    return { pos, h };
  }, [g]);
  const label = (id: string) => g.nodes.find((n) => n.id === id)?.label ?? id;
  const trunc = (s: string) => (s.length > 26 ? `${s.slice(0, 25)}…` : s);
  return (
    <svg className="graph" viewBox={`0 0 760 ${layout.h}`} role="img" aria-label="Relationship graph">
      {g.edges.map((e) => {
        const a = layout.pos[e.source], b = layout.pos[e.target];
        if (!a || !b) return null;
        const color = e.status === "confirmed" ? "var(--good)" : "var(--warn)";
        return (
          <g key={e.id}>
            <line x1={a.x + 6} y1={a.y} x2={b.x - 6} y2={b.y} stroke={color} strokeWidth={e.status === "confirmed" ? 2.2 : 1.4} strokeDasharray={e.status === "confirmed" ? undefined : "5 4"} />
            <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} textAnchor="middle" style={{ fontSize: 10, fill: "var(--muted)" }}>{e.type.replace(/_/g, " ")}</text>
          </g>
        );
      })}
      {Object.entries(layout.pos).map(([id, p]) => {
        const kind = g.nodes.find((n) => n.id === id)?.kind;
        return (
          <g key={id}>
            <circle cx={p.x} cy={p.y} r={6} fill={kind === "organisation" ? "var(--accent)" : kind === "opportunity" ? "var(--good)" : "var(--muted)"} />
            <text x={p.x < 400 ? p.x - 12 : p.x + 12} y={p.y + 4} textAnchor={p.x < 400 ? "end" : "start"}>{trunc(label(id))}</text>
          </g>
        );
      })}
    </svg>
  );
}

export default function Chains() {
  const [hyp, setHyp] = useState(true);
  const g = useApi(() => api.get<Graph>("/chains", { include_hypotheses: hyp }), [hyp]);
  const orgs = useApi(() => api.get<Page<Organisation>>("/organisations", { limit: 500 }));
  const act = useAction();
  const [f, setF] = useState({ source_org_id: "", target_label: "", relationship_type: "partner_programme", evidence_url: "", evidence_excerpt: "", confidence: "0.7", verification_status: "hypothesis" });
  const verify = async (id: number, status: string) => {
    if (await act.run(() => api.patch(`/relationships/organisations/${id}`, { verification_status: status }), `Marked ${status}; related scores updated`)) g.reload();
  };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (await act.run(() => api.post("/relationships/organisations", { ...f, source_org_id: Number(f.source_org_id), confidence: Number(f.confidence) }), "Relationship recorded")) {
      setF({ ...f, target_label: "", evidence_url: "", evidence_excerpt: "" });
      g.reload();
    }
  };
  return (
    <>
      <PageHeader title="Opportunity Chains" subtitle="Evidence-backed relationships between buyers, vendors, partners and projects. Hypotheses (dashed) never score until confirmed." />
      <div className="alert warn small">{g.data?.note ?? "Relationships indicate possible routes; no downstream project is guaranteed."}</div>
      <Msg msg={act.msg} />
      <Card title="Graph" actions={<label className="row gap-s small"><input type="checkbox" checked={hyp} onChange={(e) => setHyp(e.target.checked)} /> show hypotheses</label>}>
        <ErrorBox error={g.error} onRetry={g.reload} />
        {g.loading && !g.data ? <Loading /> : g.data && (g.data.edges.length === 0 ? <Empty>No relationships yet. Research discovers them from official pages; you can also add them below.</Empty> : <GraphView g={g.data} />)}
      </Card>
      {g.data && g.data.edges.length > 0 && (
        <Card title="Relationships & evidence">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Source</th><th>Type</th><th>Target</th><th>Status</th><th>Conf.</th><th>Evidence</th><th>Verify</th></tr></thead>
              <tbody>
                {g.data.edges.map((e) => {
                  const lab = (id: string) => g.data!.nodes.find((n) => n.id === id)?.label ?? id;
                  return (
                    <tr key={e.id}>
                      <td className="small">{lab(e.source)}</td>
                      <td className="small">{e.type.replace(/_/g, " ")}</td>
                      <td className="small">{lab(e.target)}</td>
                      <td><StatusBadge status={e.status} /></td>
                      <td className="mono">{e.confidence}</td>
                      <td className="small wrap" style={{ maxWidth: 360 }}><div className="excerpt xs">{e.evidence_excerpt}</div><ExtLink href={e.evidence_url} /></td>
                      <td>
                        <div className="row gap-s">
                          {e.status !== "confirmed" && <button className="btn sm" onClick={() => verify(e.id, "confirmed")}>Confirm</button>}
                          {e.status !== "rejected" && <button className="btn sm danger" onClick={() => verify(e.id, "rejected")}>Reject</button>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <Card title="Record a relationship (evidence required)">
        <form className="filters" onSubmit={add}>
          <label className="field">Source organisation<select required value={f.source_org_id} onChange={(e) => setF({ ...f, source_org_id: e.target.value })}><option value="">Select…</option>{orgs.data?.items.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
          <label className="field">Type<select value={f.relationship_type} onChange={(e) => setF({ ...f, relationship_type: e.target.value })}>{REL_TYPES.map((t) => <option key={t}>{t}</option>)}</select></label>
          <label className="field">Target (name)<input required value={f.target_label} onChange={(e) => setF({ ...f, target_label: e.target.value })} /></label>
          <label className="field">Evidence URL<input required type="url" value={f.evidence_url} onChange={(e) => setF({ ...f, evidence_url: e.target.value })} /></label>
          <label className="field" style={{ flex: 1, minWidth: 240 }}>Evidence excerpt<input required minLength={10} value={f.evidence_excerpt} onChange={(e) => setF({ ...f, evidence_excerpt: e.target.value })} /></label>
          <label className="field">Confidence<input type="number" min="0" max="1" step="0.05" value={f.confidence} onChange={(e) => setF({ ...f, confidence: e.target.value })} style={{ width: 80 }} /></label>
          <label className="field">Status<select value={f.verification_status} onChange={(e) => setF({ ...f, verification_status: e.target.value })}><option value="hypothesis">hypothesis</option><option value="confirmed">confirmed</option></select></label>
          <button className="btn" disabled={act.busy}>Add</button>
        </form>
      </Card>
    </>
  );
}
