import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft, Ban, Check, CheckCircle2, Circle, CircleAlert, Copy, Eye, FlaskConical,
  MessageSquare, RefreshCw, Send, Sparkles, X,
} from "lucide-react";
import { AgentTrace, AIChip, Classifications } from "../../components/intel";
import {
  Badge, Button, Card, ErrorState, Ext, Field, Input, Modal, Msg, Notice, PageHeader,
  ScoreRing, Select, Spinner, Textarea,
} from "../../components/ui";
import { api } from "../../lib/api";
import { ago, date, EVIDENCE, rupees } from "../../lib/format";
import { useAction, useQuery } from "../../lib/hooks";
import { CATEGORY, COMPLEXITY, GEO, MATURITY, ORDER_CHANNEL, PLATFORM, SETUP, SQUAL, type SellerDetail } from "../../lib/social";

function GateRow({ g }: { g: { label: string; passed: boolean | null; detail: string } }) {
  const Icon = g.passed === true ? CheckCircle2 : g.passed === false ? X : CircleAlert;
  const tone = g.passed === true ? "text-emerald-500" : g.passed === false ? "text-rose-500" : "text-amber-500";
  return (
    <li className="flex gap-2 text-sm">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone}`} aria-hidden />
      <span><strong>{g.label}</strong><span className="block text-subtle">{g.detail}</span></span>
    </li>
  );
}

function ObservationModal({ open, onClose, seller, onSaved }:
{ open: boolean; onClose: () => void; seller: SellerDetail; onSaved: () => void }) {
  const blocked = seller.blocked_accounts[0];
  const [f, setF] = useState({
    platform: blocked?.platform ?? "instagram", notes: "", last_post_at: "", followers: "",
    account_kind: "business", profile_location: "", delivery_area: "", pickup_point: "",
    catalogue_url: "", confirmed_problem: "",
  });
  const { busy, msg, run } = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(f)) if (String(v).trim()) body[k] = k === "followers" ? Number(v) : v;
    const r = await run(() => api.post(`/social/sellers/${seller.id}/observation`, body), "Saved");
    if (r) { onSaved(); onClose(); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Record what you saw"
      footer={<><Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={save}>Save</Button></>}>
      <div className="space-y-3">
        <Notice kind="info">
          IOI cannot read Instagram or Facebook profiles — they are only served to signed-in visitors. Open the
          profile yourself and type what it actually says. IOI runs the same rules over your words.
        </Notice>
        {blocked && <p className="text-sm">
          <Ext href={blocked.url}>Open {blocked.label} @{blocked.handle}</Ext>
        </p>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Which profile">
            <Select value={f.platform} onChange={set("platform")}>
              {Object.entries(PLATFORM).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="Account type">
            <Select value={f.account_kind} onChange={set("account_kind")}>
              <option value="business">Business account</option>
              <option value="creator">Creator account</option>
              <option value="page">Page</option>
              <option value="personal">Personal account</option>
            </Select>
          </Field>
        </div>
        <Field label="Their bio and recent posts, in their words"
          hint="Paste or type what the profile says. Order complexity and signals are detected from this.">
          <Textarea rows={5} value={f.notes} onChange={set("notes")}
            placeholder="Custom cakes made to order. 50% advance to confirm. Order 3 days in advance. Sold out this week." />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Date of their latest post" hint="This is what decides whether they count as active.">
            <Input type="date" value={f.last_post_at} onChange={set("last_post_at")} />
          </Field>
          <Field label="Followers" hint="Recorded for context. Never used in scoring.">
            <Input type="number" min={0} value={f.followers} onChange={set("followers")} />
          </Field>
          <Field label="Location in their profile"><Input value={f.profile_location} onChange={set("profile_location")} placeholder="Adyar, Chennai 600020" /></Field>
          <Field label="Delivery area they state"><Input value={f.delivery_area} onChange={set("delivery_area")} placeholder="Delivers across Chennai" /></Field>
          <Field label="Pickup point they state"><Input value={f.pickup_point} onChange={set("pickup_point")} /></Field>
          <Field label="Catalogue / order link in their bio"><Input value={f.catalogue_url} onChange={set("catalogue_url")} /></Field>
        </div>
        <Field label="A problem they told you about" hint="Only if they said it themselves. This is what makes a lead S0.">
          <Textarea rows={2} value={f.confirmed_problem} onChange={set("confirmed_problem")} />
        </Field>
        <Msg msg={msg} />
      </div>
    </Modal>
  );
}

export default function SocialLeadDetail() {
  const { id } = useParams();
  const q = useQuery(() => api.get<SellerDetail>(`/social/sellers/${id}`), [id]);
  const { busy, msg, run } = useAction();
  const [observe, setObserve] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [replyOpen, setReplyOpen] = useState(false);
  const [reply, setReply] = useState({ summary: "", interested: "yes", confirmed_problem: "" });

  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Spinner label="Loading seller…" />;
  const c = q.data;
  const geo = GEO[c.geo_confidence] ?? GEO.unclear;
  const sol = c.solution ?? {};
  const agent = c.dossier?.agent;
  const act = (fn: () => Promise<unknown>, ok?: string) => run(fn, ok).then(() => q.reload());

  return (
    <div className="space-y-5">
      <Link to="/social-commerce/leads" className="inline-flex items-center gap-1 text-sm text-subtle no-underline">
        <ArrowLeft className="h-4 w-4" />All social sellers
      </Link>

      <PageHeader title={c.name}
        description={<span className="flex flex-wrap items-center gap-1.5">
          <Badge tone={SQUAL[c.qualification]?.tone}>{c.qualification} · {c.qualification_label}</Badge>
          <Badge tone={geo.tone}>{geo.label}{c.locality ? ` · ${c.locality}` : ""}</Badge>
          {c.category && <Badge>{CATEGORY[c.category]}</Badge>}
          <Badge>{SETUP[c.sales_setup]}</Badge>
          {c.maturity && <Badge tone={MATURITY[c.maturity]?.tone}>{MATURITY[c.maturity]?.label}</Badge>}
          {c.is_test && <Badge tone="warn"><FlaskConical className="mr-1 inline h-3 w-3" />TEST DATA</Badge>}
        </span>}
        actions={<div className="flex flex-wrap gap-2">
          {c.blocked_accounts.length > 0 && (
            <Button size="sm" variant="primary" onClick={() => setObserve(true)}>
              <Eye className="h-4 w-4" />Record what you saw
            </Button>)}
          {c.readable_pages.length > 0 && (
            <Button size="sm" loading={busy} onClick={() => act(() => api.post(`/social/sellers/${c.id}/research`), "Researched")}>
              <RefreshCw className="h-4 w-4" />Read their pages
            </Button>)}
          <Button size="sm" loading={busy} onClick={() => act(() => api.post(`/social/sellers/${c.id}/ai-research`), "AI research done")}>
            <Sparkles className="h-4 w-4" />AI research
          </Button>
        </div>} />

      <Msg msg={msg} />

      {c.research_error && <Notice kind="warn">{c.research_error}</Notice>}
      {c.disqualifier && <Notice kind="err">Blocker you recorded: {c.disqualifier}</Notice>}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Why this seller" description="Every answer comes from stored evidence.">
            <dl className="space-y-3 text-sm">
              {(c.dossier?.answers ?? []).map((a) => (
                <div key={a.q}>
                  <dt className="font-medium">{a.q}</dt>
                  <dd className="text-subtle">{a.a}</dd>
                </div>
              ))}
            </dl>
          </Card>

          <Card title="Mandatory checks" description="A score never bypasses a check.">
            <ul className="space-y-2">{c.gates.map((g) => <GateRow key={g.key} g={g} />)}</ul>
          </Card>

          <Card title="Where they operate" description={c.weak_evidence_note}>
            <p className="text-sm"><Badge tone={geo.tone}>{geo.label}</Badge></p>
            <p className="mt-2 text-sm text-subtle">{c.geo_reason}</p>
            {c.geo_basis && <p className="mt-1 text-xs text-subtle">Basis: {c.geo_bases[c.geo_basis] ?? c.geo_basis}</p>}
            {c.geo_excerpt && <blockquote className="mt-2 border-l-2 border-border pl-3 text-xs text-subtle">{c.geo_excerpt}</blockquote>}
            {c.geo_evidence_url && <p className="mt-1 text-xs"><Ext href={c.geo_evidence_url}>Source</Ext></p>}
          </Card>

          <Card title="How they sell today"
            description={c.sales_setup_reason ?? undefined}>
            <div className="space-y-3 text-sm">
              <p><Badge>{SETUP[c.sales_setup]}</Badge></p>
              {c.order_channels.length > 0 && (
                <p className="text-subtle">Orders arrive via {c.order_channels.map((x) => ORDER_CHANNEL[x] ?? x).join(", ")}.</p>
              )}
              {c.known_tools.length > 0 && (
                <Notice kind="info">They already use {c.known_tools.join(", ")}. Check that before offering anything new.</Notice>
              )}
              {c.workflow_gaps.length > 0 && (
                <ul className="list-disc space-y-1 pl-5 text-subtle">
                  {c.workflow_gaps.map((g) => <li key={g}>{g}</li>)}
                </ul>
              )}
            </div>
          </Card>

          <Card title="Order complexity"
            description="Indicators that a workflow tool might be relevant — not proof of a problem.">
            {c.complexity.length === 0 ? <p className="text-sm text-subtle">Nothing found yet.</p> : (
              <div className="flex flex-wrap gap-1.5">
                {c.complexity.map((x) => <Badge key={x.key} tone="brand">{x.label}</Badge>)}
              </div>
            )}
            <p className="mt-2 text-xs text-subtle">{COMPLEXITY[c.complexity_level]?.label}</p>
          </Card>

          <Card title="Public activity"
            description="A post shows the account is active. It is not proof of sales, order volume or revenue.">
            {c.activity.length === 0 ? <p className="text-sm text-subtle">No public activity recorded yet.</p> : (
              <ul className="divide-y divide-border">
                {c.activity.map((a) => (
                  <li key={a.id} className="py-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{a.label}</span>
                      <Badge tone={a.indicator_class === "demand_indicator" ? "warn" : "info"}>
                        {a.indicator_class === "demand_indicator" ? "demand indicator" : "activity"}
                      </Badge>
                      {a.published_at ? <span className="text-xs text-subtle">{date(a.published_at)}</span>
                        : <Badge>no date on the source</Badge>}
                      {a.review_status === "confirmed" && <Badge tone="ok">confirmed by you</Badge>}
                      {a.review_status === "rejected" && <Badge tone="bad">rejected</Badge>}
                    </div>
                    {a.excerpt && <blockquote className="mt-1 border-l-2 border-border pl-3 text-xs text-subtle">{a.excerpt}</blockquote>}
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                      <Ext href={a.url}>Source</Ext>
                      {a.review_status === "hypothesis" && (
                        <>
                          <button className="text-emerald-500 underline" disabled={busy}
                            onClick={() => act(() => api.post(`/social/sellers/${c.id}/activity/${a.id}/review`, { review_status: "confirmed" }), "Confirmed")}>
                            Confirm
                          </button>
                          <button className="text-rose-500 underline" disabled={busy}
                            onClick={() => act(() => api.post(`/social/sellers/${c.id}/activity/${a.id}/review`, { review_status: "rejected" }), "Rejected")}>
                            Reject
                          </button>
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="What Inferago could offer"
            description={sol.level_label ?? undefined}>
            {!sol.offer ? <p className="text-sm text-subtle">{sol.why ?? "Not enough is known yet."}</p> : (
              <div className="space-y-3 text-sm">
                <p className="font-medium">{sol.offer}</p>
                <p className="text-subtle">{sol.improvement}</p>
                <p className="text-xs text-subtle">{sol.why}</p>
                {sol.scope?.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-5 text-subtle">{sol.scope.map((s) => <li key={s}>{s}</li>)}</ul>
                )}
                {sol.delivery_note && <Notice kind="info">{sol.delivery_note}</Notice>}
                {sol.confirm_with_buyer?.length > 0 && (
                  <div>
                    <p className="font-medium">Confirm with them first</p>
                    <ul className="list-disc space-y-0.5 pl-5 text-subtle">
                      {sol.confirm_with_buyer.map((s) => <li key={s}>{s}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </Card>

          {sol.existing_software && (
            <Card title="Software they could use instead"
              description={sol.existing_software.advice}>
              <ul className="divide-y divide-border text-sm">
                {sol.existing_software.options.map((o) => (
                  <li key={o.name} className="py-2">
                    <p className="font-medium"><Ext href={o.url}>{o.name}</Ext> <span className="text-xs font-normal text-subtle">· {o.category}</span></p>
                    <p className="text-subtle">{o.solves}</p>
                    <p className="text-xs text-subtle">Downside: {o.burden}</p>
                    <p className="text-xs text-brand">Our role: {o.inferago_role}</p>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-subtle">{sol.existing_software.note}</p>
            </Card>
          )}

          <Card title="Evidence">
            {c.facts.length === 0 ? <p className="text-sm text-subtle">Nothing recorded yet.</p> : (
              <ul className="divide-y divide-border text-sm">
                {c.facts.map((f) => (
                  <li key={f.id} className="py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={EVIDENCE[f.state]?.tone}>{EVIDENCE[f.state]?.label ?? f.state}</Badge>
                      <span>{f.statement}</span>
                    </div>
                    {f.excerpt && <blockquote className="mt-1 border-l-2 border-border pl-3 text-xs text-subtle">{f.excerpt}</blockquote>}
                    <p className="mt-1 text-xs text-subtle">
                      {f.source_name}{f.source_url ? " · " : ""}{f.source_url && <Ext href={f.source_url}>source</Ext>}
                      {f.detected_by === "ai" ? " · found by AI, quote checked" : ""}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="AI research trace" description={<AIChip compact />}>
            {agent && (
              <div className="mb-3 space-y-1 text-sm">
                {agent.summary && <p className="text-subtle">{agent.summary}</p>}
                <p className="text-xs text-subtle">
                  {agent.model_calls} AI calls · {agent.tool_calls} tool calls
                  {agent.rejected_claims ? ` · ${agent.rejected_claims} claim(s) rejected` : ""}
                  {agent.cost_usd ? ` · about $${agent.cost_usd.toFixed(4)}` : ""}
                  {agent.stop_reason ? ` · ${agent.stop_reason}` : ""}
                </p>
                {agent.open_questions?.length > 0 && (
                  <ul className="list-disc pl-5 text-xs text-subtle">{agent.open_questions.map((x) => <li key={x}>{x}</li>)}</ul>
                )}
              </div>
            )}
            <AgentTrace events={c.agent_events} empty="No AI research has run for this seller yet." />
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="Score" description="Ranks within a category. Never a chance of winning the work.">
            <div className="flex items-center gap-3">
              <ScoreRing value={c.score} size={64} />
              <div className="text-sm text-subtle">{c.score} / 100</div>
            </div>
            <ul className="mt-3 space-y-1 text-xs">
              {c.score_breakdown.map((p) => (
                <li key={p.key} className="flex justify-between gap-2">
                  <span className="text-subtle" title={p.why}>{p.label}</span>
                  <span className="tabular-nums">{p.points}/{p.max}</span>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="Read of the business">
            <Classifications c={c} />
            {c.maturity && (
              <div className="mt-3">
                <Badge tone={MATURITY[c.maturity]?.tone}>{MATURITY[c.maturity]?.label}</Badge>
                <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-subtle">
                  {c.maturity_reasons.map((r) => <li key={r}>{r}</li>)}
                </ul>
                <p className="mt-1 text-xs text-subtle">{c.maturity_note}</p>
              </div>
            )}
          </Card>

          <Card title="Accounts">
            {c.accounts.length === 0 ? <p className="text-sm text-subtle">None recorded.</p> : (
              <ul className="space-y-2 text-sm">
                {c.accounts.map((a) => (
                  <li key={a.id}>
                    <p className="flex flex-wrap items-center gap-1.5">
                      <Ext href={a.url}>{a.label} @{a.handle}</Ext>
                      {a.is_primary && <Badge tone="brand">primary</Badge>}
                      {!a.readable_by_ioi && <Badge tone="warn">you must open this</Badge>}
                    </p>
                    {a.followers != null && (
                      <p className="text-xs text-subtle" title={a.followers_note}>
                        {a.followers.toLocaleString("en-IN")} followers — not used in scoring
                      </p>
                    )}
                    {a.last_post_at && <p className="text-xs text-subtle">Latest post {date(a.last_post_at)}</p>}
                    {a.catalogue_url && <p className="text-xs"><Ext href={a.catalogue_url}>Catalogue</Ext></p>}
                  </li>
                ))}
              </ul>
            )}
            {c.blocked_accounts.length > 0 && (
              <Notice kind="warn">{c.blocked_accounts[0].why}</Notice>
            )}
          </Card>

          <Card title="How to contact them">
            {c.contacts.length === 0 ? <p className="text-sm text-subtle">No public business contact found yet.</p> : (
              <ul className="space-y-1 text-sm">
                {c.contacts.map((x) => (
                  <li key={x.id} className="flex flex-wrap items-center gap-1.5">
                    <span className="text-subtle">{x.kind}:</span>
                    <span>{x.value}</span>
                    {x.official ? <Badge tone="ok">they published it</Badge> : <Badge>public listing</Badge>}
                    <Ext href={x.source_url}>source</Ext>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-xs text-subtle">{c.outreach.contact_role}</p>
          </Card>

          <Card title="Outreach" description={c.outreach_approved_at
            ? `Approved by ${c.outreach_approved_by} ${ago(c.outreach_approved_at)}` : "Approval is required before contacting."}>
            <Textarea rows={10} value={draft ?? c.outreach.message} onChange={(e) => setDraft(e.target.value)} />
            <p className="mt-2 text-xs text-subtle">Free first offer: {c.outreach.free_offer}</p>
            <p className="mt-1 text-xs text-subtle">Suggested route: {c.outreach.suggested_route}</p>
            <Notice kind="info">{c.outreach.notice}</Notice>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" onClick={() => void navigator.clipboard?.writeText(draft ?? c.outreach.message)}>
                <Copy className="h-4 w-4" />Copy
              </Button>
              {draft != null && draft !== c.outreach.message && (
                <Button size="sm" loading={busy}
                  onClick={() => act(() => api.put(`/social/sellers/${c.id}/draft`, { message: draft }), "Saved — approve it again")}>
                  <Check className="h-4 w-4" />Save draft
                </Button>
              )}
              {c.review_status !== "approved" && (
                <Button size="sm" variant="primary" loading={busy} disabled={!c.sales_ready}
                  title={c.sales_ready ? undefined : "Every mandatory check has to pass first"}
                  onClick={() => act(() => api.post(`/social/sellers/${c.id}/approve`, draft ? { message: draft } : {}), "Approved")}>
                  <CheckCircle2 className="h-4 w-4" />Approve
                </Button>
              )}
              {c.review_status === "approved" && (
                <Button size="sm" loading={busy}
                  onClick={() => act(() => api.post(`/social/sellers/${c.id}/contacted`, { channel: "whatsapp" }), "Logged")}>
                  <Send className="h-4 w-4" />I messaged them
                </Button>
              )}
              <Button size="sm" onClick={() => setReplyOpen(true)}><MessageSquare className="h-4 w-4" />Record a reply</Button>
            </div>
          </Card>

          <Card title="Status">
            <div className="flex flex-wrap gap-2">
              <Button size="sm" loading={busy}
                onClick={() => act(() => api.post(`/social/sellers/${c.id}/review`, { status: "watchlist" }), "Moved to watchlist")}>
                <Circle className="h-4 w-4" />Watchlist
              </Button>
              <Button size="sm" loading={busy}
                onClick={() => act(() => api.post(`/social/sellers/${c.id}/review`, { status: "rejected" }), "Rejected")}>
                <Ban className="h-4 w-4" />Not for us
              </Button>
              {["rejected", "watchlist"].includes(c.review_status) && (
                <Button size="sm" loading={busy}
                  onClick={() => act(() => api.post(`/social/sellers/${c.id}/review`, { status: "new" }), "Restored")}>
                  Restore
                </Button>
              )}
            </div>
            <p className="mt-2 text-xs text-subtle">
              Found via {c.source_key.replace(/_/g, " ")} · <Ext href={c.source_url}>source</Ext> · added {date(c.created_at)}
            </p>
          </Card>

          {c.deal && (
            <Card title="Deal" description={c.deal.stage.replace(/_/g, " ")}>
              <dl className="space-y-1 text-sm">
                <div className="flex justify-between"><dt className="text-subtle">Quoted</dt><dd>{rupees(c.deal.quoted_amount)}</dd></div>
                <div className="flex justify-between"><dt className="text-subtle">Collected</dt><dd>{rupees(c.deal.collected)}</dd></div>
                <div className="flex justify-between"><dt className="text-subtle">Outstanding</dt><dd>{rupees(c.deal.outstanding)}</dd></div>
              </dl>
              <Link to="/pipeline" className="mt-2 inline-block text-xs underline">Open in Sales Pipeline</Link>
            </Card>
          )}

          <Card title="History">
            {c.activities.length === 0 ? <p className="text-sm text-subtle">Nothing logged yet.</p> : (
              <ul className="space-y-1 text-xs">
                {c.activities.map((a) => (
                  <li key={a.id}><span className="text-subtle">{date(a.occurred_at, true)}</span> — {a.summary}</li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      <ObservationModal open={observe} onClose={() => setObserve(false)} seller={c} onSaved={q.reload} />

      <Modal open={replyOpen} onClose={() => setReplyOpen(false)} title="Record their reply"
        footer={<><Button onClick={() => setReplyOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!reply.summary.trim()}
            onClick={() => act(() => api.post(`/social/sellers/${c.id}/reply`, {
              summary: reply.summary,
              interested: reply.interested === "unknown" ? null : reply.interested === "yes",
              ...(reply.confirmed_problem.trim() ? { confirmed_problem: reply.confirmed_problem } : {}),
            }), "Reply recorded").then(() => setReplyOpen(false))}>Save</Button></>}>
        <div className="space-y-3">
          <Field label="What they said"><Textarea rows={3} value={reply.summary}
            onChange={(e) => setReply({ ...reply, summary: e.target.value })} /></Field>
          <Field label="Interested?">
            <Select value={reply.interested} onChange={(e) => setReply({ ...reply, interested: e.target.value })}>
              <option value="yes">Yes</option><option value="no">No</option><option value="unknown">Not clear</option>
            </Select>
          </Field>
          <Field label="A problem they confirmed"
            hint="Their own words. This is what turns a guess into a confirmed need (S0).">
            <Textarea rows={2} value={reply.confirmed_problem}
              onChange={(e) => setReply({ ...reply, confirmed_problem: e.target.value })} />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
