import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api";
import type { Score } from "../types";

// ---------------------------------------------------------------------------------------------
// Data hook
// ---------------------------------------------------------------------------------------------

export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const load = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    fn()
      .then((d) => {
        if (id === seq.current) {
          setData(d);
          setError(undefined);
        }
      })
      .catch((e: unknown) => {
        if (id === seq.current) setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e));
      })
      .finally(() => id === seq.current && setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(load, [load]);
  return { data, error, loading, reload: load, setData };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | undefined>();
  const run = async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
    setBusy(true);
    setMsg(undefined);
    try {
      const r = await fn();
      if (ok) setMsg({ kind: "ok", text: ok });
      return r;
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof ApiError ? e.message : String(e) });
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, msg, run, setMsg };
}

// ---------------------------------------------------------------------------------------------
// Layout primitives
// ---------------------------------------------------------------------------------------------

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="row gap">{actions}</div>}
    </header>
  );
}

export function Card({ title, children, actions, className }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || actions) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Loading() {
  return <div className="muted pad">Loading…</div>;
}

export function ErrorBox({ error, onRetry }: { error?: string; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="alert err">
      <span>{error}</span>
      {onRetry && (
        <button className="btn sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Msg({ msg }: { msg?: { kind: "ok" | "err"; text: string } }) {
  if (!msg) return null;
  return <div className={`alert ${msg.kind}`}>{msg.text}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (o: number) => void }) {
  if (total <= limit) return <div className="muted small pad-t">{total} item(s)</div>;
  return (
    <div className="row gap pad-t small">
      <button className="btn sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        ← Prev
      </button>
      <span className="muted">
        {offset + 1}–{Math.min(total, offset + limit)} of {total}
      </span>
      <button className="btn sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
        Next →
      </button>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={value === t.id ? "tab active" : "tab"} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Domain badges
// ---------------------------------------------------------------------------------------------

const ELIG_LABEL: Record<string, string> = {
  eligible: "Eligible",
  potentially_eligible: "Potentially eligible",
  not_eligible: "Not eligible",
  partner_route: "Partner route",
  unclear: "Unclear",
  unknown: "Unknown",
};
const ELIG_TONE: Record<string, string> = {
  eligible: "good",
  potentially_eligible: "info",
  not_eligible: "bad",
  partner_route: "warn",
  unclear: "neutral",
  unknown: "neutral",
};

export function EligibilityBadge({ outcome }: { outcome: string | null }) {
  const o = outcome ?? "unknown";
  return <span className={`badge ${ELIG_TONE[o] ?? "neutral"}`}>{ELIG_LABEL[o] ?? o}</span>;
}

export const PIPELINE_LABEL: Record<string, string> = { A_direct: "A · Direct", B_vendor: "B · Vendor", C_chain: "C · Chain", none: "—" };

export function PipelineBadge({ pipeline }: { pipeline: string }) {
  return <span className={`badge pipe-${pipeline}`}>{PIPELINE_LABEL[pipeline] ?? pipeline}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone: Record<string, string> = {
    success: "good", done: "good", approved: "good", confirmed: "good", live: "good", sent_manually: "good", qualified: "good",
    failed: "bad", rejected: "bad", not_eligible: "bad",
    partial: "warn", pending_approval: "warn", needs_manual_review: "warn", credential_gated: "warn", hypothesis: "warn", skipped: "warn",
    running: "info", in_progress: "info", researching: "info", outreach: "info", shortlisted: "info", manual: "info",
  };
  return <span className={`badge ${tone[status] ?? "neutral"}`}>{status.replace(/_/g, " ")}</span>;
}

export function DemoBadge({ show }: { show: boolean }) {
  return show ? <span className="badge demo" title="Demonstration fixture — not a real lead">DEMO</span> : null;
}

export function Geo({ country, region }: { country: string | null; region: string | null }) {
  if (!country) return <span className="muted" title="Geography not stated in the evidence">Unknown</span>;
  return (
    <span>
      {region ? `${region}, ` : ""}
      {country}
    </span>
  );
}

export const SCORE_LABEL: Record<string, string> = { direct_client: "Direct", vendor_subcontracting: "Vendor", chain_potential: "Chain" };

export function ScorePills({ scores }: { scores: Score[] }) {
  const order = ["direct_client", "vendor_subcontracting", "chain_potential"];
  return (
    <span className="row gap-s">
      {order.map((t) => {
        const s = scores.find((x) => x.score_type === t);
        if (!s) return null;
        return (
          <span key={t} className={`pill ${s.disqualified ? "dq" : ""}`} title={s.explanation}>
            {SCORE_LABEL[t]} {s.disqualified ? "DQ" : Math.round(s.effective_total)}
          </span>
        );
      })}
    </span>
  );
}

export function ScoreBreakdown({ score }: { score: Score }) {
  return (
    <div className="score-card">
      <div className="row between">
        <strong>{SCORE_LABEL[score.score_type]} score</strong>
        <span className={`big-num ${score.disqualified ? "bad-text" : ""}`}>
          {score.effective_total}
          <span className="muted small">/100</span>
        </span>
      </div>
      {score.disqualified && <div className="alert err small">Disqualified by a mandatory eligibility failure (raw score {score.raw_total}).</div>}
      <ul className="components">
        {score.components.map((c) => (
          <li key={c.name}>
            <div className="row between small">
              <span>
                {c.name.replace(/_/g, " ")} {!c.known && <span className="badge neutral xs" title="No data — scored 0 but not a negative finding">unknown</span>}
              </span>
              <span className="mono">
                {c.value}/{c.max}
              </span>
            </div>
            <div className="bar">
              <div className={`fill ${c.known ? "" : "unknown"}`} style={{ width: `${(c.value / c.max) * 100}%` }} />
            </div>
            <div className="muted xs">{c.explanation}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function fmtDate(s: string | null | undefined, withTime = false): string {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || s.includes("+") ? s : `${s}Z`);
  if (Number.isNaN(d.getTime())) return s;
  return withTime ? d.toLocaleString() : d.toLocaleDateString();
}

export function ExtLink({ href, children }: { href: string | null | undefined; children?: ReactNode }) {
  if (!href) return <span className="muted">—</span>;
  const safe = /^https?:\/\//i.test(href);
  if (!safe) return <span>{href}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow">
      {children ?? href}
    </a>
  );
}

export function OppLink({ id, title }: { id: number; title: string }) {
  return <Link to={`/opportunities/${id}`}>{title}</Link>;
}

export function Kpi({ label, value, hint, to }: { label: string; value: ReactNode; hint?: string; to?: string }) {
  const inner = (
    <>
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
      {hint && <div className="muted xs">{hint}</div>}
    </>
  );
  return to ? (
    <Link to={to} className="kpi">
      {inner}
    </Link>
  ) : (
    <div className="kpi">{inner}</div>
  );
}
