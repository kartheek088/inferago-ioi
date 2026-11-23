import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Activity, BadgeCheck, CheckCircle2, Circle, Clock, Eye, IndianRupee, Instagram, Plus, Search, ShoppingBag, TriangleAlert, Users } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorState, Notice, PageHeader, Spinner, Stat } from "../../components/ui";
import { AddSellerModal } from "./AddSeller";
import { api } from "../../lib/api";
import { ago, rupees } from "../../lib/format";
import { useQuery } from "../../lib/hooks";
import { CATEGORY, PLATFORM, SQUAL, type SocialOverview } from "../../lib/social";

function JobLine({ job }: { job: NonNullable<SocialOverview["active_job"]> }) {
  const run = (job.counters?.run ?? {}) as Record<string, number>;
  return (
    <Card title={`Run #${job.id} — ${job.stage ? job.stage.replace(/_/g, " ") : job.status}`}
      description={job.last_success ?? undefined}
      action={<Link to="/social-commerce/discover"><Button size="sm">Open</Button></Link>}>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-subtle">
        <span>Step {job.stage_index} of {job.stages?.length ?? 7}</span>
        {run.reviewed != null && <span>{run.reviewed} reviewed</span>}
        {run.added != null && <span>{run.added} added</span>}
        {run.researched != null && <span>{run.researched} researched</span>}
        {job.elapsed_s != null && <span>{Math.round(job.elapsed_s)}s elapsed</span>}
      </div>
    </Card>
  );
}

export default function SocialDashboard() {
  const q = useQuery(() => api.get<SocialOverview>("/social/overview"), [], 15000);
  const [adding, setAdding] = useState(false);
  const nav = useNavigate();

  if (!q.data && q.loading) return <Spinner label="Loading Social Commerce…" />;
  if (!q.data) return <ErrorState error={q.error} onRetry={q.reload} />;
  const { stats, revenue, by_platform, by_category, by_qualification, preflight } = q.data;
  const empty = stats.discovered === 0;
  const blocked = preflight.checks.filter((c) => c.enabled && !c.ready);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Social Commerce Intelligence"
        description="Discover growing Chennai businesses selling through Instagram, Facebook and WhatsApp."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => nav("/social-commerce/discover")}>
              <Search className="h-4 w-4" />Find Social Commerce Businesses
            </Button>
            <Button onClick={() => setAdding(true)}><Plus className="h-4 w-4" />Add Business/Profile</Button>
          </div>
        } />

      {q.data.active_job && <JobLine job={q.data.active_job} />}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Businesses discovered" value={stats.discovered} icon={<ShoppingBag className="h-4 w-4" />} />
        <Stat label="Verified active sellers" value={stats.verified_sellers} tone="ok"
          hint="Chennai confirmed from the business itself" icon={<BadgeCheck className="h-4 w-4" />} />
        <Stat label="High-fit prospects" value={stats.high_fit} tone="brand"
          hint="S0 and S1" icon={<Users className="h-4 w-4" />} />
        <Stat label="Recently active" value={stats.recently_active} tone="info"
          hint="Posted in the last 180 days" icon={<Activity className="h-4 w-4" />} />
        <Stat label="Need verification" value={stats.needs_verification} tone="warn"
          hint="A mandatory check is still open" icon={<TriangleAlert className="h-4 w-4" />} />
        <Stat label="Approved outreach" value={stats.approved} tone="ok"
          icon={<CheckCircle2 className="h-4 w-4" />} />
        <Stat label="Qualified conversations" value={stats.qualified_conversations} tone="brand"
          hint="Sellers who replied" icon={<Activity className="h-4 w-4" />} />
        <Stat label="Collected from social clients" value={rupees(revenue.collected_total)} tone="ok"
          hint={`${rupees(revenue.collected_this_month)} this month`} icon={<IndianRupee className="h-4 w-4" />} />
      </div>

      {stats.needs_human_check > 0 && (
        <Notice kind="warn">
          <strong>{stats.needs_human_check} seller(s) need you to look.</strong> Instagram and Facebook serve profiles
          only to signed-in visitors, so IOI never fetches them. Open the profile, then use <em>Record what you saw</em>
          {" "}on the seller page.{" "}
          <Link to="/social-commerce/leads?research_state=needs_human_check" className="underline">Show them</Link>
        </Notice>
      )}

      {blocked.length > 0 && (
        <Card title="Sources that are not available" description="IOI never pretends a source works.">
          <ul className="space-y-2 text-sm">
            {blocked.map((c) => (
              <li key={c.source} className="flex gap-2">
                <Circle className="mt-1 h-3 w-3 shrink-0 text-subtle" />
                <span><strong>{c.source.replace(/_/g, " ")}:</strong> <span className="text-subtle">{c.message}</span></span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {empty ? (
        <Empty icon={<Instagram className="h-6 w-6" />} title="No social sellers yet"
          action={<div className="flex flex-wrap justify-center gap-2">
            <Button variant="primary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />Add Business/Profile</Button>
            <Link to="/social-commerce/discover"><Button><Search className="h-4 w-4" />Open discovery</Button></Link>
          </div>}>
          Paste a public Instagram or Facebook business profile, a WhatsApp business number, a catalogue link or a
          website, and IOI will check what it can read, work out how complicated their orders look, and tell you what
          still needs confirming. Adding a profile by hand always works, even with no search API configured.
        </Empty>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="By qualification" className="lg:col-span-1">
            <ul className="space-y-2 text-sm">
              {(["S0", "S1", "S2", "S3"] as const).map((k) => (
                <li key={k} className="flex items-center justify-between gap-3">
                  <Link to={`/social-commerce/leads?qualification=${k}`} className="flex items-center gap-2 no-underline">
                    <Badge tone={SQUAL[k].tone}>{k}</Badge>
                    <span className="text-subtle" title={SQUAL[k].hint}>{SQUAL[k].label}</span>
                  </Link>
                  <span className="tabular-nums font-medium">{by_qualification[k] ?? 0}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="By platform">
            <ul className="space-y-2 text-sm">
              {Object.entries(by_platform).filter(([, n]) => n > 0).map(([k, n]) => (
                <li key={k} className="flex items-center justify-between gap-3">
                  <Link to={`/social-commerce/leads?platform=${k}`} className="text-subtle no-underline">{PLATFORM[k] ?? k}</Link>
                  <span className="tabular-nums font-medium">{n}</span>
                </li>
              ))}
              {Object.values(by_platform).every((n) => n === 0) && <li className="text-subtle">No accounts recorded yet.</li>}
            </ul>
          </Card>
          <Card title="By what they sell">
            <ul className="space-y-2 text-sm">
              {Object.entries(by_category).filter(([, n]) => n > 0).map(([k, n]) => (
                <li key={k} className="flex items-center justify-between gap-3">
                  <Link to={`/social-commerce/leads?category=${k}`} className="text-subtle no-underline">{CATEGORY[k] ?? k}</Link>
                  <span className="tabular-nums font-medium">{n}</span>
                </li>
              ))}
              {Object.values(by_category).every((n) => n === 0) && <li className="text-subtle">Nothing categorised yet.</li>}
            </ul>
          </Card>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Link to="/social-commerce/leads"><Button><Users className="h-4 w-4" />All sellers</Button></Link>
        <Link to="/social-commerce/leads?tab=ready"><Button><Eye className="h-4 w-4" />Ready to review ({stats.ready_to_review})</Button></Link>
        <Link to="/social-commerce/activity"><Button><Clock className="h-4 w-4" />Activity feed</Button></Link>
      </div>

      {q.data.last_job && !q.data.active_job && (
        <p className="text-xs text-subtle">
          Last run #{q.data.last_job.id} — {q.data.last_job.status}
          {q.data.last_job.finished_at ? ` ${ago(q.data.last_job.finished_at)}` : ""}.
          {q.data.last_job.error ? ` ${q.data.last_job.error}` : ""}
        </p>
      )}

      <AddSellerModal open={adding} onClose={() => setAdding(false)}
        onAdded={(id) => { setAdding(false); nav(`/social-commerce/leads/${id}`); }} />
    </div>
  );
}
