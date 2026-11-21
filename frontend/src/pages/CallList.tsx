import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Loading, Msg, useAction, useApi } from "../components/ui";
import { NeedBadge, PhoneBadge, Prospect } from "./Prospects";

interface Next { prospect: Prospect | null; reason: string | null; remaining_new: number | null }
interface Summary { calls_today: Record<string, number>; by_state: Record<string, number> }
interface Trust { level: "high" | "good" | "low"; why: string; check_link: string | null; found_on: string; dataset: string | null }
interface OutreachStatus { sent_today: number; cap: number; cap_reached: boolean; in_hours: boolean; hours: { start: number; end: number };
  now_ist: string; sender_name: string; sender_link: string; max_messages_without_reply: number }
interface Pitch { message: string; soft_message: string; is_follow_up: boolean; trust: Trust; niche_label: string | null; call_script: string; if_rude: string;
  links: { call: string | null; whatsapp: string | null; email: string | null; map: string } }
export const FOCUS: [string, string][] = [["", "All"], ["new", "🆕 New businesses"], ["hidden", "💎 Hidden gems"], ["shops", "🛒 Shops & bazaars"],
  ["real_estate", "🏠 Real estate"], ["delivery", "🚚 Delivery"], ["art", "🎨 Art & craft"], ["partners", "🤝 Referral partners"]];

const TARGET = 30;
const NEEDS = [["website", "Website"], ["upgrade", "Website upgrade"], ["marketing", "SEO / Google"], ["crm", "CRM / leads"], ["ai", "WhatsApp / AI bot"],
  ["erp", "ERP / billing"], ["automation", "Automation"], ["app", "App"]] as const;
const BUDGET = ["< ₹25k", "₹25k–1L", "₹1L–5L", "₹5L+", "Not discussed"];
const TIMELINE = ["Now", "1–3 months", "Later", "Not sure"];
const GROUPS = [["no_website", "No website"], ["upgrade", "Website upgrade"], ["colleges", "Colleges"], ["all", "Everyone"]] as const;

function readPref<T>(k: string, d: T): T {
  try { const v = localStorage.getItem(`ioi_call_${k}`); return v ? (JSON.parse(v) as T) : d; } catch { return d; }
}
function writePref(k: string, v: unknown) {
  try { localStorage.setItem(`ioi_call_${k}`, JSON.stringify(v)); } catch { /* ignore */ }
}

function Qualify({ onSave, busy }: { onSave: (q: Record<string, unknown>, qualified: boolean) => void; busy: boolean }) {
  const [needs, setNeeds] = useState<string[]>([]);
  const [budget, setBudget] = useState("");
  const [dm, setDm] = useState("");
  const [timeline, setTimeline] = useState("");
  const [current, setCurrent] = useState("");
  const qualified = needs.length > 0 && dm === "yes" && !!budget && budget !== "Not discussed" && timeline !== "Later";
  return (
    <div className="qualify">
      <h3>Qualify: quick questions</h3>
      <div className="q-row"><span>What do they need?</span>
        <div className="chips">{NEEDS.map(([k, v]) => <button key={k} className={`chip ${needs.includes(k) ? "on" : ""}`} onClick={() => setNeeds((n) => (n.includes(k) ? n.filter((x) => x !== k) : [...n, k]))}>{v}</button>)}</div>
      </div>
      <div className="q-row"><span>Budget?</span>
        <div className="chips">{BUDGET.map((b) => <button key={b} className={`chip ${budget === b ? "on" : ""}`} onClick={() => setBudget(b)}>{b}</button>)}</div>
      </div>
      <div className="q-row"><span>Talking to the decision maker?</span>
        <div className="chips">{[["yes", "Yes, owner/manager"], ["no", "No"], ["unsure", "Not sure"]].map(([k, v]) => <button key={k} className={`chip ${dm === k ? "on" : ""}`} onClick={() => setDm(k)}>{v}</button>)}</div>
      </div>
      <div className="q-row"><span>When?</span>
        <div className="chips">{TIMELINE.map((t) => <button key={t} className={`chip ${timeline === t ? "on" : ""}`} onClick={() => setTimeline(t)}>{t}</button>)}</div>
      </div>
      <input placeholder="What do they use now? (e.g. only Instagram, an old Wix site, Excel)" value={current} onChange={(e) => setCurrent(e.target.value)} />
      <div className="row gap">
        <button className="btn primary" disabled={busy} onClick={() => onSave({ needs, budget, decision_maker: dm, timeline, current_setup: current }, qualified)}>
          Save as {qualified ? "✅ Qualified" : "Interested"} & next
        </button>
        <span className="muted small">{qualified ? "Needs + budget + decision maker + soon = qualified lead." : "Qualified = a need, a budget, the decision maker, and not 'later'."}</span>
      </div>
    </div>
  );
}

function SenderBox({ st, onSaved }: { st: OutreachStatus; onSaved: () => void }) {
  const [name, setName] = useState(st.sender_name);
  const [link, setLink] = useState(st.sender_link);
  const [open, setOpen] = useState(!st.sender_name);
  const act = useAction();
  const save = async () => {
    if (await act.run(() => api.put("/settings", { sender_name: name.trim(), sender_link: link.trim() }), "Saved")) { onSaved(); setOpen(false); }
  };
  if (!open) return <button className="link-btn small" onClick={() => setOpen(true)}>Sending as {st.sender_name || "Inferago"}{st.sender_link ? ` · ${st.sender_link}` : ""} — edit</button>;
  return (
    <div className="alert info small" style={{ flexWrap: "wrap" }}>
      <span><strong>Look real, not like spam:</strong> add your name and one link a business can check (Instagram, LinkedIn or website). It goes into every message.</span>
      <input placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 180 }} />
      <input placeholder="https://instagram.com/inferago (optional)" value={link} onChange={(e) => setLink(e.target.value)} style={{ maxWidth: 280 }} />
      <button className="btn sm primary" disabled={act.busy || !name.trim()} onClick={save}>Save</button>
      <Msg msg={act.msg} />
    </div>
  );
}

export default function CallList() {
  const [group, setGroup] = useState<string>(() => readPref("group", "no_website"));
  const [state, setState] = useState<string>(() => readPref("state", ""));
  const [quality, setQuality] = useState<string>(() => readPref("quality", "good"));
  const [mobileOnly, setMobileOnly] = useState<boolean>(() => readPref("mobile", true));
  const [focus, setFocus] = useState<string>(() => readPref("focus", ""));
  const [channel, setChannel] = useState<"whatsapp" | "call">(() => readPref("channel", "whatsapp"));
  const [real, setReal] = useState<string>(() => readPref("real", "good"));
  const [override, setOverride] = useState(false);
  const ost = useApi(() => api.get<OutreachStatus>("/prospects/outreach-status"));
  const [skipped, setSkipped] = useState<number[]>([]);
  const [next, setNext] = useState<Next | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<"idle" | "interested" | "callback">("idle");
  const [note, setNote] = useState("");
  const [cbWhen, setCbWhen] = useState("");
  const summary = useApi(() => api.get<Summary>("/prospects/summary"));
  const act = useAction();
  const p = next?.prospect ?? null;
  const pitch = useApi(() => (p ? api.get<Pitch>(`/prospects/${p.id}/pitch`) : Promise.resolve(null)), [p?.id]);

  useEffect(() => { writePref("group", group); writePref("state", state); writePref("quality", quality); writePref("mobile", mobileOnly); writePref("focus", focus); writePref("channel", channel); writePref("real", real); },
    [group, state, quality, mobileOnly, focus, channel, real]);

  const load = useCallback(async (extraSkip: number[] = []) => {
    setErr(null);
    setMode("idle"); setNote(""); setCbWhen("");
    try {
      setNext(await api.get<Next>("/prospects/next", {
        group, state, quality, focus, real, phone: mobileOnly || channel === "whatsapp" ? "mobile" : "usable", exclude: [...skipped, ...extraSkip].join(","),
        need: group === "no_website" ? "likely" : undefined,
      }));
    } catch (e) { setErr(String(e)); }
  }, [group, state, quality, mobileOnly, focus, channel, real, skipped]);
  useEffect(() => { load(); }, [group, state, quality, mobileOnly, focus, channel, real]); // eslint-disable-line react-hooks/exhaustive-deps

  const log = async (outcome: string, extra: Record<string, unknown> = {}) => {
    if (!p) return;
    const r = await act.run(() => api.post(`/prospects/${p.id}/contact`, { channel, outcome, note: note || null, ...extra }));
    if (r !== undefined) { summary.reload(); ost.reload(); load(); }
  };
  const skip = () => { if (p) { setSkipped((s) => [...s, p.id]); load([p.id]); } };
  const callbackPreset = (days: number, hour = 11) => {
    const d = new Date(); d.setDate(d.getDate() + days); d.setHours(hour, 0, 0, 0);
    return d.toISOString();
  };

  // keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!p || mode !== "idle" || (e.target as HTMLElement)?.tagName === "INPUT" || (e.target as HTMLElement)?.tagName === "TEXTAREA") return;
      const k = e.key.toLowerCase();
      if (channel === "whatsapp" && k === "1") log("contacted");
      else if (channel === "whatsapp" && k === "2") log("callback", { callback_at: callbackPreset(14), note: note || "replied: not now" });
      else if (channel === "whatsapp" && k === "5") log("rejected", { note: note || "not on WhatsApp / wrong number" });
      else if (k === "1") log("no_answer");
      else if (k === "2") setMode("callback");
      else if (k === "3") log("not_interested");
      else if (k === "4") setMode("interested");
      else if (k === "5") log("rejected", { note: note || "wrong number / closed" });
      else if (k === "s") skip();
      else if (k === "c" && pitch.data?.links.call) window.location.href = pitch.data.links.call;
      else if (k === "w" && pitch.data?.links.whatsapp) window.open(pitch.data.links.whatsapp, "_blank", "noopener");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const today = summary.data?.calls_today ?? { total: 0 };
  const blocked = !!ost.data && (!ost.data.in_hours || ost.data.cap_reached) && !(pitch.data?.is_follow_up && ost.data.in_hours);
  const states = Object.keys(summary.data?.by_state ?? {}).filter((s) => s !== "unknown");
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Outreach list</h1>
          <p className="muted">One business at a time. Start with a friendly WhatsApp that offers something free (no cold-call pressure), tap what happened, go to the next. Follow-ups due come first.</p>
        </div>
        <div className="today-meter" title="Calls logged today">
          <div className="row between small"><strong>Today</strong><span>{today.total} / {TARGET} reached{ost.data ? ` · ${ost.data.sent_today}/${ost.data.cap} first messages` : ""}</span></div>
          <div className="bar"><div className="fill" style={{ width: `${Math.min(100, (100 * today.total) / TARGET)}%` }} /></div>
          <div className="xs muted">{today.interested ?? 0} interested · {today.qualified ?? 0} qualified · {today.callback ?? 0} callbacks · {today.no_answer ?? 0} no answer</div>
        </div>
      </header>

      {ost.data && <SenderBox st={ost.data} onSaved={() => { ost.reload(); pitch.reload(); }} />}
      {ost.data && channel === "whatsapp" && (!ost.data.in_hours || ost.data.cap_reached) && (
        <div className="alert warn small">
          {ost.data.cap_reached
            ? `You've sent ${ost.data.sent_today} first messages today (limit ${ost.data.cap}). Sending more in one day is how numbers get reported as spam. Do follow-ups and calls back instead, and continue tomorrow.`
            : `It's ${ost.data.now_ist} IST. Messages are best sent ${ost.data.hours.start}:00–${ost.data.hours.end}:00, Monday to Saturday. Outside those hours they feel intrusive.`}
        </div>
      )}
      <div className="seg-tabs">
        {GROUPS.map(([k, v]) => <button key={k} className={`seg ${group === k ? "on" : ""}`} onClick={() => { setSkipped([]); setGroup(k); }}>{v}</button>)}
      </div>
      <div className="row gap-s" style={{ margin: "4px 0 10px", flexWrap: "wrap" }}>
        <span className="small muted">Focus:</span>
        {FOCUS.map(([k, v]) => <button key={k} className={`chip ${focus === k ? "on" : ""}`} onClick={() => { setSkipped([]); setFocus(k); }}>{v}</button>)}
      </div>
      <div className="filters">
        <div className="seg-tabs" style={{ margin: 0 }}>
          <button className={`seg ${channel === "whatsapp" ? "on" : ""}`} onClick={() => setChannel("whatsapp")}>💬 WhatsApp first</button>
          <button className={`seg ${channel === "call" ? "on" : ""}`} onClick={() => setChannel("call")}>📞 Call</button>
        </div>
        <select value={state} onChange={(e) => { setSkipped([]); setState(e.target.value); }} aria-label="State">
          <option value="">All states</option>
          {states.map((s) => <option key={s} value={s}>{s} ({summary.data?.by_state[s]})</option>)}
        </select>
        <select value={real} onChange={(e) => { setSkipped([]); setReal(e.target.value); }} aria-label="Real business check">
          <option value="strong">Only very sure they're real</option>
          <option value="good">Sure they're real</option>
          <option value="any">Include unsure listings</option>
        </select>
        <select value={quality} onChange={(e) => { setSkipped([]); setQuality(e.target.value); }} aria-label="Business quality">
          <option value="established">Established businesses only</option>
          <option value="good">Good and established</option>
          <option value="any">Include small businesses</option>
        </select>
        {channel === "call" && <label className="check"><input type="checkbox" checked={mobileOnly} onChange={(e) => setMobileOnly(e.target.checked)} /> Mobile numbers only</label>}
      </div>

      {err && <ErrorBox error={err} onRetry={() => load()} />}
      <Msg msg={act.msg} />
      {!next && !err && <Loading />}
      {next && !p && <div className="empty">Nothing left to call with these filters. 🎉 Try another state or group.</div>}

      {p && (
        <section className="call-card">
          <div className="row between gap" style={{ alignItems: "flex-start" }}>
            <div style={{ minWidth: 0 }}>
              {next?.reason === "follow-up due" && <span className="badge warn">⏰ Follow-up due ({p.status.replace("_", " ")})</span>}
              <h2 className="call-name">{p.name}</h2>
              <div className="muted">{p.type_label} · {p.area ?? "—"}{p.state ? `, ${p.state}` : ""}</div>
              <div className="row gap-s" style={{ marginTop: 6, flexWrap: "wrap" }}>
                <NeedBadge level={p.need_level} />
                {p.quality_level && <span className={`badge ${p.quality_level === "established" ? "good" : p.quality_level === "good" ? "info" : ""}`}>{p.quality_level === "established" ? "Established business" : p.quality_level === "good" ? "Good business" : "Small business"}</span>}
                <PhoneBadge p={p} />
              </div>
            </div>
            {next?.remaining_new != null && <span className="muted small">{next.remaining_new.toLocaleString()} left in this list</span>}
          </div>

          <div className="call-actions">
            {channel === "whatsapp" && pitch.data?.links.whatsapp && (blocked && !override
              ? <span className="row gap-s"><button className="btn big" disabled>💬 WhatsApp paused ({ost.data?.cap_reached ? "daily limit" : "outside hours"})</button>
                  <button className="link-btn xs" onClick={() => setOverride(true)}>send anyway</button></span>
              : <a className="btn primary big" href={pitch.data.links.whatsapp} target="_blank" rel="noopener noreferrer">💬 {pitch.data.is_follow_up ? "Send the one follow-up" : "Open WhatsApp with message"} <kbd>W</kbd></a>)}
            {pitch.data?.links.call && <a className={`btn big ${channel === "call" ? "primary" : ""}`} href={pitch.data.links.call}>📞 Call {p.phone_normalized} <kbd>C</kbd></a>}
            {channel === "call" && pitch.data?.links.whatsapp && <a className="btn big" href={pitch.data.links.whatsapp} target="_blank" rel="noopener noreferrer">💬 WhatsApp <kbd>W</kbd></a>}
            {p.social_links[0] && /^https?:/.test(p.social_links[0]) && <a className="btn big" href={p.social_links[0]} target="_blank" rel="noopener noreferrer">👥 Their page</a>}
            {p.website && <a className="btn big" href={/^https?:/.test(p.website) ? p.website : `http://${p.website}`} target="_blank" rel="noopener noreferrer">🌐 Their site</a>}
          </div>

          {pitch.data?.trust && (
            <div className={`trust trust-${pitch.data.trust.level}`}>
              <strong>{pitch.data.trust.level === "high" ? "✓ Very likely a real, running business" : pitch.data.trust.level === "good" ? "✓ Likely a real business" : "⚠ Not sure this business is still running"}</strong>
              <span className="small"> · {pitch.data.trust.why}{pitch.data.trust.dataset ? ` · source: ${pitch.data.trust.dataset === "meta" ? "Facebook business page (via Overture Maps)" : pitch.data.trust.dataset}` : ""}</span>
              {pitch.data.trust.check_link && <> · <a href={pitch.data.trust.check_link} target="_blank" rel="noopener noreferrer" className="small">check {pitch.data.trust.found_on} first ↗</a></>}
            </div>
          )}
          <div className="grid grid-2">
            <div>
              <h3>Why they need us</h3>
              <ul className="gap-list small">{p.need_reasons.slice(0, 5).map((r) => <li key={r}>{r}</li>)}</ul>
              {p.gaps.length > 0 && <div className="chips tight" style={{ marginTop: 6 }}>{p.gaps.slice(0, 5).map((g) => <span key={g.key} className="chip warn static">{g.label}</span>)}</div>}
            </div>
            <div>
              <h3>{channel === "whatsapp" ? (pitch.data?.is_follow_up ? "Follow-up message (the last one; they didn't reply)" : "WhatsApp message (edit before sending)") : "What to say"}{pitch.data?.niche_label && <span className="badge info" style={{ marginLeft: 6 }}>{pitch.data.niche_label}</span>}</h3>
              <p className="small script" style={{ whiteSpace: "pre-wrap" }}>{(channel === "whatsapp" ? pitch.data?.soft_message : pitch.data?.call_script) ?? "…"}</p>
              {channel === "call" && pitch.data?.if_rude && <p className="xs muted">If they're rude: {pitch.data.if_rude}</p>}
              {p.contact_log.length > 0 && <p className="xs muted">Last time: {p.contact_log[p.contact_log.length - 1].outcome.replace("_", " ")}{p.contact_log[p.contact_log.length - 1].note ? ` — ${p.contact_log[p.contact_log.length - 1].note}` : ""}</p>}
            </div>
          </div>

          <input placeholder="Note (optional): who you spoke to, what they said" value={note} onChange={(e) => setNote(e.target.value)} style={{ width: "100%" }} />

          {mode === "idle" && channel === "whatsapp" && (
            <div className="outcomes">
              <button className="btn primary" disabled={act.busy} onClick={() => log("contacted")}>✓ Sent, wait for reply <kbd>1</kbd></button>
              <button className="btn good" disabled={act.busy} onClick={() => setMode("interested")}>Replied: interested <kbd>4</kbd></button>
              <button className="btn" disabled={act.busy} onClick={() => log("callback", { callback_at: callbackPreset(14), note: note || "replied: not now" })}>Replied: not now <kbd>2</kbd></button>
              <button className="btn" disabled={act.busy} onClick={() => log("not_interested")}>Replied: not interested <kbd>3</kbd></button>
              <button className="btn danger" disabled={act.busy} onClick={() => log("rejected", { note: note || "not on WhatsApp / wrong number" })}>Not on WhatsApp <kbd>5</kbd></button>
              <button className="btn" disabled={act.busy} onClick={skip}>Skip <kbd>S</kbd></button>
            </div>
          )}
          {mode === "idle" && channel === "call" && (
            <div className="outcomes">
              <button className="btn" disabled={act.busy} onClick={() => log("no_answer")}>No answer <kbd>1</kbd></button>
              <button className="btn" disabled={act.busy} onClick={() => setMode("callback")}>Call back later <kbd>2</kbd></button>
              <button className="btn" disabled={act.busy} onClick={() => log("not_interested")}>Not interested <kbd>3</kbd></button>
              <button className="btn good" disabled={act.busy} onClick={() => setMode("interested")}>Interested <kbd>4</kbd></button>
              <button className="btn danger" disabled={act.busy} onClick={() => log("rejected", { note: note || "wrong number / closed" })}>Wrong number / closed <kbd>5</kbd></button>
              <button className="btn" disabled={act.busy} onClick={skip}>Skip <kbd>S</kbd></button>
            </div>
          )}
          {mode === "callback" && (
            <div className="outcomes">
              <span className="small">Call back:</span>
              <button className="btn" onClick={() => log("callback", { callback_at: callbackPreset(0, new Date().getHours() + 2) })}>In 2 hours</button>
              <button className="btn" onClick={() => log("callback", { callback_at: callbackPreset(1) })}>Tomorrow 11 am</button>
              <button className="btn" onClick={() => log("callback", { callback_at: callbackPreset(3) })}>In 3 days</button>
              <button className="btn" onClick={() => log("callback", { callback_at: callbackPreset(7) })}>Next week</button>
              <input type="datetime-local" value={cbWhen} onChange={(e) => setCbWhen(e.target.value)} />
              <button className="btn" disabled={!cbWhen} onClick={() => log("callback", { callback_at: new Date(cbWhen).toISOString() })}>Set</button>
              <button className="link-btn" onClick={() => setMode("idle")}>cancel</button>
            </div>
          )}
          {mode === "interested" && (
            <Qualify busy={act.busy} onSave={(q, ok) => log(ok ? "qualified" : "interested", { qualification: q })} />
          )}
          <p className="xs muted">{channel === "whatsapp"
            ? `Shortcuts: W open WhatsApp · 1 sent · 4 interested · 2 not now · 3 not interested · 5 not on WhatsApp · S skip. One follow-up after 3 days, then we stop if there's no reply (max ${ost.data?.max_messages_without_reply ?? 2} messages). Anyone who says no is never contacted again.`
            : "Shortcuts: C call · W WhatsApp · 1 no answer · 2 call back · 3 not interested · 4 interested · 5 wrong number · S skip"}</p>
        </section>
      )}
    </>
  );
}
