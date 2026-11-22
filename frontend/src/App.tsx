import { useState } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { Shell } from "./components/Shell";
import { Badge, Button, Card, Input, Spinner } from "./components/ui";
import { api, setToken } from "./lib/api";
import { useQuery } from "./lib/hooks";
import Home from "./pages/Home";
import Discover from "./pages/Discover";
import Prospects from "./pages/Prospects";
import ProspectDetail from "./pages/ProspectDetail";
import Outreach from "./pages/Outreach";
import Pipeline from "./pages/Pipeline";
import Settings from "./pages/Settings";
import Onboarding from "./pages/Onboarding";
import type { Preflight } from "./lib/types";

export interface Status { ok: boolean; onboarding_done: boolean; preflight: Preflight; ai_configured: boolean; worker_alive: boolean }

function SignIn({ onDone }: { onDone: () => void }) {
  const [t, setT] = useState("");
  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <Card className="w-full max-w-sm" title="Sign in to IOI" description="Paste the access token from your .env file (IOI_API_TOKEN).">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); setToken(t.trim()); onDone(); }}>
          <Input type="password" value={t} onChange={(e) => setT(e.target.value)} placeholder="Access token" autoFocus aria-label="Access token" />
          <Button variant="primary" className="w-full" type="submit"><KeyRound className="h-4 w-4" />Sign in</Button>
        </form>
      </Card>
    </div>
  );
}

function StatusDot({ s, error }: { s?: Status; error?: boolean }) {
  if (error) return <Badge tone="bad">Server offline</Badge>;
  if (!s) return null;
  if (!s.worker_alive) return <Badge tone="warn" title="Discovery worker is not running">Worker stopped</Badge>;
  if (!s.preflight.can_find_new) return <Badge tone="warn" title="Business directory file missing">Setup needed</Badge>;
  return <Badge tone="ok">Ready</Badge>;
}

export default function App() {
  const status = useQuery(() => api.get<Status>("/status"), [], 30000);
  const nav = useNavigate();
  if (status.error?.status === 401) return <SignIn onDone={() => status.reload()} />;
  if (!status.data && status.loading) return <div className="flex min-h-full items-center justify-center"><Spinner label="Starting IOI…" /></div>;
  if (!status.data) {
    return (
      <div className="flex min-h-full items-center justify-center p-4">
        <Card className="max-w-md" title="IOI server is not reachable">
          <p className="text-sm text-subtle">{status.error?.message}</p>
          <p className="mt-2 text-sm text-subtle">Start it with <code className="rounded bg-muted px-1">./start.sh</code> (Windows: <code className="rounded bg-muted px-1">start.ps1</code>), then try again.</p>
          <Button className="mt-4" onClick={() => status.reload()}>Try again</Button>
        </Card>
      </div>
    );
  }
  if (!status.data.onboarding_done) {
    return <Onboarding status={status.data} onDone={async () => { await status.reload(); nav("/"); }} />;
  }
  return (
    <Shell status={<StatusDot s={status.data} error={!!status.error} />}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/discover" element={<Discover />} />
        <Route path="/prospects" element={<Prospects />} />
        <Route path="/prospects/:id" element={<ProspectDetail />} />
        <Route path="/outreach" element={<Outreach />} />
        <Route path="/pipeline" element={<Pipeline />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<p className="text-subtle">Page not found.</p>} />
      </Routes>
    </Shell>
  );
}
