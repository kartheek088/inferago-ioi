import { useEffect, useState } from "react";
import { api, getActor, getToken, setActor, setToken } from "../api";
import { Card, ErrorBox, Loading, Msg, PageHeader, useAction, useApi } from "../components/ui";

interface SettingsData {
  search_terms: string[];
  country_priorities: { match: string; level: string; bonus: number }[];
  research_budget: Record<string, number>;
  profile_overrides: Record<string, unknown>;
  ai_classification_refinement: boolean;
  ai_document_extraction: boolean;
  ai_auto_review_top_n: number;
  runtime: { ai_enabled: boolean; ai_model: string | null; ai_provider?: string | null; reddit_configured: boolean; scheduler: { enabled: boolean; jobs: { id: string; next_run: string | null }[] }; auth_mode: string };
}

export default function SettingsPage() {
  const s = useApi(() => api.get<SettingsData>("/settings"));
  const profile = useApi(() => api.get<{ profile: Record<string, unknown> }>("/profile"));
  const act = useAction();
  const local = useAction();
  const [terms, setTerms] = useState("");
  const [prio, setPrio] = useState("");
  const [budget, setBudget] = useState("");
  const [overrides, setOverrides] = useState("");
  const [aiRefine, setAiRefine] = useState(true);
  const [aiDocs, setAiDocs] = useState(true);
  const [autoReview, setAutoReview] = useState(3);
  const [token, setTok] = useState(getToken());
  const [actor, setAct] = useState(getActor());

  useEffect(() => {
    if (!s.data) return;
    setTerms(s.data.search_terms.join("\n"));
    setPrio(JSON.stringify(s.data.country_priorities, null, 2));
    setBudget(JSON.stringify(s.data.research_budget, null, 2));
    setOverrides(JSON.stringify(s.data.profile_overrides, null, 2));
    setAiRefine(s.data.ai_classification_refinement !== false);
    setAiDocs(s.data.ai_document_extraction !== false);
    setAutoReview(s.data.ai_auto_review_top_n ?? 3);
  }, [s.data]);

  const save = async () => {
    let body;
    try {
      body = {
        search_terms: terms.split("\n").map((t) => t.trim()).filter(Boolean),
        country_priorities: JSON.parse(prio),
        research_budget: JSON.parse(budget),
        profile_overrides: JSON.parse(overrides || "{}"),
        ai_classification_refinement: aiRefine,
        ai_document_extraction: aiDocs,
        ai_auto_review_top_n: autoReview,
      };
    } catch {
      act.setMsg({ kind: "err", text: "Country priorities, research budget and profile overrides must be valid JSON." });
      return;
    }
    if (await act.run(() => api.put("/settings", body), "Settings saved")) { s.reload(); profile.reload(); }
  };

  return (
    <>
      <PageHeader title="Settings" />
      <Card title="This browser">
        <div className="filters">
          <label className="field">API token (only if IOI_API_TOKEN is set on the server)<input type="password" value={token} onChange={(e) => setTok(e.target.value)} /></label>
          <label className="field">Your name (recorded on approvals & activity)<input value={actor} onChange={(e) => setAct(e.target.value)} /></label>
          <button className="btn" onClick={() => { setToken(token); setActor(actor); local.setMsg({ kind: "ok", text: "Saved in this browser" }); s.reload(); }}>Save</button>
        </div>
        <Msg msg={local.msg} />
      </Card>
      <ErrorBox error={s.error} onRetry={s.reload} />
      {!s.data ? <Loading /> : (
        <>
          <Card title="Runtime (from server environment)">
            <dl className="kv">
              <dt>Access control</dt><dd>{s.data.runtime.auth_mode === "token" ? "Bearer token required" : "Loopback-only (no token configured)"}</dd>
              <dt>AI (OpenRouter)</dt><dd>{s.data.runtime.ai_enabled ? `Enabled · ${s.data.runtime.ai_provider === "claude" ? "Claude" : "OpenRouter"} · ${s.data.runtime.ai_model}` : "Disabled — deterministic rules and templates are used (set IOI_OPENROUTER_API_KEY and IOI_OPENROUTER_MODEL to enable)"}</dd>
              <dt>Reddit API</dt><dd>{s.data.runtime.reddit_configured ? "Credentials configured" : "Not configured (adapter disabled)"}</dd>
              <dt>Scheduler</dt><dd>{s.data.runtime.scheduler.enabled ? `Running · ${s.data.runtime.scheduler.jobs.length} job(s)` : "Off (opt-in: IOI_SCHEDULER_ENABLED=true)"}{s.data.runtime.scheduler.jobs.map((j) => <div key={j.id} className="muted xs">{j.id} → next {j.next_run}</div>)}</dd>
            </dl>
          </Card>
          <Card title="AI assistance (used only when AI is enabled on the server)">
            <div className="muted xs">AI only locates text; every value must match a verbatim quote from the source, and eligibility is still decided by the rules.</div>
            <label className="row gap"><input type="checkbox" checked={aiRefine} onChange={(e) => setAiRefine(e.target.checked)} /> Refine uncertain classifications during collection (max 10 AI calls per source run)</label>
            <label className="row gap"><input type="checkbox" checked={aiDocs} onChange={(e) => setAiDocs(e.target.checked)} /> Document import: fill fields the rules missed and locate requirement clauses</label>
            <label className="row gap">AI review agent: review the top <input type="number" min={0} max={50} style={{ width: 70 }} value={autoReview} onChange={(e) => setAutoReview(Number(e.target.value))} /> new opportunities after each discovery run (0 = off)</label>
          </Card>
          <div className="grid grid-2">
            <Card title="Search terms">
              <textarea rows={14} value={terms} onChange={(e) => setTerms(e.target.value)} />
            </Card>
            <Card title="Country / region priorities (ranking bonus, explicit geography only)">
              <textarea className="mono" rows={14} value={prio} onChange={(e) => setPrio(e.target.value)} />
            </Card>
            <Card title="Research budget">
              <textarea className="mono" rows={12} value={budget} onChange={(e) => setBudget(e.target.value)} />
            </Card>
            <Card title="Business profile overrides">
              <div className="muted xs">Only real, owner-verified facts (e.g. {"{\"gst_registered\": true}"} once registered, or {"{\"annual_turnover_inr\": 1200000}"}). Services cannot be changed here.</div>
              <textarea className="mono" rows={9} value={overrides} onChange={(e) => setOverrides(e.target.value)} />
            </Card>
          </div>
          <div className="row gap"><button className="btn primary" disabled={act.busy} onClick={save}>Save settings</button><Msg msg={act.msg} /></div>
          {profile.data && (
            <Card title="Effective business profile">
              <pre>{JSON.stringify(profile.data.profile, null, 2)}</pre>
            </Card>
          )}
        </>
      )}
    </>
  );
}
