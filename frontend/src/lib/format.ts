import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...v: ClassValue[]) => twMerge(clsx(v));

export const INDUSTRY: Record<string, string> = {
  equipment_sales_service: "Equipment Sales & Service",
  wholesale_distribution: "Wholesale Distribution",
};
export const QUAL: Record<string, { label: string; short: string; tone: Tone }> = {
  P0: { label: "Confirmed opportunity", short: "P0", tone: "ok" },
  P1: { label: "High-fit prospect", short: "P1", tone: "info" },
  P2: { label: "Watchlist", short: "P2", tone: "neutral" },
  P3: { label: "Excluded", short: "P3", tone: "bad" },
};
export const LOCATION: Record<string, { label: string; tone: Tone }> = {
  verified: { label: "Chennai · verified", tone: "ok" },
  partial: { label: "Chennai · partly verified", tone: "warn" },
  unknown: { label: "Location unknown", tone: "neutral" },
  outside: { label: "Outside Chennai", tone: "bad" },
};
export const FRICTION: Record<string, string> = { low: "Low friction", moderate: "Moderate friction", high: "High friction", unknown: "Friction unknown" };
export const INTENT: Record<string, string> = { confirmed: "Confirmed by buyer", explicit_public: "Explicit public request", indirect: "Indirect signal", unknown: "Unknown",
  explicit: "Explicit", buyer_confirmed: "Buyer confirmed" };
export const FIT: Record<string, string> = { strong: "Strong", moderate: "Moderate", weak: "Weak", unknown: "Unknown" };
export const READINESS: Record<string, string> = { buyer_confirmed: "Buyer confirmed", limited_public: "Limited public evidence", unknown: "Unknown" };
export const EVQ: Record<string, string> = { strong: "Strong", partial: "Partial", weak: "Weak" };
export const AI_STATUS: Record<string, { label: string; tone: Tone }> = {
  not_run: { label: "AI not run", tone: "neutral" }, done: { label: "AI researched", tone: "ok" }, partial: { label: "AI: partial", tone: "info" },
  unavailable: { label: "AI unavailable", tone: "warn" }, failed: { label: "AI failed", tone: "bad" },
};
export function duration(s: number | null | undefined): string {
  if (s === null || s === undefined) return "—";
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}
export const EVIDENCE: Record<string, { label: string; tone: Tone }> = {
  source_verified: { label: "Verified", tone: "ok" },
  buyer_confirmed: { label: "Buyer confirmed", tone: "info" },
  inferred: { label: "Hypothesis", tone: "warn" },
  unknown: { label: "Unknown", tone: "neutral" },
};
export const SIGNAL_TYPES: Record<string, string> = {
  explicit_software_request: "Asked for software / automation",
  vendor_request: "Looking for a tech vendor / partner",
  operational_problem: "Operational problem",
  integration_need: "Existing system needs integration",
  new_facility: "New service centre / warehouse / branch",
  expansion: "Expanding operations",
  modernisation: "Technology modernisation",
};
export type Tone = "ok" | "warn" | "bad" | "info" | "neutral" | "brand";

export function rupees(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return "₹" + n.toLocaleString("en-IN");
}
export function date(s: string | null | undefined, withTime = false): string {
  if (!s) return "—";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) || s.length <= 10 ? s : s + "Z");
  if (Number.isNaN(d.getTime())) return s;
  return withTime
    ? d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
export function ago(s: string | null | undefined): string {
  if (!s) return "never";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.round(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)} h ago`;
  return `${Math.round(sec / 86400)} days ago`;
}
export function greeting(h = new Date().getHours()): string {
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}
