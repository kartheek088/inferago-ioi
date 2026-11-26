import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, ChevronRight, FileText, Handshake, IndianRupee, KanbanSquare, Lightbulb } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorState, Field, Input, Modal, Msg, PageHeader, Select, Spinner, Stat, Textarea } from "../components/ui";
import { api } from "../lib/api";
import { useAction, useQuery } from "../lib/hooks";
import { date, rupees } from "../lib/format";
import type { Deal, Revenue } from "../lib/types";

interface Data { stages: { key: string; label: string }[]; outcomes: { key: string; label: string }[]; deals: Deal[]; revenue: Revenue; goal: number }

export default function Pipeline() {
  const q = useQuery(() => api.get<Data>("/pipeline"), []);
  const act = useAction();
  const [open, setOpen] = useState<Deal | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  const d = q.data;
  const move = async (deal: Deal, dir: 1 | -1) => {
    if (!d) return;
    const i = d.stages.findIndex((s) => s.key === deal.stage) + dir;
    if (i < 0 || i >= d.stages.length) return;
    if (await act.run(() => api.post(`/deals/${deal.id}/stage`, { stage: d.stages[i].key }))) q.reload();
  };
  return (
    <>
      <PageHeader title="Sales Pipeline" description="Move each opportunity forward. Only payments you record count as collected revenue." />
      <ErrorState error={q.error} onRetry={q.reload} />
      <Msg msg={act.msg} />
      {!d ? <Spinner /> : (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Potential" value={rupees(d.revenue.potential)} hint="Your estimates — not revenue" tone="neutral" icon={<Lightbulb className="h-4 w-4" />} />
            <Stat label="Quoted" value={rupees(d.revenue.quoted)} hint="Proposals sent" tone="info" icon={<FileText className="h-4 w-4" />} />
            <Stat label="Contracted" value={rupees(d.revenue.contracted)} hint={`Outstanding ${rupees(d.revenue.outstanding)}`} tone="brand" icon={<Handshake className="h-4 w-4" />} />
            <Stat label="Collected this month" value={rupees(d.revenue.collected_this_month)} hint={d.goal ? `Goal ${rupees(d.goal)}` : undefined} tone="ok" icon={<IndianRupee className="h-4 w-4" />} />
          </div>
          {d.deals.length === 0 ? (
            <Empty icon={<KanbanSquare className="h-6 w-6" />} title="No opportunities in the pipeline yet" action={<Link to="/outreach"><Button variant="primary">Go to Outreach</Button></Link>}>
              A business enters the pipeline when you log contact with it, or click "Move to Sales Pipeline" in Outreach.
            </Empty>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap gap-1.5" aria-label="Stages summary">
                {d.stages.map((s) => {
                  const n = d.deals.filter((x) => x.stage === s.key && (showClosed || !x.outcome || x.outcome === "follow_up_later")).length;
                  return (
                    <button key={s.key} onClick={() => document.getElementById(`stage-${s.key}`)?.scrollIntoView({ behavior: "smooth", inline: "start", block: "nearest" })}
                      className={`rounded-full border px-2.5 py-1 text-xs ${n ? "border-brand/30 bg-brand-soft font-medium text-brand" : "border-border text-subtle hover:bg-muted"}`}>
                      {s.label}{n ? ` · ${n}` : ""}
                    </button>
                  );
                })}
              </div>
              <label className="mb-3 flex items-center gap-2 text-sm text-subtle"><input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />Show closed outcomes (not interested, lost…)</label>
              <div className="flex gap-3 overflow-x-auto pb-4" aria-label="Pipeline board">
                {d.stages.map((s, i) => {
                  const deals = d.deals.filter((x) => x.stage === s.key && (showClosed || !x.outcome || x.outcome === "follow_up_later"));
                  return (
                    <section key={s.key} id={`stage-${s.key}`} className="w-64 shrink-0 scroll-ml-1 rounded-2xl border border-border/70 bg-muted/50 p-2" aria-label={s.label}>
                      <div className="h-1 rounded-full" style={{ background: `hsl(${215 - i * 12} 70% ${i >= 7 ? 42 : 55}%)` }} aria-hidden />
                      <h2 className="flex items-center justify-between px-2 pb-1 pt-2 text-sm font-semibold">{s.label}
                        <span className="rounded-full bg-surface px-2 text-xs font-medium text-subtle">{deals.length}</span></h2>
                      {deals.some((x) => x.quoted_amount) && <p className="px-2 text-xs tabular-nums text-subtle">{rupees(deals.reduce((a, x) => a + (x.quoted_amount ?? 0), 0))} quoted</p>}
                      <div className="mt-1 space-y-2">
                        {deals.map((x) => (
                          <article key={x.id} className="rounded-xl border border-border bg-surface p-3 text-sm shadow-sm transition hover:shadow-md">
                            <button className="text-left font-medium hover:text-brand" onClick={() => setOpen(x)}>{x.company}</button>
                            {x.channel === "social_commerce" && <div><Badge tone="brand" title="Came from Social Commerce discovery">Social</Badge></div>}
                            {x.outcome && <div><Badge tone={x.outcome === "follow_up_later" ? "warn" : "bad"}>{d.outcomes.find((o) => o.key === x.outcome)?.label}</Badge>{x.outcome_reason && <span className="ml-1 text-xs text-subtle">{x.outcome_reason}</span>}</div>}
                            <div className="mt-1 text-xs text-subtle">{x.offer ?? "No offer yet"}</div>
                            <div className="mt-1 text-xs tabular-nums">{x.quoted_amount ? `Quoted ${rupees(x.quoted_amount)}` : ""}{x.collected ? ` · Paid ${rupees(x.collected)}` : ""}</div>
                            {x.next_follow_up_at && <div className="mt-1 text-xs text-subtle">Follow up {date(x.next_follow_up_at)}</div>}
                            <div className="mt-2 flex justify-between">
                              <Button size="sm" variant="ghost" disabled={i === 0 || act.busy} onClick={() => move(x, -1)} aria-label={`Move ${x.company} back`}><ChevronLeft className="h-4 w-4" /></Button>
                              <Button size="sm" variant="ghost" onClick={() => setOpen(x)}>Open</Button>
                              <Button size="sm" variant="ghost" disabled={i === d.stages.length - 1 || act.busy} onClick={() => move(x, 1)} aria-label={`Move ${x.company} forward`}><ChevronRight className="h-4 w-4" /></Button>
                            </div>
                          </article>
                        ))}
                      </div>
                    </section>
                  );
                })}
              </div>
            </>
          )}
        </>
      )}
      {open && d && <DealDialog deal={open} data={d} onClose={() => setOpen(null)} onChanged={(x) => { setOpen(x); q.reload(); }} />}
    </>
  );
}

function DealDialog({ deal, data, onClose, onChanged }: { deal: Deal; data: Data; onClose: () => void; onChanged: (d: Deal) => void }) {
  const act = useAction();
  const [f, setF] = useState({ contact_name: deal.contact_name ?? "", confirmed_requirement: deal.confirmed_requirement ?? "", offer: deal.offer ?? "",
    potential_amount: deal.potential_amount?.toString() ?? "", delivery_status: deal.delivery_status ?? "", expected_payment_date: deal.expected_payment_date ?? "",
    next_follow_up_at: deal.next_follow_up_at?.slice(0, 10) ?? "", notes: deal.notes ?? "" });
  const [prop, setProp] = useState({ title: deal.offer ?? "", amount: "", scope: "" });
  const [pay, setPay] = useState({ amount: "", kind: "advance", received_on: new Date().toISOString().slice(0, 10), reference: "" });
  const [reason, setReason] = useState(deal.outcome_reason ?? "");
  const done = (r: Deal | undefined) => r && onChanged(r);
  const save = async () => done(await act.run(() => api.patch<Deal>(`/deals/${deal.id}`, {
    ...f, potential_amount: f.potential_amount ? parseInt(f.potential_amount, 10) : null, expected_payment_date: f.expected_payment_date || null,
    next_follow_up_at: f.next_follow_up_at ? `${f.next_follow_up_at}T09:00:00` : null }), "Saved"));
  return (
    <Modal open onClose={onClose} title={deal.company}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Stage"><Select className="w-full" value={deal.stage} onChange={async (e) => done(await act.run(() => api.post<Deal>(`/deals/${deal.id}/stage`, { stage: e.target.value }), "Stage updated"))}>
          {data.stages.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</Select></Field>
        <Field label="Outcome"><Select className="w-full" value={deal.outcome ?? ""} onChange={async (e) => done(await act.run(() => api.post<Deal>(`/deals/${deal.id}/stage`, { outcome: e.target.value || null, outcome_reason: reason || null }), "Outcome updated"))}>
          <option value="">Open</option>{data.outcomes.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}</Select></Field>
      </div>
      {deal.outcome && deal.outcome !== "follow_up_later" && (
        <div className="flex items-end gap-2">
          <Field label="Why?" hint="Their reason, in a few words — this is how you learn which leads are worth calling"><Input value={reason} maxLength={300}
            placeholder="e.g. a relative maintains the site" onChange={(e) => setReason(e.target.value)} /></Field>
          <Button size="sm" onClick={async () => done(await act.run(() => api.post<Deal>(`/deals/${deal.id}/stage`, { outcome: deal.outcome, outcome_reason: reason || null }), "Reason saved"))}>Save reason</Button>
        </div>
      )}
      <div className="grid grid-cols-3 gap-2 rounded-lg bg-muted p-3 text-sm">
        <div><div className="text-xs text-subtle">Quoted</div>{rupees(deal.quoted_amount)}</div>
        <div><div className="text-xs text-subtle">Collected</div>{rupees(deal.collected)}</div>
        <div><div className="text-xs text-subtle">Outstanding</div>{rupees(deal.outstanding)}</div>
      </div>
      <Field label="Contact person"><Input value={f.contact_name} onChange={(e) => setF({ ...f, contact_name: e.target.value })} /></Field>
      <Field label="Confirmed requirement" hint="What the buyer actually asked for"><Textarea rows={2} value={f.confirmed_requirement} onChange={(e) => setF({ ...f, confirmed_requirement: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Offer"><Input value={f.offer} onChange={(e) => setF({ ...f, offer: e.target.value })} /></Field>
        <Field label="Potential (estimate, ₹)"><Input type="number" min={0} value={f.potential_amount} onChange={(e) => setF({ ...f, potential_amount: e.target.value })} /></Field>
        <Field label="Expected payment"><Input type="date" value={f.expected_payment_date} onChange={(e) => setF({ ...f, expected_payment_date: e.target.value })} /></Field>
        <Field label="Next follow-up"><Input type="date" value={f.next_follow_up_at} onChange={(e) => setF({ ...f, next_follow_up_at: e.target.value })} /></Field>
        <Field label="Delivery status"><Input value={f.delivery_status} onChange={(e) => setF({ ...f, delivery_status: e.target.value })} /></Field>
      </div>
      <Field label="Notes"><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      <Button onClick={save} loading={act.busy}>Save details</Button>

      <Card title="Proposal" className="shadow-none">
        <div className="grid gap-2 sm:grid-cols-2">
          <Input placeholder="Title" value={prop.title} onChange={(e) => setProp({ ...prop, title: e.target.value })} aria-label="Proposal title" />
          <Input type="number" min={1} placeholder="Amount ₹" value={prop.amount} onChange={(e) => setProp({ ...prop, amount: e.target.value })} aria-label="Proposal amount" />
        </div>
        <Textarea className="mt-2" rows={2} placeholder="Scope" value={prop.scope} onChange={(e) => setProp({ ...prop, scope: e.target.value })} />
        <Button className="mt-2" size="sm" disabled={!prop.title || !prop.amount} onClick={async () => done(await act.run(() => api.post<Deal>(`/deals/${deal.id}/proposals`,
          { title: prop.title, amount: parseInt(prop.amount, 10), scope: prop.scope || null, sent: true }), "Proposal recorded as sent"))}>Record proposal sent</Button>
      </Card>

      <Card title="Payments received" className="shadow-none">
        {deal.payments.length > 0 && <ul className="mb-3 space-y-1 text-sm">{deal.payments.map((p) => <li key={p.id}>{date(p.received_on)} · {rupees(p.amount)} · {p.kind}{p.reference ? ` · ${p.reference}` : ""}</li>)}</ul>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Input type="number" min={1} placeholder="Amount ₹" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} aria-label="Payment amount" />
          <Select value={pay.kind} onChange={(e) => setPay({ ...pay, kind: e.target.value })} aria-label="Payment type"><option value="advance">Advance</option><option value="milestone">Milestone</option><option value="final">Final</option></Select>
          <Input type="date" value={pay.received_on} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setPay({ ...pay, received_on: e.target.value })} aria-label="Received on" />
          <Input placeholder="Reference (UPI/bank)" value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} />
        </div>
        <Button className="mt-2" size="sm" variant="success" disabled={!pay.amount} onClick={async () => {
          const r = await act.run(() => api.post<Deal>(`/deals/${deal.id}/payments`, { ...pay, amount: parseInt(pay.amount, 10), reference: pay.reference || null }), "Payment recorded");
          if (r) { setPay({ ...pay, amount: "", reference: "" }); onChanged(r); }
        }}>Record payment received</Button>
      </Card>
      <Msg msg={act.msg} />
    </Modal>
  );
}
