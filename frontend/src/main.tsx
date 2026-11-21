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
import Today from "./pages/Today";
import Prospects from "./pages/Prospects";
import BigProjects from "./pages/BigProjects";

const MAIN_NAV: { to: string; label: string; icon: string; hint: string }[] = [
  { to: "/", label: "Today", icon: "☀️", hint: "What to do now" },
  { to: "/prospects", label: "Prospects", icon: "🎯", hint: "Businesses that need us" },
  { to: "/big-projects", label: "Big projects", icon: "🏗️", hint: "Companies with new projects — approach as a vendor" },
  { to: "/opportunities", label: "Projects & tenders", icon: "📋", hint: "People asking for work" },
  { to: "/outreach", label: "Messages", icon: "✉️", hint: "Drafts to approve" },
  { to: "/follow-ups", label: "Follow-ups", icon: "⏰", hint: "Calls & reminders" },
];

const MORE_NAV: { to: string; label: string }[] = [
  { to: "/discover", label: "Search for projects" },
  { to: "/stats", label: "Stats" },
  { to: "/organisations", label: "Organisations" },
  { to: "/vendor", label: "Vendor & partner programmes" },
  { to: "/eligibility", label: "Eligibility checks" },
  { to: "/chains", label: "Connections" },
  { to: "/research", label: "Research queue" },
  { to: "/evidence", label: "Raw evidence" },
  { to: "/sources", label: "Sources" },
  { to: "/settings", label: "Settings" },
];

function readMoreOpen(): boolean {
  try { return localStorage.getItem("ioi_more_open") === "1"; } catch { return false; }
}

function Shell() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const inMore = MORE_NAV.some((n) => loc.pathname.startsWith(n.to));
  const [moreOpen, setMoreOpen] = useState(readMoreOpen);
  const toggleMore = () => {
    setMoreOpen((v) => {
      try { localStorage.setItem("ioi_more_open", v ? "0" : "1"); } catch { /* ignore */ }
      return !v;
    });
  };
  return (
    <div className="layout">
      <div className="mobile-bar">
        <button className="btn sm" onClick={() => setOpen((o) => !o)} aria-label="Toggle navigation">
          ☰
        </button>
        <strong>Inferago</strong>
      </div>
      <aside className={`sidebar ${open ? "open" : ""}`} onClick={() => setOpen(false)}>
        <div className="brand"><span className="logo">i</span>Inferago</div>
        <div className="brand-sub">Find clients · win work</div>
        <nav className="nav">
          {MAIN_NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} title={n.hint}>
              <span className="nav-icon" aria-hidden>{n.icon}</span>
              <span>{n.label}</span>
            </NavLink>
          ))}
          <button className={`more-toggle ${moreOpen || inMore ? "open" : ""}`} onClick={(e) => { e.stopPropagation(); toggleMore(); }} aria-expanded={moreOpen || inMore}>
            <span>More tools</span><span aria-hidden>{moreOpen || inMore ? "▾" : "▸"}</span>
          </button>
          {(moreOpen || inMore) && (
            <div className="more">
              {MORE_NAV.map((n) => <NavLink key={n.to} to={n.to}>{n.label}</NavLink>)}
            </div>
          )}
        </nav>
      </aside>
      <main className="main" key={loc.pathname}>
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/prospects" element={<Prospects />} />
          <Route path="/big-projects" element={<BigProjects />} />
          <Route path="/stats" element={<Overview />} />
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
