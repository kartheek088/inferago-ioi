import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Download, Instagram, Plus } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorState, PageHeader, ScoreRing, Select, Spinner, Tabs } from "../../components/ui";
import { AddSellerModal } from "./AddSeller";
import { api } from "../../lib/api";
import { ago } from "../../lib/format";
import { useQuery } from "../../lib/hooks";
import { CATEGORY, COMPLEXITY, GEO, MATURITY, PLATFORM, SETUP, SQUAL, type SellerCard } from "../../lib/social";

const TABS = [
  { id: "ready", label: "Ready to review" },
  { id: "high_fit", label: "High fit" },
  { id: "watchlist", label: "Watchlist" },
  { id: "verify", label: "Needs verification" },
  { id: "approved", label: "Approved" },
  { id: "excluded", label: "Excluded" },
  { id: "all", label: "All" },
] as const;

type Tab = (typeof TABS)[number]["id"];

export function SellerRow({ c }: { c: SellerCard }) {
  const geo = GEO[c.geo_confidence] ?? GEO.unclear;
  return (
    <Link to={`/social-commerce/leads/${c.id}`} className="block no-underline hover:no-underline">
      <Card className="transition-colors hover:border-brand/40">
        <div className="flex gap-4">
          <div className="hidden shrink-0 sm:block"><ScoreRing value={c.score} /></div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate font-medium text-fg">{c.name}</span>
              <Badge tone={SQUAL[c.qualification]?.tone} title={SQUAL[c.qualification]?.hint}>
                {c.qualification} · {c.qualification_label}
              </Badge>
              {c.sales_ready && <Badge tone="ok">Passes every check</Badge>}
              {c.is_test && <Badge tone="warn">TEST DATA</Badge>}
            </div>
            <p className="mt-1 line-clamp-2 text-sm text-subtle">{c.description ?? "No description yet."}</p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
              <Badge tone={geo.tone}>{geo.label}{c.locality ? ` · ${c.locality}` : ""}</Badge>
              {c.category && <Badge>{CATEGORY[c.category] ?? c.category}</Badge>}
              <Badge>{SETUP[c.sales_setup] ?? c.sales_setup}</Badge>
              {c.maturity && <Badge tone={MATURITY[c.maturity]?.tone}>{MATURITY[c.maturity]?.label}</Badge>}
              <Badge tone={COMPLEXITY[c.complexity_level]?.tone}>
                {c.complexity_count > 0 ? `${c.complexity_count} complexity indicator${c.complexity_count > 1 ? "s" : ""}` : COMPLEXITY[c.complexity_level]?.label}
              </Badge>
              {c.platforms.map((p) => <Badge key={p}>{PLATFORM[p] ?? p}</Badge>)}
              {c.needs_human_check && <Badge tone="warn">You need to look at their profile</Badge>}
              {c.last_activity_at && <span className="text-subtle">Active {ago(c.last_activity_at)}</span>}
              {!c.has_contact && <Badge tone="warn">No contact found</Badge>}
            </div>
            {c.next_action && <p className="mt-2 text-xs text-brand">{c.next_action}</p>}
          </div>
        </div>
      </Card>
    </Link>
  );
}

export default function SocialLeads() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") ?? "ready") as Tab;
  const [adding, setAdding] = useState(false);
  const filters = {
    platform: params.get("platform") ?? "",
    category: params.get("category") ?? "",
    qualification: params.get("qualification") ?? "",
    geo_confidence: params.get("geo_confidence") ?? "",
    maturity: params.get("maturity") ?? "",
    research_state: params.get("research_state") ?? "",
  };
  const counts = useQuery(() => api.get<Record<string, number>>("/social/counts"), []);
  const q = useQuery(() => api.get<{ items: SellerCard[]; total: number }>("/social/sellers", {
    tab, ...filters, limit: 50,
  }), [tab, ...Object.values(filters)]);

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Social sellers" description="Chennai businesses selling through social channels."
        actions={<div className="flex gap-2">
          <a href={api.url(`/social/export.csv?tab=${tab}`)} download><Button size="sm"><Download className="h-4 w-4" />Export</Button></a>
          <Button size="sm" variant="primary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />Add</Button>
        </div>} />

      <Tabs tabs={TABS.map((t) => ({ ...t, count: counts.data?.[t.id] ?? null }))} value={tab}
        onChange={(t) => set("tab", t)} />

      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Select value={filters.platform} onChange={(e) => set("platform", e.target.value)} aria-label="Platform">
            <option value="">All platforms</option>
            {Object.entries(PLATFORM).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            <option value="multi">Multi-platform</option>
          </Select>
          <Select value={filters.category} onChange={(e) => set("category", e.target.value)} aria-label="What they sell">
            <option value="">All categories</option>
            {Object.entries(CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <Select value={filters.geo_confidence} onChange={(e) => set("geo_confidence", e.target.value)} aria-label="Location confidence">
            <option value="">Any location confidence</option>
            {Object.entries(GEO).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          <Select value={filters.maturity} onChange={(e) => set("maturity", e.target.value)} aria-label="Maturity">
            <option value="">Any activity level</option>
            {Object.entries(MATURITY).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          <Select value={filters.qualification} onChange={(e) => set("qualification", e.target.value)} aria-label="Qualification">
            <option value="">Any qualification</option>
            {(["S0", "S1", "S2", "S3"] as const).map((k) => <option key={k} value={k}>{k} — {SQUAL[k].label}</option>)}
          </Select>
          <Select value={filters.research_state} onChange={(e) => set("research_state", e.target.value)} aria-label="Research state">
            <option value="">Any research state</option>
            <option value="not_researched">Not researched yet</option>
            <option value="researched">Researched</option>
            <option value="needs_human_check">You need to look at their profile</option>
            <option value="failed">Research failed</option>
          </Select>
        </div>
      </Card>

      {q.error ? <ErrorState error={q.error} onRetry={q.reload} />
        : !q.data && q.loading ? <Spinner />
          : q.data && q.data.items.length === 0 ? (
            <Empty icon={<Instagram className="h-6 w-6" />} title="Nothing here yet"
              action={<Button variant="primary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" />Add a profile</Button>}>
              {tab === "ready"
                ? "No seller has passed every check yet. Try the Needs verification tab to see what is still open."
                : "No seller matches these filters."}
            </Empty>
          ) : (
            <>
              <p className="text-sm text-subtle">{q.data?.total} seller(s)</p>
              <div className="space-y-3">{q.data?.items.map((c) => <SellerRow key={c.id} c={c} />)}</div>
            </>
          )}

      <AddSellerModal open={adding} onClose={() => setAdding(false)} onAdded={() => { setAdding(false); q.reload(); counts.reload(); }} />
    </div>
  );
}
