import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import "./styles.css";
import Overview from "./pages/Overview";
import Discover from "./pages/Discover";
import Opportunities from "./pages/Opportunities";
import OpportunityDetail from "./pages/OpportunityDetail";
import Organisations, { OrganisationDetail } from "./pages/Organisations";
import VendorIntelligence from "./pages/VendorIntelligence";
import Eligibility from "./pages/Eligibility";
import Chains from "./pages/Chains";
import EvidenceViewer from "./pages/EvidenceViewer";
import ResearchQueue from "./pages/ResearchQueue";
import Outreach from "./pages/Outreach";
import FollowUps from "./pages/FollowUps";
import Sources from "./pages/Sources";
import SettingsPage from "./pages/Settings";

const NAV: { group?: string; to: string; label: string }[] = [
  { to: "/", label: "Overview" },
  { to: "/discover", label: "Discover" },
  { group: "Pipeline", to: "/opportunities", label: "Opportunities" },
  { to: "/organisations", label: "Organisations" },
  { to: "/vendor", label: "Vendor Intelligence" },
  { to: "/eligibility", label: "Eligibility" },
  { to: "/chains", label: "Opportunity Chains" },
  { to: "/evidence", label: "Evidence Viewer" },
  { group: "Work", to: "/research", label: "Research Queue" },
  { to: "/outreach", label: "Outreach" },
  { to: "/follow-ups", label: "Follow-ups" },
  { group: "System", to: "/sources", label: "Sources" },
  { to: "/settings", label: "Settings" },
];

function Shell() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  return (
    <div className="layout">
      <div className="mobile-bar">
        <button className="btn sm" onClick={() => setOpen((o) => !o)} aria-label="Toggle navigation">
          ☰
        </button>
        <strong>Inferago IOI</strong>
      </div>
      <aside className={`sidebar ${open ? "open" : ""}`} onClick={() => setOpen(false)}>
        <div className="brand">Inferago IOI</div>
        <div className="brand-sub">Opportunity Intelligence · internal</div>
        <nav className="nav">
          {NAV.map((n) => (
            <div key={n.to}>
              {n.group && <div className="group">{n.group}</div>}
              <NavLink to={n.to} end={n.to === "/"}>
                {n.label}
              </NavLink>
            </div>
          ))}
        </nav>
      </aside>
      <main className="main" key={loc.pathname}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/discover" element={<Discover />} />
          <Route path="/opportunities" element={<Opportunities />} />
          <Route path="/opportunities/:id" element={<OpportunityDetail />} />
          <Route path="/organisations" element={<Organisations />} />
          <Route path="/organisations/:id" element={<OrganisationDetail />} />
          <Route path="/vendor" element={<VendorIntelligence />} />
          <Route path="/eligibility" element={<Eligibility />} />
          <Route path="/chains" element={<Chains />} />
          <Route path="/evidence" element={<EvidenceViewer />} />
          <Route path="/research" element={<ResearchQueue />} />
          <Route path="/outreach" element={<Outreach />} />
          <Route path="/follow-ups" element={<FollowUps />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<div className="empty">Page not found</div>} />
        </Routes>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </StrictMode>,
);
