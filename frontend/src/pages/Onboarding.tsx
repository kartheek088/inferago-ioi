import { useState } from "react";
import { CheckCircle2, Circle, XCircle } from "lucide-react";
import { Button, Card, Field, Input, Msg, Notice, Textarea } from "../components/ui";
import { api } from "../lib/api";
import { useAction, useQuery } from "../lib/hooks";
import type { Status } from "../App";

interface Settings {
  business: { company_name: string; positioning: string; services: string[]; facts: string[]; revenue_goal_monthly: number; sender_name: string };
  discovery: { city: string; industries: string[]; industry_mix: Record<string, number>; depth: string };
  ai: { configured: boolean; provider: string | null; model: string | null; how_to_configure: string };
}

const STEPS = ["Your business", "Market", "Sources", "AI (optional)", "First discovery"];

export default function Onboarding({ status, onDone }: { status: Status; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const s = useQuery(() => api.get<Settings>("/settings"));
  const act = useAction();
  const [biz, setBiz] = useState<Settings["business"] | null>(null);
  const [aiMsg, setAiMsg] = useState<string | null>(null);
  const b = biz ?? s.data?.business ?? null;

  const saveBusiness = async () => {
    if (!b) return;
    const ok = await act.run(() => api.put("/settings", { business: b }));
    if (ok) setStep(1);
  };
  const finish = async (runDiscovery: boolean) => {
    if (runDiscovery) {
      const r = await act.run(() => api.post("/jobs", { mode: "balanced", max_candidates: 20, max_deep: 5 }));
      if (!r) return;
    }
    await act.run(() => api.post("/onboarding/complete"));
    onDone();
  };

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Welcome to Inferago IOI</h1>
      <p className="mt-1 text-sm text-subtle">Five quick steps. You can change everything later in Settings.</p>
      <ol className="my-6 flex flex-wrap gap-2 text-xs" aria-label="Setup steps">
        {STEPS.map((t, i) => (
          <li key={t} className={`rounded-full border px-3 py-1 ${i === step ? "border-brand bg-brand-soft text-brand" : i < step ? "border-ok/30 text-ok" : "border-border text-subtle"}`}>
            {i + 1}. {t}
          </li>
        ))}
      </ol>
      {!b ? <Notice>Loading…</Notice> : (
        <Card>
          {step === 0 && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">Confirm your business profile</h2>
              <Field label="Business name"><Input value={b.company_name} onChange={(e) => setBiz({ ...b, company_name: e.target.value })} /></Field>
              <Field label="How you describe your service"><Textarea rows={2} value={b.positioning} onChange={(e) => setBiz({ ...b, positioning: e.target.value })} /></Field>
              <Field label="Services you offer" hint="One per line. Only list what you really offer.">
                <Textarea rows={4} value={b.services.join("\n")} onChange={(e) => setBiz({ ...b, services: e.target.value.split("\n").filter((x) => x.trim()) })} />
              </Field>
              <div className="rounded-lg bg-muted p-3 text-sm"><span className="font-medium">Facts used in messages: </span>{b.facts.join(" · ")}</div>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Monthly revenue goal (₹)"><Input type="number" min={0} value={b.revenue_goal_monthly} onChange={(e) => setBiz({ ...b, revenue_goal_monthly: Math.max(0, parseInt(e.target.value || "0", 10)) })} /></Field>
                <Field label="Your name (signs outreach messages)"><Input value={b.sender_name} onChange={(e) => setBiz({ ...b, sender_name: e.target.value })} /></Field>
              </div>
              <Msg msg={act.msg} />
              <div className="flex justify-end"><Button variant="primary" loading={act.busy} onClick={saveBusiness}>Looks right — continue</Button></div>
            </div>
          )}
          {step === 1 && s.data && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">Where and who</h2>
              <div className="rounded-lg border border-border p-4">
                <p className="text-sm"><strong>Location:</strong> Chennai city only (Greater Chennai Corporation area). Suburbs like Tambaram or Avadi are
                  left out unless you approve them in Settings. Businesses based elsewhere are never added.</p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-border p-4"><p className="font-medium">Equipment Sales & Service</p>
                  <p className="text-sm text-subtle">Medical, lab, industrial, electrical and commercial equipment companies that install, repair and maintain. 70% of discovery effort.</p></div>
                <div className="rounded-lg border border-border p-4"><p className="font-medium">Wholesale Distribution</p>
                  <p className="text-sm text-subtle">B2B distributors with repeat orders, stock and dispatch. 30% of discovery effort.</p></div>
              </div>
              <div className="flex justify-between"><Button variant="ghost" onClick={() => setStep(0)}>Back</Button><Button variant="primary" onClick={() => setStep(2)}>Confirm</Button></div>
            </div>
          )}
          {step === 2 && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">Discovery sources</h2>
              <ul className="space-y-2">
                {status.preflight.checks.filter((c) => c.source !== "ai").map((c) => (
                  <li key={c.source} className="flex items-start gap-2 text-sm">
                    {c.ready ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-ok" /> : <XCircle className="mt-0.5 h-4 w-4 text-bad" />}{c.message}
                  </li>
                ))}
                <li className="flex items-start gap-2 text-sm"><Circle className="mt-0.5 h-4 w-4 text-subtle" />You can also add businesses yourself or import an authorised CSV list.</li>
              </ul>
              <p className="text-xs text-subtle">IOI does not read Google Maps, LinkedIn, JustDial or IndiaMART automatically. Their terms don't allow it; add those finds by hand.</p>
              <div className="flex justify-between"><Button variant="ghost" onClick={() => setStep(1)}>Back</Button><Button variant="primary" onClick={() => setStep(3)}>Continue</Button></div>
            </div>
          )}
          {step === 3 && s.data && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">AI assistance (optional)</h2>
              <p className="text-sm text-subtle">IOI works fully without AI. If configured, Deep research uses a limited number of AI calls to read company websites; every
                statement it keeps must be quoted word-for-word from the site.</p>
              {s.data.ai.configured ? (
                <Notice kind="ok">AI is configured: {s.data.ai.provider} ({s.data.ai.model}).</Notice>
              ) : <Notice>Not configured. {s.data.ai.how_to_configure}</Notice>}
              {s.data.ai.configured && <Button size="sm" loading={act.busy} onClick={async () => { const r = await act.run(() => api.post<{ ok: boolean; message: string }>("/ai/test")); if (r) setAiMsg(r.message); }}>Test connection</Button>}
              {aiMsg && <Notice>{aiMsg}</Notice>}
              <div className="flex justify-between"><Button variant="ghost" onClick={() => setStep(2)}>Back</Button><Button variant="primary" onClick={() => setStep(4)}>Continue</Button></div>
            </div>
          )}
          {step === 4 && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">Run a small first discovery</h2>
              <p className="text-sm text-subtle">IOI will look at up to 20 Chennai businesses and check the 5 most promising websites. This takes a few minutes and keeps running
                in the background. Nothing is ever sent to any business.</p>
              {!status.preflight.can_start && <Notice kind="warn">No discovery source is ready yet — you can finish setup and fix this in Settings.</Notice>}
              <Msg msg={act.msg} />
              <div className="flex flex-wrap justify-between gap-2">
                <Button variant="ghost" onClick={() => setStep(3)}>Back</Button>
                <div className="flex gap-2">
                  <Button onClick={() => finish(false)} loading={act.busy}>Skip for now</Button>
                  <Button variant="primary" disabled={!status.preflight.can_start} loading={act.busy} onClick={() => finish(true)}>Start first discovery</Button>
                </div>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
