import { useState } from "react";
import { Link } from "react-router-dom";
import { CalendarClock, Copy, KanbanSquare, MessageSquareReply, PhoneCall, Send } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorState, Ext, Field, Input, Modal, Msg, PageHeader, Select, Spinner, Textarea } from "../components/ui";
import { api } from "../lib/api";
import { useAction, useQuery } from "../lib/hooks";
import { INDUSTRY, date } from "../lib/format";
import type { CompanyCard, Outreach as OutreachT } from "../lib/types";

interface Item extends CompanyCard {
  channel: string;  // b2b | social_commerce — Outreach is shared between both pipelines
  contacts: { kind: string; value: string; official: boolean; source_url: string }[];
  outreach: OutreachT; last_activity: { kind: string; summary: string; at: string } | null; deal_stage: string | null;
}
type Dialog = { kind: "contacted" | "reply" | "follow"; item: Item } | null;

export default function Outreach() {
  const q = useQuery(() => api.get<Item[]>("/outreach"), []);
  const act = useAction();
  const [dlg, setDlg] = useState<Dialog>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const copy = async (it: Item) => { await navigator.clipboard?.writeText(it.outreach.message); setCopied(it.id); setTimeout(() => setCopied(null), 1500); };
  const toPipeline = async (it: Item) => { if (await act.run(() => api.post(`/companies/${it.id}/to-pipeline`), `${it.name} is in the Sales Pipeline`)) q.reload(); };
  return (
    <>
      <PageHeader title="Outreach" description="Businesses you approved. IOI never sends anything — copy the message, contact them yourself, then log what happened." />
      <ErrorState error={q.error} onRetry={q.reload} />
      <Msg msg={act.msg} />
      {!q.data ? <Spinner /> : q.data.length === 0 ? (
        <Empty icon={<Send className="h-6 w-6" />} title="No approved prospects yet" action={<Link to="/prospects"><Button variant="primary">Review prospects</Button></Link>}>
          Open a prospect and click <strong>Approve for Outreach</strong> once you're happy with the message.
        </Empty>
      ) : (
        <div className="space-y-4">
          {q.data.map((it) => {
            const due = it.next_follow_up_at && new Date(it.next_follow_up_at + "Z") <= new Date();
            return (
              <Card key={it.id}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <Link to={`/prospects/${it.id}`} className="text-base font-semibold text-fg">{it.name}</Link>
                    <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
                      {it.channel === "social_commerce"
                        ? <Badge tone="brand" title="Came from Social Commerce discovery">Social seller</Badge>
                        : <Badge tone="brand">{INDUSTRY[it.industry ?? ""]}</Badge>}
                      {it.offer && <Badge>{it.offer}</Badge>}
                      {it.deal_stage && <Badge tone="info">Pipeline: {it.deal_stage.replace(/_/g, " ")}</Badge>}
                      {it.next_follow_up_at && <Badge tone={due ? "warn" : "neutral"}><CalendarClock className="h-3 w-3" />Follow up {date(it.next_follow_up_at)}</Badge>}
                    </div>
                  </div>
                  <div className="text-right text-sm text-subtle">{it.last_activity ? <>{it.last_activity.summary}<br />{date(it.last_activity.at, true)}</> : "Not contacted yet"}</div>
                </div>
                <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_18rem]">
                  <div>
                    <p className="mb-1 text-sm"><span className="font-medium">Contact: </span>{it.outreach.contact_role}</p>
                    <pre className="whitespace-pre-wrap rounded-lg bg-muted p-3 font-sans text-sm">{it.outreach.message}</pre>
                  </div>
                  <div className="space-y-3 text-sm">
                    <div>
                      <p className="font-medium">Public contact routes</p>
                      <ul className="mt-1 space-y-1">
                        {it.contacts.map((x) => (
                          <li key={x.value}>
                            {x.kind === "phone" ? <a href={`tel:${x.value.replace(/\s/g, "")}`}>{x.value}</a> : x.kind === "email" ? <a href={`mailto:${x.value}`}>{x.value}</a> : <Ext href={x.value}>Contact form</Ext>}
                            <span className="text-xs text-subtle"> · {x.official ? "their website" : "directory"}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    {it.outreach.questions.length > 0 && <div><p className="font-medium">Ask them</p><ol className="mt-1 list-decimal pl-5 text-subtle">{it.outreach.questions.slice(0, 4).map((x) => <li key={x}>{x}</li>)}</ol></div>}
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => copy(it)}><Copy className="h-4 w-4" />{copied === it.id ? "Copied" : "Copy message"}</Button>
                  <Button size="sm" variant="primary" onClick={() => setDlg({ kind: "contacted", item: it })}><PhoneCall className="h-4 w-4" />Mark as contacted</Button>
                  <Button size="sm" onClick={() => setDlg({ kind: "reply", item: it })}><MessageSquareReply className="h-4 w-4" />Record reply</Button>
                  <Button size="sm" onClick={() => setDlg({ kind: "follow", item: it })}><CalendarClock className="h-4 w-4" />Schedule follow-up</Button>
                  {!it.deal_stage && <Button size="sm" variant="ghost" onClick={() => toPipeline(it)}><KanbanSquare className="h-4 w-4" />Move to Sales Pipeline</Button>}
                </div>
              </Card>
            );
          })}
        </div>
      )}
      {dlg && <ActionDialog dlg={dlg} onClose={() => setDlg(null)} onDone={() => { setDlg(null); q.reload(); }} />}
    </>
  );
}

function ActionDialog({ dlg, onClose, onDone }: { dlg: NonNullable<Dialog>; onClose: () => void; onDone: () => void }) {
  const act = useAction();
  const [channel, setChannel] = useState("phone");
  const [note, setNote] = useState("");
  const [days, setDays] = useState(3);
  const [interested, setInterested] = useState<string>("yes");
  const [problem, setProblem] = useState("");
  const [when, setWhen] = useState(() => new Date(Date.now() + 2 * 86400000).toISOString().slice(0, 10));
  const id = dlg.item.id;
  const submit = async () => {
    const r = dlg.kind === "contacted"
      ? await act.run(() => api.post(`/companies/${id}/contacted`, { channel, note: note || null, follow_up_days: days || null }))
      : dlg.kind === "reply"
        ? await act.run(() => api.post(`/companies/${id}/reply`, { summary: note, interested: interested === "yes" ? true : interested === "no" ? false : null, buyer_problem: problem || null }))
        : await act.run(() => api.post(`/companies/${id}/follow-up`, { at: `${when}T09:00:00`, note: note || null }));
    if (r) onDone();
  };
  const title = { contacted: "Mark as contacted", reply: "Record their reply", follow: "Schedule a follow-up" }[dlg.kind];
  return (
    <Modal open onClose={onClose} title={`${title} — ${dlg.item.name}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={act.busy} disabled={dlg.kind === "reply" && note.length < 2} onClick={submit}>Save</Button></>}>
      {dlg.kind === "contacted" && <>
        <Field label="How did you contact them?"><Select className="w-full" value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="phone">Phone call</option><option value="whatsapp">WhatsApp</option><option value="email">Email</option><option value="in_person">In person</option><option value="other">Other</option>
        </Select></Field>
        <Field label="Follow up in (days)"><Input type="number" min={0} max={90} value={days} onChange={(e) => setDays(parseInt(e.target.value || "0", 10))} /></Field>
      </>}
      {dlg.kind === "reply" && <>
        <Field label="Are they interested?"><Select className="w-full" value={interested} onChange={(e) => setInterested(e.target.value)}>
          <option value="yes">Yes / want to talk</option><option value="unsure">Not sure yet</option><option value="no">Not interested</option>
        </Select></Field>
        <Field label="Problem they described (optional)" hint="Saved as a buyer-confirmed fact — only write what they actually said.">
          <Input value={problem} onChange={(e) => setProblem(e.target.value)} placeholder="e.g. Service calls are tracked in a notebook" /></Field>
      </>}
      {dlg.kind === "follow" && <Field label="Follow up on"><Input type="date" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>}
      <Field label={dlg.kind === "reply" ? "What they said *" : "Note (optional)"}><Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      <Msg msg={act.msg} />
    </Modal>
  );
}
