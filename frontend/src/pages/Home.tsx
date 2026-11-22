import { Link } from "react-router-dom";
import { ArrowRight, BellRing, Compass, IndianRupee, Radio, Users } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorState, Spinner, Stat } from "../components/ui";
import { ProspectCard } from "../components/prospect";
import { api } from "../lib/api";
import { useQuery } from "../lib/hooks";
import { ago, greeting, rupees } from "../lib/format";
import type { CompanyCard, Job, Revenue } from "../lib/types";

interface HomeData {
  stats: { qualified: number; new_signals: number; follow_ups_due: number; collected_this_month: number };
  goal: number; best: CompanyCard[]; revenue: Revenue; last_job: Job | null;
  tasks: { leads_to_review: number; signals_to_check: number; follow_ups_due: { company_id: number; name: string; due: string }[];
    replies: { deal_id: number; company_id: number; name: string }[]; proposals: { deal_id: number; company_id: number; name: string; stage: string }[] };
}

export default function Home() {
  const q = useQuery(() => api.get<HomeData>("/home"), [], 20000);
  const d = q.data;
  const running = d?.last_job && ["queued", "running", "stopping"].includes(d.last_job.status);
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">{greeting()}. Here's your sales workspace.</h1>
      <p className="mt-1 text-sm text-subtle">Chennai · Equipment Sales & Service and Wholesale Distribution</p>
      <ErrorState error={q.error} onRetry={q.reload} />
      {!d ? <Spinner /> : (
        <div className="mt-6 space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Qualified prospects" value={d.stats.qualified} hint="Pass every check" icon={<Users className="h-4 w-4" />} />
            <Stat label="New buying signals" value={d.stats.new_signals} hint="Last 7 days" icon={<Radio className="h-4 w-4" />} />
            <Stat label="Follow-ups due" value={d.stats.follow_ups_due} icon={<BellRing className="h-4 w-4" />} />
            <Stat label="Collected this month" value={rupees(d.stats.collected_this_month)} hint={d.goal ? `Goal ${rupees(d.goal)}` : undefined} icon={<IndianRupee className="h-4 w-4" />} />
          </div>

          <Card className="border-brand/30 bg-brand-soft/40">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold">Find Chennai Business Opportunities</h2>
                <p className="mt-1 text-sm text-subtle">Equipment Sales & Service · Wholesale Distribution · Chennai</p>
                <p className="mt-1 text-xs text-subtle">
                  {d.last_job ? <>Last run {ago(d.last_job.finished_at ?? d.last_job.created_at)} — <span className="capitalize">{d.last_job.status}</span></> : "No discovery run yet"}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Link to="/discover"><Button variant="primary" size="lg"><Compass className="h-5 w-5" />{running ? "View progress" : "Start Discovery"}</Button></Link>
                <Link to="/settings?tab=discovery"><Button variant="ghost">Discovery settings</Button></Link>
              </div>
            </div>
          </Card>

          <div className="grid gap-6 lg:grid-cols-3">
            <div className="space-y-3 lg:col-span-2">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold">Today's best prospects</h2>
                <Link to="/prospects" className="text-sm">All prospects <ArrowRight className="inline h-3 w-3" /></Link>
              </div>
              {d.best.length === 0 ? (
                <Empty icon={<Users className="h-6 w-6" />} title="No prospects ready yet">
                  Prospects appear here once a business passes every check (verified Chennai address, relevant work, activity, public contact).
                  Run discovery to find some — IOI never invents leads to fill this space.
                </Empty>
              ) : d.best.map((c) => <ProspectCard key={c.id} c={c} />)}
            </div>
            <div className="space-y-6">
              <Card title="My tasks">
                <ul className="space-y-2 text-sm">
                  <Task to="/prospects" n={d.tasks.leads_to_review} label="leads awaiting review" />
                  <Task to="/prospects?tab=all" n={d.tasks.signals_to_check} label="signals to check" />
                  <Task to="/outreach" n={d.tasks.follow_ups_due.length} label="follow-ups due" />
                  <Task to="/pipeline" n={d.tasks.replies.length} label="replies to act on" />
                  <Task to="/pipeline" n={d.tasks.proposals.length} label="proposals awaiting action" />
                </ul>
              </Card>
              <Card title="Revenue snapshot" description="Only recorded payments count as collected.">
                <dl className="space-y-2 text-sm">
                  <Row k="Quotes sent" v={rupees(d.revenue.quoted)} />
                  <Row k="Advances received" v={rupees(d.revenue.advances_received)} />
                  <Row k="Outstanding" v={rupees(d.revenue.outstanding)} />
                  <Row k="Collected this month" v={<strong>{rupees(d.revenue.collected_this_month)}</strong>} />
                </dl>
                {d.goal > 0 && (
                  <div className="mt-3">
                    <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={d.revenue.collected_this_month} aria-valuemax={d.goal} aria-label="Monthly goal">
                      <div className="h-full bg-ok" style={{ width: `${Math.min(100, (d.revenue.collected_this_month / d.goal) * 100)}%` }} />
                    </div>
                    <p className="mt-1 text-xs text-subtle">{rupees(d.revenue.collected_this_month)} of {rupees(d.goal)} goal</p>
                  </div>
                )}
              </Card>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Task({ to, n, label }: { to: string; n: number; label: string }) {
  return (
    <li className="flex items-center justify-between">
      <Link to={to} className="text-fg">{label[0].toUpperCase() + label.slice(1)}</Link>
      <Badge tone={n ? "brand" : "neutral"}>{n}</Badge>
    </li>
  );
}
function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex justify-between"><dt className="text-subtle">{k}</dt><dd className="tabular-nums">{v}</dd></div>;
}
