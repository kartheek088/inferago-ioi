import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Check, Search, Send, Trash2, X } from "lucide-react";
import { Badge, Button, ErrorState, Ext, Field, Input, Notice, Select, Spinner, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { ago } from "../../lib/format";
import { useQuery } from "../../lib/hooks";

type Tone = "brand" | "ok" | "warn" | "bad" | "info" | "neutral";

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

export const OBSERVED: Record<string, string> = {
  not_found: "Page not found",
  server_error: "Server error",
  domain_expired_or_unresolved: "Domain not resolving",
  tls_problem: "HTTPS / certificate problem",
  placeholder_or_parked: "Placeholder, parked or suspended page",
};

export const ACTIVITY: Record<string, { label: string; tone: Tone }> = {
  active_verified: { label: "Operating — verified", tone: "ok" },
  active_probable: { label: "Operating — probable", tone: "info" },
  activity_unclear: { label: "Operating? Unclear", tone: "neutral" },
  inactive_suspected: { label: "Possibly inactive", tone: "warn" },
  closed_verified: { label: "Closed", tone: "bad" },
};

export const QUAL: Record<string, { label: string; tone: Tone; hint: string }> = {
  R0: { label: "R0 · Confirmed need", tone: "ok", hint: "The business told you it needs help" },
  R1: { label: "R1 · Strong opportunity", tone: "brand", hint: "All gates pass — intent still unconfirmed" },
  R2: { label: "R2 · Research needed", tone: "warn", hint: "Some gates still open" },
  R3: { label: "R3 · Not suitable", tone: "neutral", hint: "Excluded or already has a working site" },
};

const KINDS: Record<string, string> = {
  phone_call: "Phone call with the business",
  official_social: "The business's own social page",
  marketplace_listing: "Marketplace listing (IndiaMART, Justdial, …)",
  official_website: "The business's own (newer) website",
  news: "News or association listing",
  other: "Other public source",
  confirmed_need: "Business confirmed it needs help",
};
const DIRECT = new Set(["phone_call", "confirmed_need"]);

type Gate = { key: string; label: string; passed: boolean; detail: string };
type Evidence = {
  id: number; kind: string; kind_label: string; signal: string; statement: string; source_url: string | null;
  published_on: string | null; observed_on: string; method: string; recorded_by: string | null; counts_as_dated: boolean;
};
type Contact = {
  id: number; kind: string; kind_label: string; value: string; route: string; source_url: string;
  needs_review: string | null; usable: boolean; reviewable?: boolean; review?: string | null;
};
type CheckRow = {
  checked_at: string; status: string; observed_class: string | null; confidence: string; dns: string;
  http_status: number | null; final_url: string | null; tls: string | null; error_kind: string | null;
  error_text: string | null; reasons: string[];
};
export type DossierData = {
  company: { id: number; name: string; website: string | null; business_type: string; location_confidence: string; location_reason: string | null };
  checks: CheckRow[];
  qualification: { category: string; bucket: string; summary: string; gates: Gate[]; friction: string[] };
  activity: { status: string; reasons: string[]; window_days: number; manual: Evidence[]; automatic: Evidence[] };
  alternatives: { url: string; found_via: string; status: string; reason: string | null; checked_at: string }[];
  contacts: Contact[];
  check_yourself: { label: string; url: string }[];
  outreach?: { approved: boolean; lead_source: string | null; ready: boolean };
};

export function Tag({ map, value }: { map: Record<string, { label: string; tone: Tone }>; value: string }) {
  const s = map[value] ?? { label: value, tone: "neutral" as Tone };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-xl border border-border/70 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Local calendar date (YYYY-MM-DD). toISOString() would give the UTC date, which lags IST until 05:30. */
export const today = (d = new Date()) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function RecordForm({ id, onSaved }: { id: number; onSaved: () => void }) {
  const [kind, setKind] = useState("phone_call");
  const [signal, setSignal] = useState("active");
  const [statement, setStatement] = useState("");
  const [url, setUrl] = useState("");
  const [published, setPublished] = useState("");
  const [observed, setObserved] = useState(today());
  const [chennai, setChennai] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const direct = DIRECT.has(kind);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await api.post(`/recovery/companies/${id}/evidence`, {
        kind, signal: kind === "confirmed_need" ? "active" : signal, statement,
        source_url: url || null, published_on: direct ? null : published || null, observed_on: observed || null,
        confirms_chennai: kind === "phone_call" && chennai,
      });
      setStatement(""); setUrl(""); setPublished(""); setChennai(false);
      onSaved();
    } catch (x) {
      setErr(x instanceof Error ? x.message : String(x));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-3 grid gap-2 md:grid-cols-2" aria-label="Record what you verified">
      <Field label="What did you check?">
        <Select value={kind} onChange={(e) => setKind(e.target.value)}>
          {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </Field>
      {kind !== "confirmed_need" && (
        <Field label="What did it show?">
          <Select value={signal} onChange={(e) => setSignal(e.target.value)}>
            <option value="active">Still operating</option>
            <option value="inactive">Looks inactive</option>
            <option value="closed">Closed</option>
          </Select>
        </Field>
      )}
      <div className="md:col-span-2">
        <Field label="What you saw" hint="Business facts only. No phone numbers or emails here.">
          <Textarea value={statement} onChange={(e) => setStatement(e.target.value)} rows={2} required minLength={3} maxLength={500} />
        </Field>
      </div>
      <Field label={direct ? "Link (optional)" : "Link where you saw it"}>
        <Input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" required={!direct} />
      </Field>
      {!direct && (
        <Field label="Date the post / listing was published" hint="Leave empty if it shows no date — undated items don't count.">
          <Input type="date" value={published} max={today()} onChange={(e) => setPublished(e.target.value)} />
        </Field>
      )}
      <Field label={direct ? "Date of the call" : "Date you checked"}>
        <Input type="date" value={observed} max={today()} onChange={(e) => setObserved(e.target.value)} required />
      </Field>
      {kind === "phone_call" && (
        <label className="flex items-center gap-2 text-sm md:col-span-2">
          <input type="checkbox" checked={chennai} onChange={(e) => setChennai(e.target.checked)} />
          They confirmed their Chennai address on this call
        </label>
      )}
      {err && <div className="md:col-span-2"><Notice kind="err">{err}</Notice></div>}
      <div className="md:col-span-2"><Button type="submit" size="sm" loading={busy} disabled={busy}>Save</Button></div>
    </form>
  );
}

function EvidenceList({ items, onDelete, empty }: { items: Evidence[]; onDelete?: (id: number) => void; empty: string }) {
  if (!items.length) return <p className="text-sm text-subtle">{empty}</p>;
  return (
    <ul className="space-y-2 text-sm">
      {items.map((e) => (
        <li key={e.id} className="flex items-start gap-2">
          <Badge tone={e.signal === "active" ? "ok" : e.signal === "closed" ? "bad" : "warn"}>{e.signal}</Badge>
          <div className="min-w-0 flex-1">
            <div>{e.statement}</div>
            <div className="text-xs text-subtle">
              {e.kind_label} · {e.published_on ? `published ${e.published_on}` : DIRECT.has(e.kind) ? `on ${e.observed_on}` : "undated (doesn't count)"}
              {" "}· seen {e.observed_on}{e.source_url && <> · <Ext href={e.source_url}>source</Ext></>}
            </div>
          </div>
          {onDelete && (
            <button type="button" aria-label="Delete this evidence" className="text-subtle hover:text-bad" onClick={() => onDelete(e.id)}>
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

export function Dossier({ id, onChanged }: { id: number; onChanged?: () => void }) {
  const q = useQuery(() => api.get<DossierData>(`/recovery/companies/${id}`), [id]);
  const [altBusy, setAltBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [approveErr, setApproveErr] = useState<string | null>(null);
  if (q.loading && !q.data) return <Spinner />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={q.reload} />;
  const d = q.data;
  const refresh = () => { q.reload(); onChanged?.(); };

  async function reviewContact(cid: number, decision: "approved" | "rejected") {
    setMsg(null);
    try {
      await api.post(`/recovery/contacts/${cid}/review`, { decision });
      refresh();
    } catch (x) {
      setMsg(x instanceof Error ? x.message : String(x));
    }
  }
  async function remove(eid: number) {
    await api.del(`/recovery/evidence/${eid}`);
    refresh();
  }
  async function approve() {
    setApproveErr(null);
    try {
      await api.post(`/recovery/companies/${id}/approve`);
      refresh();
    } catch (x) {
      setApproveErr(x instanceof Error ? x.message : String(x));
    }
  }
  async function findNewer() {
    setAltBusy(true); setMsg(null);
    try {
      const r = await api.post<{ results: unknown[] }>(`/recovery/companies/${id}/alternatives`);
      setMsg(r.results.length ? `Checked ${r.results.length} possible newer site(s).` : "No other domain found in its email or directory record.");
      refresh();
    } catch (x) {
      setMsg(x instanceof Error ? x.message : String(x));
    } finally {
      setAltBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <Section title="Should we approach them?">
        <div className="flex flex-wrap items-center gap-2">
          <Tag map={QUAL} value={d.qualification.category} />
          <span className="text-sm">{d.qualification.summary}</span>
        </div>
        <ul className="mt-2 grid gap-1 text-sm md:grid-cols-2">
          {d.qualification.gates.map((g) => (
            <li key={g.key} className="flex items-start gap-2">
              {g.passed ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-label="passed" /> : <X className="mt-0.5 h-4 w-4 shrink-0 text-bad" aria-label="not passed" />}
              <span><span className="font-medium">{g.label}</span> <span className="text-subtle">— {g.detail}</span></span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-subtle">Unknowns: {d.qualification.friction.join(" · ")}</p>
        {d.outreach?.approved ? (
          <p className="mt-3 text-sm"><Badge tone="ok">Approved</Badge> It's in <Link to="/outreach" className="underline">Outreach</Link> with a
            draft message — nothing is sent until you contact them.</p>
        ) : d.outreach?.ready ? (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button size="sm" onClick={approve}><Send className="h-4 w-4" /> Approve for outreach</Button>
            <span className="text-xs text-subtle">Adds it to Outreach with a factual draft about what the checks saw. IOI sends nothing.</span>
          </div>
        ) : null}
        {approveErr && <Notice kind="err">{approveErr}</Notice>}
      </Section>

      <Section title="Is the business still operating?">
        <div className="flex flex-wrap items-center gap-2">
          <Tag map={ACTIVITY} value={d.activity.status} />
          <span className="text-sm text-subtle">{d.activity.reasons.join(" ")} (window: {d.activity.window_days} days)</span>
        </div>
        <div className="mt-3 text-xs font-semibold uppercase tracking-wide text-subtle">What you verified</div>
        <EvidenceList items={d.activity.manual} onDelete={remove} empty="Nothing recorded yet. Call them, or open the searches below and record what you find." />
        {d.activity.automatic.length > 0 && <>
          <div className="mt-3 text-xs font-semibold uppercase tracking-wide text-subtle">Found automatically</div>
          <EvidenceList items={d.activity.automatic} empty="" />
        </>}
        <RecordForm id={id} onSaved={refresh} />
      </Section>

      <Section title="Check it yourself" >
        <p className="mb-2 text-xs text-subtle">These open in your browser. IOI never visits Facebook, Instagram, IndiaMART or Justdial itself.</p>
        <div className="flex flex-wrap gap-2">
          {d.check_yourself.map((l) => (
            <a key={l.label} href={l.url} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-sm hover:bg-muted">
              <Search className="h-3.5 w-3.5" /> {l.label}
            </a>
          ))}
        </div>
      </Section>

      <Section title="Did they move to a newer website?"
        action={<Button size="sm" variant="secondary" onClick={findNewer} loading={altBusy} disabled={altBusy}>Look for a newer website</Button>}>
        {msg && <Notice kind="info">{msg}</Notice>}
        {d.alternatives.length ? (
          <ul className="space-y-1 text-sm">
            {d.alternatives.map((a) => (
              <li key={a.url} className="flex flex-wrap items-center gap-2">
                <Ext href={a.url} /> <Tag map={STATUS} value={a.status} />
                <span className="text-xs text-subtle">from its {a.found_via.replace("_", " ")} · {ago(a.checked_at)}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-subtle">None found yet. Free email addresses (Gmail etc.) are never used to guess a website.</p>}
      </Section>

      <Section title="Business contacts">
        {d.contacts.length ? (
          <ul className="space-y-1 text-sm">
            {d.contacts.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-2">
                <span className={c.usable ? "" : "text-subtle line-through decoration-dotted"}>{c.value}</span>
                <Badge tone="neutral">{c.kind_label}</Badge>
                <Badge tone={c.route === "official" ? "ok" : "neutral"}>{c.route === "official" ? "on their own site" : "from a directory"}</Badge>
                {c.needs_review && <span className="text-xs text-warn">{c.needs_review}</span>}
                {c.review === "approved" && <Badge tone="ok">you approved this</Badge>}
                <Ext href={c.source_url}>source</Ext>
                {c.reviewable && c.review !== "approved" && (
                  <Button size="sm" variant="secondary" onClick={() => reviewContact(c.id, "approved")}>It's the business line</Button>
                )}
                {c.reviewable && c.review !== "rejected" && (
                  <Button size="sm" variant="ghost" onClick={() => reviewContact(c.id, "rejected")}>Don't use</Button>
                )}
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-subtle">No business contact on file.</p>}
        {msg && <Notice kind="info">{msg}</Notice>}
        <p className="mt-2 text-xs text-subtle">
          Approve a flagged number only once you know it is the business's line (for example, the business answered it).
          A public business number is not consent to promotional messages; outreach still goes through approval in Outreach.
        </p>
      </Section>

      <Section title="Website checks">
        <ol className="space-y-2 text-sm">
          {d.checks.map((c, i) => (
            <li key={i} className="rounded-lg border border-border/70 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <Tag map={STATUS} value={c.status} />
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
      </Section>
    </div>
  );
}
