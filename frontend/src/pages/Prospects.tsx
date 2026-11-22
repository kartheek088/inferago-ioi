import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, Search, Upload, Users } from "lucide-react";
import { Button, Empty, ErrorState, Field, Input, Modal, Msg, PageHeader, Select, Spinner, Tabs } from "../components/ui";
import { ProspectCard } from "../components/prospect";
import { api } from "../lib/api";
import { useAction, useQuery } from "../lib/hooks";
import { FRICTION, INDUSTRY } from "../lib/format";
import type { CompanyCard } from "../lib/types";

type Tab = "ready" | "high_fit" | "watchlist" | "all" | "approved" | "rejected";
interface Page { items: CompanyCard[]; total: number; offset: number; limit: number }

export default function Prospects() {
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get("tab") as Tab) || "ready";
  const [f, setF] = useState({ industry: "", qualification: "", confidence: "", friction: "", signal_days: "", contact: "", q: "" });
  const [offset, setOffset] = useState(0);
  const counts = useQuery(() => api.get<Record<string, number>>("/companies/counts"), []);
  const list = useQuery(() => api.get<Page>("/companies", { tab, ...f, offset, limit: 20 }), [tab, JSON.stringify(f), offset]);
  const act = useAction();
  const [addOpen, setAddOpen] = useState(false);
  const [csvOpen, setCsvOpen] = useState(false);
  const set = (k: keyof typeof f, v: string) => { setF({ ...f, [k]: v }); setOffset(0); };
  const refresh = () => { list.reload(); counts.reload(); };
  const quick = async (id: number, path: string, ok: string) => {
    const r = await act.run(() => api.post<{ research_error?: string | null }>(`/companies/${id}/${path}`, {}));
    if (r) { act.setMsg(r.research_error && path === "research" ? { kind: "err", text: r.research_error } : { kind: "ok", text: ok }); refresh(); }
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "ready", label: "Ready to Review" }, { id: "high_fit", label: "High-Fit Prospects" }, { id: "watchlist", label: "Watchlist" },
    { id: "all", label: "All Businesses" }, { id: "approved", label: "Approved" }, { id: "rejected", label: "Excluded" },
  ];
  return (
    <>
      <PageHeader title="Prospects" description="Review what discovery found. Facts are marked Verified; guesses are marked Hypothesis."
        actions={<>
          <Button onClick={() => setCsvOpen(true)}><Upload className="h-4 w-4" />Import CSV</Button>
          <Button variant="primary" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" />Add business</Button>
        </>} />
      <Tabs tabs={tabs.map((t) => ({ ...t, count: counts.data?.[t.id] }))} value={tab} onChange={(t) => { setSp({ tab: t }); setOffset(0); }} />
      <div className="my-4 flex flex-wrap gap-2">
        <div className="relative min-w-[12rem] flex-1">
          <Search className="absolute left-3 top-3 h-4 w-4 text-subtle" />
          <Input className="pl-9" placeholder="Search name or area" value={f.q} onChange={(e) => set("q", e.target.value)} aria-label="Search" />
        </div>
        <Select value={f.industry} onChange={(e) => set("industry", e.target.value)} aria-label="Industry">
          <option value="">Both industries</option>{Object.entries(INDUSTRY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <Select value={f.qualification} onChange={(e) => set("qualification", e.target.value)} aria-label="Qualification">
          <option value="">Any qualification</option><option value="P0">P0 · Confirmed</option><option value="P1">P1 · High-fit</option><option value="P2">P2 · Watchlist</option><option value="P3">P3 · Excluded</option>
        </Select>
        <Select value={f.confidence} onChange={(e) => set("confidence", e.target.value)} aria-label="Location evidence">
          <option value="">Any location evidence</option><option value="verified">Verified</option><option value="partial">Partly verified</option><option value="unknown">Unknown</option>
        </Select>
        <Select value={f.signal_days} onChange={(e) => set("signal_days", e.target.value)} aria-label="Signal recency">
          <option value="">Any signal age</option><option value="30">Signal ≤ 30 days</option><option value="90">Signal ≤ 90 days</option><option value="180">Signal ≤ 180 days</option>
        </Select>
        <Select value={f.friction} onChange={(e) => set("friction", e.target.value)} aria-label="Sales friction">
          <option value="">Any friction</option>{Object.entries(FRICTION).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <Select value={f.contact} onChange={(e) => set("contact", e.target.value)} aria-label="Contact">
          <option value="">Contact: any</option><option value="true">Has contact</option><option value="false">No contact</option>
        </Select>
      </div>
      <Msg msg={act.msg} />
      <ErrorState error={list.error} onRetry={list.reload} />
      {!list.data ? <Spinner /> : list.data.items.length === 0 ? (
        <Empty icon={<Users className="h-6 w-6" />} title={tab === "ready" ? "Nothing waiting for review" : "No businesses here"}
          action={<Link to="/discover"><Button variant="primary">Go to Discover</Button></Link>}>
          {tab === "ready" ? "Discovery shortlists businesses that pass every check. Run discovery, or look in Watchlist for businesses that need one more check." : "Try another tab or clear the filters."}
        </Empty>
      ) : (
        <div className="space-y-3">
          {list.data.items.map((c) => (
            <ProspectCard key={c.id} c={c} actions={<>
              <Link to={`/prospects/${c.id}`}><Button size="sm">Open details</Button></Link>
              {c.sales_ready && c.review_status !== "approved" && <Link to={`/prospects/${c.id}#outreach`}><Button size="sm" variant="success">Approve for Outreach</Button></Link>}
              {c.review_status !== "watchlist" && c.qualification !== "P3" && <Button size="sm" variant="ghost" disabled={act.busy} onClick={() => quick(c.id, "review/watchlist", "Moved to watchlist")}>Move to Watchlist</Button>}
              {c.research_level === "directory" && c.website && <Button size="sm" variant="ghost" disabled={act.busy} onClick={() => quick(c.id, "research", "Research finished")}>Research further</Button>}
              {c.review_status !== "rejected" && <Button size="sm" variant="danger" disabled={act.busy} onClick={() => quick(c.id, "review/reject", "Rejected")}>Reject</Button>}
              {c.review_status === "rejected" && <Button size="sm" disabled={act.busy} onClick={() => quick(c.id, "review/restore", "Restored")}>Restore</Button>}
            </>} />
          ))}
          <div className="flex items-center justify-between pt-2 text-sm text-subtle">
            <span>{list.data.total === 0 ? 0 : offset + 1}–{Math.min(offset + list.data.limit, list.data.total)} of {list.data.total}</span>
            <div className="flex gap-2">
              <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</Button>
              <Button size="sm" disabled={offset + 20 >= list.data.total} onClick={() => setOffset(offset + 20)}>Next</Button>
            </div>
          </div>
        </div>
      )}
      <AddBusiness open={addOpen} onClose={() => setAddOpen(false)} onDone={refresh} />
      <ImportCsv open={csvOpen} onClose={() => setCsvOpen(false)} onDone={refresh} />
    </>
  );
}

function AddBusiness({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const empty = { name: "", industry: "", address: "", website: "", phone: "", email: "", source_url: "", location_evidence_url: "", note: "" };
  const [f, setF] = useState(empty);
  const act = useAction();
  const save = async () => {
    const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() || null]));
    if (await act.run(() => api.post("/companies", body), "Added")) { setF(empty); onDone(); onClose(); }
  };
  const inp = (k: keyof typeof empty, label: string, hint?: string) => (
    <Field label={label} hint={hint}><Input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>
  );
  return (
    <Modal open={open} onClose={onClose} title="Add a business you found"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={act.busy} disabled={!f.name || !f.source_url} onClick={save}>Add</Button></>}>
      <p className="text-sm text-subtle">For businesses you found yourself — a LinkedIn post, a trade-fair list, an IndiaMART page. It goes through the same checks.</p>
      {inp("name", "Business name *")}
      <Field label="Industry"><Select className="w-full" value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })}>
        <option value="">Work it out from the name</option>{Object.entries(INDUSTRY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </Select></Field>
      {inp("address", "Address", "Include the area and PIN, e.g. 'Guindy, Chennai 600032'")}
      {inp("website", "Official website")}
      <div className="grid gap-3 sm:grid-cols-2">{inp("phone", "Public business phone")}{inp("email", "Public business email")}</div>
      {inp("source_url", "Where you found it (link) *")}
      {inp("location_evidence_url", "Page on their website showing the Chennai address", "Optional — if given, the location counts as verified")}
      {inp("note", "What you saw (optional)")}
      <Msg msg={act.msg} />
    </Modal>
  );
}

function ImportCsv({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [src, setSrc] = useState("");
  const [result, setResult] = useState<Record<string, number | string[]> | null>(null);
  const act = useAction();
  const go = async () => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    if (src) fd.append("source_url", src);
    const r = await act.run(() => api.upload<Record<string, number | string[]>>("/import/csv", fd));
    if (r) { setResult(r); onDone(); }
  };
  return (
    <Modal open={open} onClose={() => { setResult(null); onClose(); }} title="Import an authorised CSV list"
      footer={<Button variant="primary" loading={act.busy} disabled={!file} onClick={go}>Import</Button>}>
      <p className="text-sm text-subtle">Only lists you are allowed to use (e.g. an exhibitor or association list you received). Columns: <code>name</code> (required), address, website, phone, email, category, industry, source_url, note.</p>
      <Input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="CSV file" />
      <Field label="Where this list came from (link)" hint="Used for rows without their own source_url"><Input value={src} onChange={(e) => setSrc(e.target.value)} /></Field>
      <Msg msg={act.msg} />
      {result && (
        <div className="rounded-lg bg-muted p-3 text-sm">
          {String(result.rows)} rows · {String(result.accepted)} added · {String(result.outside_chennai)} outside Chennai · {String(result.wrong_industry)} other industries · {String(result.duplicate)} duplicates
          {Array.isArray(result.errors) && result.errors.length > 0 && <ul className="mt-2 list-disc pl-5 text-bad">{result.errors.slice(0, 5).map((e) => <li key={e}>{e}</li>)}</ul>}
        </div>
      )}
    </Modal>
  );
}
