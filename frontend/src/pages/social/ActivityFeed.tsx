import { Link, useSearchParams } from "react-router-dom";
import { Activity as ActivityIcon } from "lucide-react";
import { Badge, Card, Empty, ErrorState, Ext, Notice, PageHeader, Select, Spinner } from "../../components/ui";
import { api } from "../../lib/api";
import { date } from "../../lib/format";
import { useQuery } from "../../lib/hooks";
import { PLATFORM, type SocialSignal } from "../../lib/social";

type Row = SocialSignal & { seller: { id: number; name: string } };

export default function SocialActivityFeed() {
  const [params, setParams] = useSearchParams();
  const days = params.get("days") ?? "90";
  const kind = params.get("indicator_class") ?? "";
  const platform = params.get("platform") ?? "";
  const q = useQuery(() => api.get<{ items: Row[]; note: string }>("/social/activity", {
    days, indicator_class: kind, platform, limit: 200,
  }), [days, kind, platform]);

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Social activity" description="What sellers have published, newest first." />

      <Card>
        <div className="grid gap-3 sm:grid-cols-3">
          <Select value={days} onChange={(e) => set("days", e.target.value)} aria-label="Period">
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
            <option value="180">Last 180 days</option>
            <option value="365">Last year</option>
          </Select>
          <Select value={kind} onChange={(e) => set("indicator_class", e.target.value)} aria-label="Kind">
            <option value="">Activity and demand indicators</option>
            <option value="activity">Activity only</option>
            <option value="demand_indicator">Demand indicators only</option>
          </Select>
          <Select value={platform} onChange={(e) => set("platform", e.target.value)} aria-label="Platform">
            <option value="">All platforms</option>
            {Object.entries(PLATFORM).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </div>
      </Card>

      {q.data && <Notice kind="info">{q.data.note}</Notice>}

      {q.error ? <ErrorState error={q.error} onRetry={q.reload} />
        : !q.data && q.loading ? <Spinner />
          : q.data && q.data.items.length === 0 ? (
            <Empty icon={<ActivityIcon className="h-6 w-6" />} title="No activity recorded yet">
              Activity appears here once a seller's own pages have been read, or once you record what you saw on
              their profile.
            </Empty>
          ) : (
            <ul className="space-y-2">
              {q.data?.items.map((a) => (
                <li key={a.id}>
                  <Card>
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <Link to={`/social-commerce/leads/${a.seller.id}`} className="font-medium no-underline">{a.seller.name}</Link>
                      <span>{a.label}</span>
                      <Badge tone={a.indicator_class === "demand_indicator" ? "warn" : "info"}>
                        {a.indicator_class === "demand_indicator" ? "demand indicator" : "activity"}
                      </Badge>
                      {a.published_at ? <span className="text-xs text-subtle">{date(a.published_at)}</span>
                        : <Badge>no date on the source</Badge>}
                      {a.platform && <Badge>{PLATFORM[a.platform] ?? a.platform}</Badge>}
                      {a.review_status === "confirmed" && <Badge tone="ok">confirmed</Badge>}
                    </div>
                    {a.excerpt && <blockquote className="mt-1 border-l-2 border-border pl-3 text-xs text-subtle">{a.excerpt}</blockquote>}
                    <p className="mt-1 text-xs"><Ext href={a.url}>Source</Ext>{a.source_name ? ` · ${a.source_name}` : ""}</p>
                  </Card>
                </li>
              ))}
            </ul>
          )}
    </div>
  );
}
