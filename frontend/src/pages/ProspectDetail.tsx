import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Bot, Check, CircleHelp, Copy, Globe, Mail, Phone, RefreshCw, X } from "lucide-react";
import { Badge, Button, Card, ErrorState, Ext, Field, Input, Modal, Msg, Notice, Select, Spinner, Textarea } from "../components/ui";
import { EvidenceTag, LocationBadge, QualBadge } from "../components/prospect";
import { AgentTrace, AIChip, Classifications } from "../components/intel";
import { api } from "../lib/api";
import { useAction, useQuery } from "../lib/hooks";
import { AI_STATUS, FRICTION, INDUSTRY, INTENT, SIGNAL_TYPES, date } from "../lib/format";
import type { CompanyDetail, Fact } from "../lib/types";

export default function ProspectDetail() {
  const { id } = useParams();
  const q = useQuery(() => api.get<CompanyDetail>(`/companies/${id}`), [id]);
  const act = useAction();
  const aiAct = useAction();
  const [draft, setDraft] = useState<string | null>(null);
  const [factOpen, setFactOpen] = useState(false);
  const c = q.data;
  useEffect(() => { if (c && window.location.hash === "#outreach") document.getElementById("outreach")?.scrollIntoView(); }, [c?.id]);
  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} />;
  if (!c) return <Spinner />;

  const run = async (fn: () => Promise<CompanyDetail>, ok: string) => { const r = await act.run(fn, ok); if (r) { q.setData(r); setDraft(null); } };
  const facts = (k: string) => c.facts.filter((f) => f.kind === k);
  const signals = facts("signal");
  const problems = facts("problem");
  const blocked = c.gates.filter((g) => g.passed !== true);

  return (
    <div className="space-y-6">
      <Link to="/prospects" className="inline-flex items-center gap-1 text-sm"><ArrowLeft className="h-4 w-4" />Prospects</Link>

      {/* Overview */}
      <Card>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{c.name}</h1>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge tone="brand">{INDUSTRY[c.industry ?? ""] ?? "Not a target industry"}{c.industry_subtype && c.industry_subtype !== "other" ? ` · ${c.industry_subtype}` : ""}</Badge>
              <LocationBadge c={c} /><QualBadge q={c.qualification} />
              <Badge>{c.review_status === "shortlisted" ? "Ready to review" : c.review_status}</Badge>
            </div>
            {c.address && <p className="mt-3 text-sm">{c.address}</p>}
            <div className="mt-3 flex flex-wrap gap-4 text-sm">
              {c.website && <span className="inline-flex items-center gap-1"><Globe className="h-4 w-4 text-subtle" /><Ext href={c.website} /></span>}
              {c.contacts.map((x) => (
                <span key={`${x.kind}${x.value}`} className="inline-flex items-center gap-1">
                  {x.kind === "email" ? <Mail className="h-4 w-4 text-subtle" /> : x.kind === "phone" ? <Phone className="h-4 w-4 text-subtle" /> : <Globe className="h-4 w-4 text-subtle" />}
                  {x.kind === "email" ? <a href={`mailto:${x.value}`}>{x.value}</a> : x.kind === "phone" ? <a href={`tel:${x.value.replace(/\s/g, "")}`}>{x.value}</a> : <Ext href={x.value}>Contact form</Ext>}
                  <span className="text-xs text-subtle">({x.official ? "their website" : "directory"} · <Ext href={x.source_url}>source</Ext>)</span>
                </span>
              ))}
              {c.contacts.length === 0 && <span className="text-subtle">No public contact found yet</span>}
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2">
            <div className="text-3xl font-semibold tabular-nums">{c.score}<span className="text-sm font-normal text-subtle">/100</span></div>
            <Button size="sm" loading={act.busy} disabled={!c.website} onClick={async () => {
              const r = await act.run(() => api.post<CompanyDetail>(`/companies/${c.id}/research`));
              if (r) { q.setData(r); act.setMsg(r.research_error ? { kind: "err", text: r.research_error } : { kind: "ok", text: "Research finished" }); }
            }}>
              <RefreshCw className="h-4 w-4" />Research further</Button>
          </div>
        </div>
        <Msg msg={act.msg} />
        {c.research_error && <div className="mt-3"><Notice kind="warn">{c.research_error}</Notice></div>}
        <div className="mt-4"><Classifications c={c} /></div>
      </Card>

      {c.dossier.answers && (
        <Card title="Key questions" description="Answered only from stored evidence. Nothing here means the company has agreed to buy.">
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {c.dossier.answers.map((x) => (
              <div key={x.q}><dt className="text-xs font-semibold uppercase tracking-wide text-subtle">{x.q}</dt><dd className="mt-0.5 text-sm">{x.a}</dd></div>
            ))}
          </dl>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Management & decision-makers" description="Only names and roles the company itself publishes, with the quote. Never guessed.">
          {c.people.length === 0 ? <p className="text-sm text-subtle">No management contact is publicly published on the pages read.</p> : (
            <ul className="space-y-3">{c.people.map((p) => (
              <li key={p.id} className="text-sm">
                <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{p.name}</span><Badge>{p.role}</Badge>
                  {p.detected_by === "ai" && <Badge tone="info">found by AI · quote checked</Badge>}</div>
                <blockquote className="mt-1 border-l-2 border-border pl-3 text-xs text-subtle">“{p.excerpt.slice(0, 220)}”</blockquote>
                <div className="mt-1 text-xs"><Ext href={p.source_url}>source</Ext>{p.published_contact && <> · published contact: {p.published_contact}</>} · {date(p.verified_at)}</div>
              </li>
            ))}</ul>
          )}
        </Card>
        <Card title="Public activity & testimonials" description="Testimonials on a company's own site are self-published claims, not independent reviews.">
          {facts("testimonial").length + facts("activity").length === 0 ? <p className="text-sm text-subtle">Nothing found yet.</p> : (
            <ul className="space-y-3">{[...facts("activity"), ...facts("testimonial")].map((f) => <FactRow key={f.id} f={f} />)}</ul>
          )}
        </Card>
      </div>

      <Card title={<span className="flex items-center gap-2"><Bot className="h-4 w-4" />AI research <Badge tone={AI_STATUS[c.ai_status]?.tone ?? "neutral"}>{AI_STATUS[c.ai_status]?.label ?? c.ai_status}</Badge></span>}
        description="A bounded agent reads the company's own pages and records only quote-checked facts. Read-only; it never contacts anyone."
        action={<Button size="sm" loading={aiAct.busy} disabled={!c.website} onClick={async () => {
          const r = await aiAct.run(() => api.post<CompanyDetail>(`/companies/${c.id}/ai-research`));
          if (r) { q.setData(r); aiAct.setMsg({ kind: r.ai_status === "failed" || r.ai_status === "unavailable" ? "err" : "ok", text: r.dossier.agent?.summary ?? `AI research: ${r.ai_status}` }); }
        }}>{c.ai_status === "not_run" ? "Research with AI" : "Retry AI research"}</Button>}>
        <div className="space-y-3">
          <AIChip />
          <Msg msg={aiAct.msg} />
          {c.dossier.agent && (
            <div className="rounded-xl border border-border bg-bg/40 p-3 text-sm">
              {c.dossier.agent.summary && <p>{c.dossier.agent.summary}</p>}
              {c.dossier.agent.open_questions.length > 0 && <ul className="mt-2 list-disc pl-5 text-subtle">{c.dossier.agent.open_questions.map((x) => <li key={x}>{x}</li>)}</ul>}
              <p className="mt-2 text-xs text-subtle">Outcome: {c.dossier.agent.outcome}{c.dossier.agent.stop_reason ? ` (${c.dossier.agent.stop_reason})` : ""} · {c.dossier.agent.model_calls} AI calls ·
                {" "}{c.dossier.agent.tool_calls} tool calls · {c.dossier.agent.tokens} tokens{c.dossier.agent.cost_usd ? ` · $${c.dossier.agent.cost_usd.toFixed(4)}` : ""} · {date(c.dossier.agent.at, true)}</p>
            </div>
          )}
          <details open={c.agent_events.length > 0 && c.agent_events.length < 30}>
            <summary className="cursor-pointer text-sm font-medium">Activity trace ({c.agent_events.length} events)</summary>
            <div className="mt-2 max-h-80 overflow-auto"><AgentTrace events={c.agent_events} /></div>
          </details>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {/* Why selected */}
          <Card title="Why IOI selected this company">
            <ul className="mb-4 list-disc space-y-1 pl-5 text-sm">{c.qualification_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            <h3 className="mb-2 text-sm font-semibold">Mandatory checks</h3>
            <ul className="space-y-1.5 text-sm">
              {c.gates.map((g) => (
                <li key={g.key} className="flex gap-2">
                  {g.passed === true ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" /> : g.passed === false ? <X className="mt-0.5 h-4 w-4 shrink-0 text-bad" /> : <CircleHelp className="mt-0.5 h-4 w-4 shrink-0 text-warn" />}
                  <span><span className="font-medium">{g.label}:</span> <span className="text-subtle">{g.detail}</span></span>
                </li>
              ))}
            </ul>
            <details className="mt-4">
              <summary className="cursor-pointer text-sm font-medium">Score breakdown ({c.score}/100) — ranks prospects within a category only</summary>
              <table className="mt-2 w-full text-sm"><tbody>
                {c.score_breakdown.map((p) => (
                  <tr key={p.key} className="border-t border-border"><td className="py-1.5 pr-2">{p.label}</td><td className="py-1.5 pr-2 tabular-nums">{p.points}/{p.max}</td><td className="py-1.5 text-subtle">{p.why}</td></tr>
                ))}
              </tbody></table>
            </details>
          </Card>

          {/* Workflow */}
          <Card title="Operational workflow" description="Only what sources actually say.">
            {facts("workflow").length === 0 ? <p className="text-sm text-subtle">Nothing confirmed yet. {c.research_level === "directory" ? "Their website hasn't been researched." : "Their website didn't describe it."}</p> : (
              <ul className="space-y-3">{facts("workflow").map((f) => <FactRow key={f.id} f={f} />)}</ul>
            )}
          </Card>

          {/* Problems */}
          <Card title="Potential problems" description="Hypotheses are guesses to check with the buyer — not facts.">
            <ul className="space-y-3">
              {problems.filter((f) => f.state === "buyer_confirmed").map((f) => <FactRow key={f.id} f={f} />)}
              {problems.filter((f) => f.state !== "buyer_confirmed").map((f) => <FactRow key={f.id} f={f} />)}
              {facts("tools").map((f) => <FactRow key={f.id} f={f} />)}
              {problems.length === 0 && <li className="text-sm text-subtle">None recorded.</li>}
            </ul>
          </Card>

          {/* Evidence + buying intent */}
          <Card title="Buying intent & signals" action={<Button size="sm" onClick={() => setFactOpen(true)}>Add what you found</Button>}
            description={<>Buying intent: <strong>{INTENT[c.buying_intent]}</strong>. Detected signals stay unconfirmed until you read the source.</>}>
            {signals.length === 0 ? <p className="text-sm text-subtle">No buying signal found yet.</p> : (
              <ul className="space-y-3">
                {signals.map((f) => (
                  <li key={f.id} className="rounded-lg border border-border p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <strong>{f.label ?? f.statement}</strong>
                      <Badge tone={f.review_status === "confirmed" ? "ok" : f.review_status === "rejected" ? "bad" : "warn"}>{f.review_status === "hypothesis" ? "Not yet confirmed" : f.review_status}</Badge>
                      <span className="text-subtle">{f.published_at ? date(f.published_at) : "date unknown"} · <Ext href={f.source_url}>{f.source_name ?? "source"}</Ext></span>
                    </div>
                    {f.excerpt && <blockquote className="mt-2 border-l-2 border-border pl-3 text-subtle">“{f.excerpt}”</blockquote>}
                    {f.review_status === "hypothesis" && (
                      <div className="mt-2 flex gap-2">
                        <Button size="sm" variant="success" onClick={() => run(() => api.post(`/facts/${f.id}/review`, { decision: "confirmed" }), "Signal confirmed")}>I read it — confirm</Button>
                        <Button size="sm" variant="danger" onClick={() => run(() => api.post(`/facts/${f.id}/review`, { decision: "rejected" }), "Signal rejected")}>Not relevant</Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="All evidence">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem] text-sm">
                <thead><tr className="text-left text-xs text-subtle"><th className="pb-2">Statement</th><th className="pb-2">Evidence</th><th className="pb-2">Reliability</th><th className="pb-2">Date</th><th className="pb-2">Source</th></tr></thead>
                <tbody>
                  {c.locations.map((l, i) => (
                    <tr key={`l${i}`} className="border-t border-border align-top">
                      <td className="py-2 pr-2">Location: {l.reason}{l.excerpt && <div className="text-xs text-subtle">“{l.excerpt.slice(0, 160)}”</div>}</td>
                      <td className="py-2 pr-2"><EvidenceTag state={l.basis === "directory" ? "inferred" : "source_verified"} /></td>
                      <td className="py-2 pr-2">{l.basis === "official_site" ? "high" : l.basis === "owner" ? "high" : "low"}</td>
                      <td className="py-2 pr-2">{date(l.observed_at)}</td><td className="py-2"><Ext href={l.evidence_url} /></td>
                    </tr>
                  ))}
                  {c.facts.filter((f) => f.kind !== "signal").map((f) => (
                    <tr key={f.id} className="border-t border-border align-top">
                      <td className="py-2 pr-2">{f.statement}</td><td className="py-2 pr-2"><EvidenceTag state={f.state} /></td>
                      <td className="py-2 pr-2">{f.state === "unknown" ? "—" : f.reliability}</td><td className="py-2 pr-2">{date(f.published_at ?? f.observed_at)}</td>
                      <td className="py-2">{f.source_url ? <Ext href={f.source_url} /> : <span className="text-subtle">{f.source_name ?? "—"}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Recommended Inferago solution">
            {c.solution.offer ? (
              <div className="space-y-3 text-sm">
                <div><Badge tone="brand">{c.solution.offer}</Badge> <span className="text-xs text-subtle">Step {c.solution.level}: {c.solution.level_label}</span></div>
                <p><span className="font-medium">What we know: </span>{c.solution.known_workflow}</p>
                <p><span className="font-medium">Possible improvement: </span>{c.solution.improvement}</p>
                <div><span className="font-medium">Proposed scope</span><ul className="mt-1 list-disc pl-5">{c.solution.scope.map((s) => <li key={s}>{s}</li>)}</ul></div>
                <p><span className="font-medium">Why this: </span>{c.solution.why}</p>
                <div><span className="font-medium">Confirm with the buyer</span><ul className="mt-1 list-disc pl-5 text-subtle">{c.solution.confirm_with_buyer.map((s) => <li key={s}>{s}</li>)}</ul></div>
                <p className="text-xs text-subtle">No price is suggested until the scope is confirmed.</p>
                {c.solution.existing_software && (
                  <details className="pt-1">
                    <summary className="cursor-pointer font-medium">Software they could use instead (configure before building)</summary>
                    <ul className="mt-2 space-y-2">{c.solution.existing_software.options.map((o) => (
                      <li key={o.name}><Ext href={o.url}>{o.name}</Ext> <span className="text-xs text-subtle">· {o.category}</span>
                        {c.solution.existing_software!.already_mentioned.includes(o.name) && <Badge tone="info" className="ml-1">mentioned on their site</Badge>}
                        <div className="text-xs text-subtle">{o.solves} Burden: {o.burden} <span className="text-fg">Inferago: {o.inferago_role}</span></div></li>
                    ))}</ul>
                    <p className="mt-2 text-xs text-subtle">{c.solution.existing_software.note}</p>
                  </details>
                )}
              </div>
            ) : <p className="text-sm text-subtle">{c.solution.why}</p>}
          </Card>

          <Card title="Sales friction">
            <p className="text-sm font-medium">{FRICTION[c.friction]}</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-subtle">{c.friction_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </Card>

          <Card title="Outreach" className="scroll-mt-6">
            <div id="outreach" className="space-y-3">
              <p className="text-sm"><span className="font-medium">Who to contact: </span>{c.outreach.contact_role}</p>
              <Textarea rows={10} value={draft ?? c.outreach.message} onChange={(e) => setDraft(e.target.value)} aria-label="Outreach message" />
              <div className="flex flex-wrap gap-2">
                {draft !== null && <Button size="sm" onClick={() => run(() => api.put(`/companies/${c.id}/draft`, { message: draft }), "Draft saved")}>Save changes</Button>}
                <Button size="sm" onClick={() => navigator.clipboard?.writeText(draft ?? c.outreach.message)}><Copy className="h-4 w-4" />Copy</Button>
              </div>
              {c.review_status === "approved" ? (
                <Notice kind="ok">Approved by {c.outreach_approved_by} on {date(c.outreach_approved_at)}. Contact them yourself, then log it in <Link to="/outreach">Outreach</Link>.</Notice>
              ) : blocked.length ? (
                <Notice kind="warn">Can't approve yet — still needs: {blocked.map((g) => g.label.toLowerCase()).join(", ")}.</Notice>
              ) : (
                <Button variant="success" className="w-full" loading={act.busy}
                  onClick={() => run(() => api.post(`/companies/${c.id}/approve`, { message: draft ?? undefined }), "Approved for outreach")}>
                  <Check className="h-4 w-4" />Approve for Outreach</Button>
              )}
              <p className="text-xs text-subtle">{c.outreach.notice}</p>
              {c.outreach.questions.length > 0 && <div className="text-sm"><span className="font-medium">Discovery questions</span><ol className="mt-1 list-decimal pl-5 text-subtle">{c.outreach.questions.map((x) => <li key={x}>{x}</li>)}</ol></div>}
            </div>
          </Card>

          <Card title="Status">
            <div className="flex flex-wrap gap-2">
              {c.review_status !== "watchlist" && <Button size="sm" onClick={() => run(() => api.post(`/companies/${c.id}/review/watchlist`, {}), "Moved to watchlist")}>Move to Watchlist</Button>}
              {c.review_status !== "rejected" ? <Button size="sm" variant="danger" onClick={() => run(() => api.post(`/companies/${c.id}/review/reject`, {}), "Rejected")}>Reject</Button>
                : <Button size="sm" onClick={() => run(() => api.post(`/companies/${c.id}/review/restore`, {}), "Restored")}>Restore</Button>}
            </div>
            <EditDetails c={c} onSaved={(r) => q.setData(r)} />
          </Card>

          <Card title="Activity history">
            {c.activities.length === 0 ? <p className="text-sm text-subtle">No activity yet.</p> : (
              <ol className="space-y-2 text-sm">{c.activities.map((a) => (
                <li key={a.id}><span className="text-subtle">{date(a.occurred_at, true)} · </span>{a.summary}</li>
              ))}</ol>
            )}
          </Card>
        </div>
      </div>
      <AddFact open={factOpen} id={c.id} onClose={() => setFactOpen(false)} onSaved={(r) => q.setData(r)} />
    </div>
  );
}

function FactRow({ f }: { f: Fact }) {
  return (
    <li className="text-sm">
      <div className="flex flex-wrap items-center gap-2"><EvidenceTag state={f.state} /><span>{f.statement}</span></div>
      {f.excerpt && <blockquote className="mt-1 border-l-2 border-border pl-3 text-xs text-subtle">“{f.excerpt.slice(0, 260)}”</blockquote>}
      {f.source_url && <div className="mt-1 text-xs"><Ext href={f.source_url}>{f.source_name ?? "source"}</Ext></div>}
    </li>
  );
}

function EditDetails({ c, onSaved }: { c: CompanyDetail; onSaved: (r: CompanyDetail) => void }) {
  const [w, setW] = useState(c.website ?? "");
  const [loc, setLoc] = useState("");
  const [dq, setDq] = useState(c.disqualifier ?? "");
  const [act2, setAct2] = useState("");
  const act = useAction();
  const save = async (body: Record<string, string | boolean>) => { const r = await act.run(() => api.patch<CompanyDetail>(`/companies/${c.id}`, body), "Saved"); if (r) onSaved(r); };
  return (
    <details className="mt-4 text-sm">
      <summary className="cursor-pointer font-medium">Correct details</summary>
      <div className="mt-3 space-y-3">
        <Field label="Official website"><div className="flex gap-2"><Input value={w} onChange={(e) => setW(e.target.value)} /><Button size="sm" onClick={() => save({ website: w })}>Save</Button></div></Field>
        {c.location_confidence === "partial" && (
          <Field label="I checked the Chennai address here (link)" hint="Marks the location as verified by you">
            <div className="flex gap-2"><Input value={loc} onChange={(e) => setLoc(e.target.value)} placeholder="https://…" /><Button size="sm" disabled={!loc} onClick={() => save({ location_evidence_url: loc })}>Verify</Button></div>
          </Field>
        )}
        {c.activity !== "active" && (
          <Field label="I confirmed they're operating now" hint="e.g. 'Called on 23 Nov, they answered' or a link to a recent post">
            <div className="flex gap-2"><Input value={act2} onChange={(e) => setAct2(e.target.value)} /><Button size="sm" disabled={act2.length < 5} onClick={() => save({ activity_evidence: act2 })}>Confirm</Button></div>
          </Field>
        )}
        {c.gates.some((g) => g.key === "scope" && g.passed === null) && (
          <Notice kind="warn">Size check needed: {c.gates.find((g) => g.key === "scope")?.detail}
            <div className="mt-2"><Button size="sm" onClick={() => save({ scope_confirmed: true })}>This is a realistic size for Inferago</Button></div>
          </Notice>
        )}
        <Field label="Known blocker (e.g. requires GST invoice)"><div className="flex gap-2"><Input value={dq} onChange={(e) => setDq(e.target.value)} /><Button size="sm" onClick={() => save({ disqualifier: dq })}>Save</Button></div></Field>
        <Msg msg={act.msg} />
      </div>
    </details>
  );
}

function AddFact({ open, id, onClose, onSaved }: { open: boolean; id: number; onClose: () => void; onSaved: (r: CompanyDetail) => void }) {
  const empty = { kind: "signal", signal_type: "explicit_software_request", statement: "", source_url: "", published_at: "", buyer_confirmed: false };
  const [f, setF] = useState(empty);
  const act = useAction();
  const save = async () => {
    const r = await act.run(() => api.post<CompanyDetail>(`/companies/${id}/facts`, { ...f, source_url: f.source_url || null, published_at: f.published_at || null,
      signal_type: f.kind === "signal" ? f.signal_type : null }), "Saved");
    if (r) { onSaved(r); setF(empty); onClose(); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Add what you found"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={act.busy} disabled={f.statement.length < 5} onClick={save}>Save</Button></>}>
      <Field label="What is it?"><Select className="w-full" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
        <option value="signal">A buying signal (post, news, tender)</option><option value="problem">A problem they have</option>
        <option value="workflow">How they operate</option><option value="tools">Software they use</option><option value="note">Other note</option>
      </Select></Field>
      {f.kind === "signal" && <Field label="Signal type"><Select className="w-full" value={f.signal_type} onChange={(e) => setF({ ...f, signal_type: e.target.value })}>
        {Object.entries(SIGNAL_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>}
      <Field label="What it says" hint="Quote it where possible"><Textarea rows={3} value={f.statement} onChange={(e) => setF({ ...f, statement: e.target.value })} /></Field>
      <Field label={f.kind === "signal" ? "Link (required)" : "Link (optional)"}><Input value={f.source_url} onChange={(e) => setF({ ...f, source_url: e.target.value })} placeholder="https://…" /></Field>
      {f.kind === "signal" && <Field label="Date published"><Input type="date" value={f.published_at} onChange={(e) => setF({ ...f, published_at: e.target.value })} /></Field>}
      {f.kind !== "signal" && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.buyer_confirmed} onChange={(e) => setF({ ...f, buyer_confirmed: e.target.checked })} />The buyer told me this</label>}
      <Msg msg={act.msg} />
    </Modal>
  );
}
