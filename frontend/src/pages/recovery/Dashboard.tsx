import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Globe, RefreshCw, ShieldAlert, TriangleAlert, CheckCircle2, Activity, Star, SlidersHorizontal, Download } from "lucide-react";
import { Button, Card, Empty, ErrorState, Notice, PageHeader, Select, Spinner, Stat, Tabs } from "../../components/ui";
import { api } from "../../lib/api";
import { ago } from "../../lib/format";
import { useQuery } from "../../lib/hooks";
import { ACTIVITY, Dossier, QUAL, STATUS, Tag } from "./Dossier";

export { STATUS } from "./Dossier";

type Scope = { categories: string[] | null; window_days: number };

export type RecoveryOverview = {
  businesses_discovered: number;
  with_own_website: number;
  websites_checked: number;
  checks_recorded: number;
  by_status: Record<string, number>;
  failures_detected: number;
  pending_confirmation: number;
  confirmed: number;
  high_priority: number;
  needs_verification: number;
  migrated: number;
  excluded: number;
  r0: number;
  r1: number;
  active_verified: number;
  alternatives_found: number;
  with_usable_contact: number;
  scope: Scope;
};

export type RecoveryItem = {
  company_id: number;
  name: string;
  locality: string | null;
  business_type: string;
  website: string;
  status: string;
  observed_class: string | null;
  confidence: string;
  reasons: string[];
  checked_at: string;
  qualification: string;
  bucket: string;
  summary: string;
  activity: string;
};

type RunSummary = {
  checked: number; skipped_recent: number; failures_detected: number; confirmed: number;
  network_failures: number; access_restricted: number; errors: number; alternatives_working?: number;
};

type TabId = "high_priority" | "needs_verification" | "migrated" | "excluded";
const nice = (s: string) => s.replace(/_/g, " ");

function Row({ item, onChanged }: { item: RecoveryItem; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-border/70 last:border-0">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex w-full items-start gap-3 px-1 py-3 text-left hover:bg-muted/40">
        {open ? <ChevronDown className="mt-0.5 h-4 w-4 shrink-0" /> : <ChevronRight className="mt-0.5 h-4 w-4 shrink-0" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{item.name}</span>
            {item.locality && <span className="text-xs text-subtle">{item.locality}</span>}
            <Tag map={QUAL} value={item.qualification} />
            <Tag map={STATUS} value={item.status} />
            <Tag map={ACTIVITY} value={item.activity} />
          </div>
          <div className="mt-0.5 truncate text-xs text-subtle">
            {nice(item.business_type)} · {item.summary} · checked {ago(item.checked_at)}
          </div>
        </div>
      </button>
      {open && <div className="pb-4 pl-8 pr-1"><Dossier id={item.company_id} onChanged={onChanged} /></div>}
    </li>
  );
}

function ScopeCard({ onSaved }: { onSaved: () => void }) {
  const q = useQuery(() => api.get<Scope & { available: { industry: string; category: string; count: number }[] }>("/recovery/scope"), []);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [windowDays, setWindowDays] = useState(90);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!q.data) return;
    setPicked(new Set(q.data.categories ?? q.data.available.map((a) => a.category)));
    setWindowDays(q.data.window_days);
  }, [q.data]);
  if (!q.data) return q.error ? <ErrorState error={q.error} onRetry={q.reload} /> : null;
  const avail = q.data.available;
  const all = q.data.categories === null;
  const industries = [...new Set(avail.map((a) => a.industry))];

  async function save() {
    setBusy(true); setErr(null);
    try {
      const everything = avail.every((a) => picked.has(a.category));
      await api.put("/recovery/scope", { categories: everything ? null : [...picked], window_days: windowDays });
      await q.reload();
      onSaved();
      setOpen(false);
    } catch (x) {
      setErr(x instanceof Error ? x.message : String(x));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Who to target"
      description={all ? "Every business type in your two industries. Untick the ones you can't reach or help."
        : `${q.data.categories?.length ?? 0} business types selected · activity window ${q.data.window_days} days`}
      action={<Button size="sm" variant="secondary" onClick={() => setOpen((o) => !o)}><SlidersHorizontal className="h-4 w-4" /> {open ? "Close" : "Change"}</Button>}>
      {open && (
        <div className="space-y-3">
          {industries.map((ind) => (
            <fieldset key={ind}>
              <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-subtle">{nice(ind)}</legend>
              <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                {avail.filter((a) => a.industry === ind).map((a) => (
                  <label key={a.category} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={picked.has(a.category)} onChange={(e) => {
                      const next = new Set(picked);
                      if (e.target.checked) next.add(a.category); else next.delete(a.category);
                      setPicked(next);
                    }} />
                    {nice(a.category)} <span className="text-subtle">({a.count})</span>
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <label className="flex items-center gap-2 text-sm">
            Count activity from the last
            <Select value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))} aria-label="Activity window">
              {[30, 60, 90, 180].map((w) => <option key={w} value={w}>{w} days</option>)}
            </Select>
          </label>
          {err && <Notice kind="err">{err}</Notice>}
          <Button size="sm" onClick={save} loading={busy} disabled={busy}>Save</Button>
        </div>
      )}
    </Card>
  );
}

type Source = {
  source: string; label: string; approved: number; contacted: number; replied: number; not_interested: number;
  proposals: number; won: number; collected: number; reply_rate: number | null; win_rate: number | null;
  lost_reasons: { company: string; outcome: string; reason: string }[];
};

/** Sales feedback: is this channel worth the effort? Counts from what you logged in Outreach and the Sales Pipeline. */
function CompareCard() {
  const q = useQuery(() => api.get<{ sources: Source[]; min_to_compare: number }>("/recovery/compare"), []);
  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} />;
  if (!q.data) return null;
  const { sources, min_to_compare } = q.data;
  const pct = (r: number | null) => (r === null ? "—" : `${Math.round(r * 100)}%`);
  const reasons = sources.find((s) => s.source === "website_recovery")?.lost_reasons ?? [];
  return (
    <Card title="Is it working?"
      description={`From what you log in Outreach and the Sales Pipeline. Rates appear once a source has ${min_to_compare}+ businesses contacted — before that they would mislead.`}>
      {!sources.length ? <p className="text-sm text-subtle">Nothing approved for outreach yet.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead><tr className="text-left text-xs text-subtle">
              <th className="py-1 pr-3 font-medium">Source</th><th className="pr-3 font-medium">Approved</th><th className="pr-3 font-medium">Contacted</th>
              <th className="pr-3 font-medium">Replied</th><th className="pr-3 font-medium">Not interested</th><th className="pr-3 font-medium">Quoted</th>
              <th className="pr-3 font-medium">Won</th><th className="pr-3 font-medium">Reply rate</th><th className="font-medium">Collected</th>
            </tr></thead>
            <tbody>{sources.map((s) => (
              <tr key={s.source} className="border-t border-border/70">
                <td className="py-1.5 pr-3 font-medium">{s.label}</td><td className="pr-3">{s.approved}</td><td className="pr-3">{s.contacted}</td>
                <td className="pr-3">{s.replied}</td><td className="pr-3">{s.not_interested}</td><td className="pr-3">{s.proposals}</td>
                <td className="pr-3">{s.won}</td><td className="pr-3">{pct(s.reply_rate)}</td><td>₹{s.collected.toLocaleString("en-IN")}</td>
              </tr>))}
            </tbody>
          </table>
        </div>
      )}
      {reasons.length > 0 && (
        <div className="mt-3 text-sm">
          <p className="font-medium">Why recovery leads said no</p>
          <ul className="mt-1 list-disc pl-5 text-subtle">{reasons.map((r) => <li key={r.company}>{r.company} — {r.outcome}: {r.reason}</li>)}</ul>
        </div>
      )}
    </Card>
  );
}

export default function RecoveryDashboard() {
  const [tab, setTab] = useState<TabId>("high_priority");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  const ov = useQuery(() => api.get<RecoveryOverview>("/recovery/overview"), []);
  const list = useQuery(() => api.get<{ items: RecoveryItem[] }>("/recovery/companies", { tab }), [tab]);
  const reloadAll = () => { ov.reload(); list.reload(); };
  const [dlErr, setDlErr] = useState<string | null>(null);
  const exportCsv = () => { setDlErr(null); api.download("/recovery/export.csv", "ioi-website-recovery.csv").catch((e) => setDlErr(String(e?.message ?? e))); };

  async function check(force = false) {
    setBusy(true); setRunErr(null);
    try {
      setRun(await api.post<RunSummary>("/recovery/check", { limit: 10, force }));
      await Promise.all([ov.reload(), list.reload()]);
    } catch (e) {
      setRunErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const o = ov.data;
  return (
    <div className="space-y-6">
      <PageHeader title="Website Recovery"
        description="Businesses whose own website looks broken. A broken website is not buying intent — it is a reason to check."
        actions={<>
          <Button onClick={() => check(false)} loading={busy} disabled={busy}><Globe className="h-4 w-4" /> Check next 10 websites</Button>
          <Button variant="secondary" onClick={() => check(true)} disabled={busy}><RefreshCw className="h-4 w-4" /> Recheck now</Button>
        </>} />

      <Notice kind="info">
        One request per site. Failures waiting for their 24-hour recheck are checked first. A lead becomes High-Priority
        only when every gate passes — including that the business is still operating, which you confirm by calling them or
        recording what you see on their own pages. IOI never visits Facebook, Instagram, IndiaMART or Justdial itself.
      </Notice>

      {runErr && <Notice kind="err">{runErr}</Notice>}
      {run && (
        <Notice kind="ok">
          This run: {run.checked} checked, {run.skipped_recent} skipped (checked recently), {run.failures_detected} failures
          ({run.confirmed} confirmed), {run.access_restricted} access restricted, {run.network_failures} network problems,
          {" "}{run.alternatives_working ?? 0} newer sites found, {run.errors} errors.
        </Notice>
      )}

      {ov.error ? <ErrorState error={ov.error} onRetry={ov.reload} /> : !o ? <Spinner /> : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Websites checked" value={o.websites_checked} hint={`${o.with_own_website} of ${o.businesses_discovered} have their own site`} icon={<CheckCircle2 className="h-4 w-4" />} tone="info" />
          <Stat label="Failures confirmed" value={o.confirmed} hint={`${o.pending_confirmation} waiting for the 24 h recheck`} icon={<TriangleAlert className="h-4 w-4" />} tone="bad" />
          <Stat label="Operating — verified" value={o.active_verified} hint={`${o.alternatives_found} moved to a newer site`} icon={<Activity className="h-4 w-4" />} tone="ok" />
          <Stat label="High-Priority" value={o.high_priority} hint={`R1 ${o.r1} · R0 ${o.r0} (confirmed need)`} icon={<Star className="h-4 w-4" />} />
        </div>
      )}

      <ScopeCard onSaved={reloadAll} />

      <Card action={<Button size="sm" variant="secondary" onClick={exportCsv} disabled={!o?.high_priority}
          title="R0/R1 leads with usable business contacts only"><Download className="h-4 w-4" /> Export strong leads</Button>}>
        {dlErr && <Notice kind="err">{dlErr}</Notice>}
        <Tabs<TabId> value={tab} onChange={setTab} tabs={[
          { id: "high_priority", label: "High-Priority", count: o?.high_priority },
          { id: "needs_verification", label: "Needs Verification", count: o?.needs_verification },
          { id: "migrated", label: "Migrated / Storefront", count: o?.migrated },
          { id: "excluded", label: "Excluded", count: o?.excluded },
        ]} />
        <div className="mt-3">
          {list.error ? <ErrorState error={list.error} onRetry={list.reload} />
            : list.loading && !list.data ? <Spinner />
            : !list.data?.items.length ? (
              <Empty icon={<ShieldAlert className="h-5 w-5" />} title="Nothing here yet">
                {tab === "high_priority"
                  ? "No R0/R1 leads yet. A lead needs a confirmed website failure and proof the business is still operating."
                  : "Run a check to fill this list."}
              </Empty>
            ) : (
              <ul>{list.data.items.map((it) => <Row key={it.company_id} item={it} onChanged={reloadAll} />)}</ul>
            )}
        </div>
      </Card>

      <CompareCard />
    </div>
  );
}
