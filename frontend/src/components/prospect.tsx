import { Link } from "react-router-dom";
import { Building2, MapPin, Phone, Radio, ShieldCheck } from "lucide-react";
import { Badge, ScoreRing } from "./ui";
import { EVIDENCE, FRICTION, INDUSTRY, LOCATION, QUAL, date, type Tone } from "../lib/format";
import type { CompanyCard } from "../lib/types";

export function QualBadge({ q }: { q: string }) {
  const v = QUAL[q] ?? { label: q, short: q, tone: "neutral" as Tone };
  return <Badge tone={v.tone} title={v.label}>{v.short} · {v.label}</Badge>;
}
export function LocationBadge({ c }: { c: { location_confidence: string; locality: string | null } }) {
  const v = LOCATION[c.location_confidence] ?? LOCATION.unknown;
  return <Badge tone={v.tone}><MapPin className="h-3 w-3" />{c.locality ? `${c.locality.replace(/\b\w/g, (m) => m.toUpperCase())} · ` : ""}{v.label.replace("Chennai · ", "")}</Badge>;
}
export function EvidenceTag({ state }: { state: string }) {
  const v = EVIDENCE[state] ?? EVIDENCE.unknown;
  return <Badge tone={v.tone}>{v.label}</Badge>;
}

export function ProspectCard({ c, actions }: { c: CompanyCard; actions?: React.ReactNode }) {
  return (
    <article className="rounded-2xl border border-border/80 bg-surface p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition hover:border-brand/40 hover:shadow-md" data-testid="prospect-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Link to={`/prospects/${c.id}`} className="text-base font-semibold text-fg hover:text-brand">{c.name}</Link>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
            <Badge tone="brand"><Building2 className="h-3 w-3" />{INDUSTRY[c.industry ?? ""] ?? "—"}</Badge>
            <LocationBadge c={c} />
            <QualBadge q={c.qualification} />
            {c.is_test && <Badge tone="warn">Test data</Badge>}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden text-right text-xs text-subtle sm:block">{FRICTION[c.friction]}</div>
          <ScoreRing value={c.score} />
        </div>
      </div>
      {c.description && <p className="mt-3 text-sm text-subtle">{c.description}</p>}
      <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
        <div className="flex gap-2"><Radio className="mt-0.5 h-4 w-4 shrink-0 text-subtle" /><div>
          <dt className="sr-only">Latest signal</dt>
          <dd>{c.latest_signal ? <>{c.latest_signal.label} <span className="text-subtle">· {c.latest_signal.date ? date(c.latest_signal.date) : "date unknown"}{c.latest_signal.confirmed ? " · confirmed" : " · not yet confirmed"}</span></> : <span className="text-subtle">No buying signal yet</span>}</dd>
        </div></div>
        <div className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-subtle" /><dd>{c.sources} source{c.sources === 1 ? "" : "s"} · {c.research_level === "directory" ? "directory only" : "website checked"}</dd></div>
        <div className="flex gap-2"><Phone className="mt-0.5 h-4 w-4 shrink-0 text-subtle" /><dd>{c.official_contact ? "Contact on their website" : c.has_contact ? "Directory contact" : <span className="text-subtle">No contact yet</span>}</dd></div>
        {c.offer && <div className="flex gap-2"><span className="mt-0.5 h-4 w-4 shrink-0 text-center text-subtle">→</span><dd>Suggested: <strong>{c.offer}</strong></dd></div>}
      </dl>
      <p className="mt-4 flex items-start gap-2 rounded-xl bg-brand-soft/50 px-3 py-2 text-sm"><span className="font-semibold text-brand">Next</span><span>{c.next_action}</span></p>
      {actions && <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">{actions}</div>}
    </article>
  );
}
