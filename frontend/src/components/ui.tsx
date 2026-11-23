import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes, useEffect } from "react";
import { AlertTriangle, CheckCircle2, ExternalLink, Loader2, X } from "lucide-react";
import { cn, type Tone } from "../lib/format";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
const VARIANT: Record<Variant, string> = {
  primary: "bg-brand text-brand-fg hover:bg-brand/90 shadow-sm",
  secondary: "bg-surface text-fg border border-border hover:bg-muted",
  ghost: "text-subtle hover:bg-muted hover:text-fg",
  danger: "bg-surface text-bad border border-border hover:bg-bad/10",
  success: "bg-ok text-white hover:bg-ok/90 dark:text-black",
};

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg"; loading?: boolean }>(
  ({ className, variant = "secondary", size = "md", loading, disabled, children, ...p }, ref) => (
    <button ref={ref} disabled={disabled || loading}
      className={cn("inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap",
        size === "sm" ? "h-8 px-3 text-sm" : size === "lg" ? "h-12 px-6 text-base" : "h-10 px-4 text-sm", VARIANT[variant], className)} {...p}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  ));
Button.displayName = "Button";

export function Card({ className, children, title, action, description }: { className?: string; children: ReactNode; title?: ReactNode; action?: ReactNode; description?: ReactNode }) {
  return (
    <section className={cn("rounded-2xl border border-border/80 bg-surface shadow-[0_1px_2px_rgba(16,24,40,0.04),0_1px_3px_rgba(16,24,40,0.06)]", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 px-5 pt-5">
          <div>
            {title && <h2 className="text-base font-semibold">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-subtle">{description}</p>}
          </div>
          {action}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

const TONE: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok border-ok/20", warn: "bg-warn/10 text-warn border-warn/25", bad: "bg-bad/10 text-bad border-bad/20",
  info: "bg-info/10 text-info border-info/20", neutral: "bg-muted text-subtle border-border", brand: "bg-brand-soft text-brand border-brand/20",
};
export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return <span title={title} className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", TONE[tone], className)}>{children}</span>;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn("h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm placeholder:text-subtle/70 focus:border-brand focus:outline-none", className)} {...p} />
));
Input.displayName = "Input";
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn("w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm placeholder:text-subtle/70 focus:border-brand focus:outline-none", className)} {...p} />
));
Textarea.displayName = "Textarea";
export function Select({ className, children, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn("h-10 rounded-lg border border-border bg-surface px-3 text-sm focus:border-brand focus:outline-none", className)} {...p}>{children}</select>;
}
export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="block text-xs text-subtle">{hint}</span>}
    </label>
  );
}

export function Stat({ label, value, hint, icon, tone = "brand" }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: Tone }) {
  const chip: Record<Tone, string> = { brand: "bg-brand-soft text-brand", ok: "bg-ok/10 text-ok", warn: "bg-warn/10 text-warn", bad: "bg-bad/10 text-bad",
    info: "bg-info/10 text-info", neutral: "bg-muted text-subtle" };
  return (
    <div className="rounded-2xl border border-border/80 bg-surface p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="flex items-center gap-3">
        {icon && <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl", chip[tone])}>{icon}</span>}
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase leading-tight tracking-wide text-subtle sm:text-xs">{label}</div>
          <div className="text-2xl font-semibold tabular-nums leading-tight">{value}</div>
        </div>
      </div>
      {hint && <div className="mt-2 text-xs text-subtle">{hint}</div>}
    </div>
  );
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-border bg-surface/50 px-6 py-12 text-center">
      {icon && <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-brand-soft text-brand">{icon}</div>}
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-subtle">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return <div className="flex items-center gap-2 py-8 text-sm text-subtle" role="status"><Loader2 className="h-4 w-4 animate-spin" />{label}</div>;
}

export function Notice({ kind = "info", children }: { kind?: "info" | "ok" | "err" | "warn"; children: ReactNode }) {
  const cls = { info: "border-info/25 bg-info/5", ok: "border-ok/25 bg-ok/5", err: "border-bad/25 bg-bad/5 text-bad", warn: "border-warn/30 bg-warn/5" }[kind];
  const Icon = kind === "ok" ? CheckCircle2 : AlertTriangle;
  return <div role={kind === "err" ? "alert" : "status"} className={cn("flex items-start gap-2 rounded-lg border px-3 py-2 text-sm", cls)}>{kind !== "info" && <Icon className="mt-0.5 h-4 w-4 shrink-0" />}<div>{children}</div></div>;
}

export function Msg({ msg }: { msg?: { kind: "ok" | "err"; text: string } }) {
  return msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null;
}

export function ErrorState({ error, onRetry }: { error?: { message: string; status?: number }; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <Notice kind="err">
      {error.message} {onRetry && <button className="ml-2 font-medium underline" onClick={onRetry}>Try again</button>}
    </Notice>
  );
}

export function Ext({ href, children, className }: { href: string | null | undefined; children?: ReactNode; className?: string }) {
  if (!href) return <span className="text-subtle">no link</span>;
  let label: ReactNode = children;
  if (!label) { try { label = new URL(href).hostname.replace(/^www\./, ""); } catch { label = href; } }
  return <a href={href} target="_blank" rel="noopener noreferrer" className={cn("inline-flex items-center gap-1 break-all", className)}>{label}<ExternalLink className="h-3 w-3 shrink-0" aria-hidden /></a>;
}

export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} className="max-h-[92vh] w-full overflow-auto rounded-t-2xl bg-surface shadow-xl sm:max-w-lg sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="font-semibold">{title}</h3>
          <button onClick={onClose} className="rounded p-1 text-subtle hover:bg-muted" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="space-y-4 p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string; count?: number | null }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-border">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cn("-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
            value === t.id ? "border-brand text-fg" : "border-transparent text-subtle hover:text-fg")}>
          {t.label}{t.count !== undefined && t.count !== null && <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs text-subtle">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function ScoreRing({ value, size = 52 }: { value: number; size?: number }) {
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, value)) / 100;
  const color = value >= 70 ? "rgb(var(--ok))" : value >= 45 ? "rgb(var(--brand))" : "rgb(var(--subtle))";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`Score ${value} out of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--muted))" strokeWidth={5} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={5} strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-sm font-semibold tabular-nums">{value}</span>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-subtle">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
