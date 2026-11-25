import { useState } from "react";
import { ChevronDown, ChevronRight, Globe, RefreshCw, ShieldAlert, TriangleAlert, CheckCircle2, ArrowRightLeft } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorState, Ext, Notice, PageHeader, Spinner, Stat, Tabs } from "../../components/ui";
import { api } from "../../lib/api";
import { ago } from "../../lib/format";
import { useQuery } from "../../lib/hooks";

type Tone = "brand" | "ok" | "warn" | "bad" | "info" | "neutral";

export type RecoveryOverview = {
  businesses_discovered: number;
  with_own_website: number;
  websites_checked: number;
  checks_recorded: number;
  by_status: Record<string, number>;
  high_priority: number;
  needs_verification: number;
  migrated: number;
  excluded: number;
};

export type RecoveryItem = {
  company_id: number;
  name: string;
  locality: string | null;
  website: string;
  status: string;
  observed_class: string | null;
  confidence: string;
  reasons: string[];
  final_url: string | null;
  http_status: number | null;
  checked_at: string;
};

type Check = {
  checked_at: string; status: string; observed_class: string | null; confidence: string; dns: string;
  http_status: number | null; final_url: string | null; tls: string | null; error_kind: string | null;
  error_text: string | null; reasons: string[];
};

type RunSummary = {
  checked: number; skipped_recent: number; failures_detected: number; confirmed: number;
  network_failures: number; blocked_by_policy: number; access_restricted: number; errors: number;
};

/** Plain-language labels (brief §15). A 403 or bot challenge never reads as an outage. */
export const STATUS: Record<string, { label: string; tone: Tone }> = {
  healthy: { label: "Website working", tone: "ok" },
  unhealthy_confirmed: { label: "Website failure confirmed", tone: "bad" },
  unhealthy_suspected: { label: "Website may be unavailable", tone: "warn" },
  redirected_to_active_site: { label: "Website redirected", tone: "info" },
  migrated_to_storefront: { label: "New website / storefront found", tone: "info" },
  access_restricted: { label: "Website access restricted", tone: "neutral" },
  network_failure: { label: "Could not verify (network)", tone: "neutral" },
  unknown: { label: "Could not verify", tone: "neutral" },
};

const OBSERVED: Record<string, string> = {
  not_found: "Page not found",
  server_error: "Server error",
  domain_expired_or_unresolved: "Domain not resolving",
  tls_problem: "HTTPS / certificate problem",
  placeholder_or_parked: "Placeholder, parked or suspended page",
};

type TabId = "high_priority" | "needs_verification" | "migrated" | "excluded";

function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, tone: "neutral" as Tone };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

function History({ id }: { id: number }) {
  const q = useQuery(() => api.get<{ checks: Check[] }>(`/recovery/companies/${id}`), [id]);
  if (q.loading && !q.data) return <Spinner />;
  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} />;
  return (
    <ol className="space-y-2 text-sm">
      {q.data?.checks.map((c, i) => (
        <li key={i} className="rounded-lg border border-border/70 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={c.status} />
            {c.observed_class && <span className="text-subtle">{OBSERVED[c.observed_class] ?? c.observed_class}</span>}
            <span className="text-subtle">· {ago(c.checked_at)} · confidence {c.confidence}</span>
          </div>
          <div className="mt-1 text-xs text-subtle">
            DNS {c.dns}{c.http_status != null && <> · HTTP {c.http_status}</>}{c.tls && <> · TLS {c.tls}</>}
            {c.error_kind && <> · {c.error_kind}</>}{c.final_url && <> · ended at {c.final_url}</>}
          </div>
          {c.reasons.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs">{c.reasons.map((r, j) => <li key={j}>{r}</li>)}</ul>}
        </li>
      ))}
    </ol>
  );
}

function Row({ item }: { item: RecoveryItem }) {
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
            <StatusBadge status={item.status} />
          </div>
          <div className="mt-0.5 truncate text-xs text-subtle">
            {item.observed_class ? `${OBSERVED[item.observed_class] ?? item.observed_class} · ` : ""}
            {item.reasons[0] ?? ""} · checked {ago(item.checked_at)}
          </div>
        </div>
      </button>
      {open && (
        <div className="space-y-2 pb-4 pl-8 pr-1">
          <div className="text-sm"><Ext href={item.website}>{item.website}</Ext></div>
          <History id={item.company_id} />
        </div>
      )}
    </li>
  );
}

export default function RecoveryDashboard() {
  const [tab, setTab] = useState<TabId>("high_priority");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  const ov = useQuery(() => api.get<RecoveryOverview>("/recovery/overview"), []);
  const list = useQuery(() => api.get<{ items: RecoveryItem[] }>("/recovery/companies", { tab }), [tab]);

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
        This view checks website health only, one request per site. Sites checked in the last 24 hours are skipped unless you
        press Recheck. A failure is confirmed only when the same failure is seen again at least 24 hours later.
        Business-activity research, marketplace footprint and contact review are not built yet.
      </Notice>

      {runErr && <Notice kind="err">{runErr}</Notice>}
      {run && (
        <Notice kind="ok">
          This run: {run.checked} checked, {run.skipped_recent} skipped (checked recently), {run.failures_detected} failures
          ({run.confirmed} confirmed), {run.access_restricted} access restricted, {run.network_failures} network problems,
          {" "}{run.errors} errors.
        </Notice>
      )}

      {ov.error ? <ErrorState error={ov.error} onRetry={ov.reload} /> : !o ? <Spinner /> : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="B2B businesses" value={o.businesses_discovered} hint={`${o.with_own_website} with their own website`} icon={<Globe className="h-4 w-4" />} />
          <Stat label="Websites checked" value={o.websites_checked} hint={`${o.checks_recorded} checks recorded`} icon={<CheckCircle2 className="h-4 w-4" />} tone="info" />
          <Stat label="Failures confirmed" value={o.high_priority} hint={`${o.by_status.unhealthy_suspected ?? 0} pending confirmation`} icon={<TriangleAlert className="h-4 w-4" />} tone="bad" />
          <Stat label="Moved / restricted" value={o.migrated} hint={`${o.by_status.access_restricted ?? 0} access restricted`} icon={<ArrowRightLeft className="h-4 w-4" />} tone="neutral" />
        </div>
      )}

      <Card>
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
                  ? "No confirmed failures. A failure needs two matching checks at least 24 hours apart."
                  : "Run a check to fill this list."}
              </Empty>
            ) : (
              <ul>{list.data.items.map((it) => <Row key={it.company_id} item={it} />)}</ul>
            )}
        </div>
      </Card>
    </div>
  );
}
