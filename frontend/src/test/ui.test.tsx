import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Shell, NAV } from "../components/Shell";
import { ProspectCard } from "../components/prospect";
import Home from "../pages/Home";
import Discover from "../pages/Discover";
import ProspectDetail from "../pages/ProspectDetail";
import Pipeline from "../pages/Pipeline";
import Prospects from "../pages/Prospects";
import { greeting, rupees } from "../lib/format";
import { mockApi, renderAt } from "./helpers";
import { card, detail, job } from "./fixtures";

const emptyRevenue = { potential: 0, quoted: 0, contracted: 0, advances_received: 0, outstanding: 0, collected_total: 0, collected_this_month: 0 };

describe("format", () => {
  it("formats rupees and greetings", () => {
    expect(rupees(30000)).toBe("₹30,000");
    expect(rupees(null)).toBe("—");
    expect(greeting(9)).toBe("Good morning");
    expect(greeting(14)).toBe("Good afternoon");
    expect(greeting(20)).toBe("Good evening");
  });
});

describe("navigation", () => {
  it("has exactly the six main sections", () => {
    expect(NAV.map((n) => n.label)).toEqual(["Home", "Discover", "Prospects", "Outreach", "Sales Pipeline", "Settings"]);
    render(<MemoryRouter><Shell><p>content</p></Shell></MemoryRouter>);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link")).toHaveLength(6);
  });
});

describe("Home", () => {
  it("shows real zero values and an honest empty state", async () => {
    mockApi({ "/home": { stats: { qualified: 0, new_signals: 0, follow_ups_due: 0, collected_this_month: 0 }, goal: 30000, best: [], revenue: emptyRevenue,
      last_job: null, tasks: { leads_to_review: 0, signals_to_check: 0, follow_ups_due: [], replies: [], proposals: [] } } });
    renderAt("/", "/", <Home />);
    expect(await screen.findByText("No prospects ready yet")).toBeInTheDocument();
    expect(screen.getByText(/IOI never invents leads/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start Discovery/ })).toBeInTheDocument();
    expect(screen.getByText("No discovery run yet")).toBeInTheDocument();
  });

  it("shows collected revenue only from the API", async () => {
    mockApi({ "/home": { stats: { qualified: 1, new_signals: 2, follow_ups_due: 1, collected_this_month: 15000 }, goal: 30000, best: [card],
      revenue: { ...emptyRevenue, quoted: 40000, collected_this_month: 15000, outstanding: 25000 }, last_job: null,
      tasks: { leads_to_review: 1, signals_to_check: 0, follow_ups_due: [], replies: [], proposals: [] } } });
    renderAt("/", "/", <Home />);
    expect(await screen.findByText("Test Biomedical Services")).toBeInTheDocument();
    expect(screen.getAllByText("₹15,000").length).toBeGreaterThan(0);
    expect(screen.getByText("₹25,000")).toBeInTheDocument();
  });

  it("shows a clear error when the server is unreachable", async () => {
    mockApi({ "/home": new Response("boom", { status: 500 }) });
    renderAt("/", "/", <Home />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong (500)");
  });
});

describe("Discover", () => {
  it("shows real stages, counters and failed sources for a running job", async () => {
    mockApi({
      "/discover": { settings: { depth: "balanced", max_candidates: 50, max_deep: 10, daily_shortlist: 5, ai_max_calls: 10 },
        preflight: { checks: [], can_start: true, can_find_new: true }, active: job, history: [job], market_news: [] },
      "/jobs/3": job,
    });
    renderAt("/discover", "/discover", <Discover />);
    expect(await screen.findByText("5. Researching promising candidates")).toBeInTheDocument();
    expect(screen.getByText("18 of 50")).toBeInTheDocument();
    expect(screen.getByText(/1 feed failed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Stop/ })).toBeInTheDocument();
  });

  it("starts a job with the chosen depth", async () => {
    const calls = mockApi({
      "GET /discover": { settings: { depth: "balanced", max_candidates: 50, max_deep: 10, daily_shortlist: 5, ai_max_calls: 10 },
        preflight: { checks: [], can_start: true, can_find_new: true }, active: null, history: [], market_news: [] },
      "POST /jobs": { ...job, status: "queued" },
    });
    renderAt("/discover", "/discover", <Discover />);
    fireEvent.click(await screen.findByText("Quick"));
    fireEvent.click(screen.getByRole("button", { name: /Start Discovery/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/jobs")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ mode: "quick", max_candidates: 50 });
  });
});

describe("Prospect", () => {
  it("card shows evidence summary, qualification and next action", () => {
    render(<MemoryRouter><ProspectCard c={card} /></MemoryRouter>);
    expect(screen.getByText(/P1 · High-fit prospect/)).toBeInTheDocument();
    expect(screen.getByText(/not yet confirmed/)).toBeInTheDocument();
    expect(screen.getByText(/Review and approve for outreach/)).toBeInTheDocument();
    expect(screen.getByText("Test data")).toBeInTheDocument();
  });

  it("detail separates verified facts, hypotheses and unknowns, and approves outreach", async () => {
    const calls = mockApi({ "GET /companies/7": detail,
      "POST /companies/7/approve": { ...detail, review_status: "approved", outreach_approved_by: "owner", outreach_approved_at: "2026-11-23T10:00:00" } });
    renderAt("/prospects/7", "/prospects/:id", <ProspectDetail />);
    expect(await screen.findByRole("heading", { name: "Test Biomedical Services" })).toBeInTheDocument();
    expect(screen.getAllByText("Verified").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Hypothesis").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
    expect(screen.getByText(/No price is suggested/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Approve for Outreach/ }));
    expect(await screen.findByText(/Approved by owner/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/companies/7/approve")).toBe(true);
  });

  it("does not offer approval while checks are missing", async () => {
    mockApi({ "GET /companies/7": { ...detail, gates: [{ key: "chennai", label: "Verified Chennai operation", passed: null, detail: "Not confirmed" }] } });
    renderAt("/prospects/7", "/prospects/:id", <ProspectDetail />);
    expect(await screen.findByText(/Can't approve yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve for Outreach/ })).not.toBeInTheDocument();
  });

  it("list shows an empty Ready-to-Review state", async () => {
    mockApi({ "/companies/counts": { ready: 0, high_fit: 0, watchlist: 0, all: 0, approved: 0, rejected: 0 }, "/companies": { items: [], total: 0, offset: 0, limit: 20 } });
    renderAt("/prospects", "/prospects", <Prospects />);
    expect(await screen.findByText("Nothing waiting for review")).toBeInTheDocument();
  });
});

describe("Pipeline", () => {
  it("moves a deal to the next stage", async () => {
    const deal = { id: 1, company_id: 7, company: "Test Biomedical Services", stage: "contacted", outcome: null, contact_name: null, confirmed_requirement: null,
      offer: "ServiceFlow Setup", potential_amount: null, quoted_amount: null, expected_payment_date: null, delivery_status: null, next_follow_up_at: null,
      notes: null, collected: 0, outstanding: 0, payments: [], updated_at: "2026-11-23T10:00:00" };
    const calls = mockApi({
      "GET /pipeline": { stages: [{ key: "new_prospect", label: "New Prospect" }, { key: "contacted", label: "Contacted" }, { key: "replied", label: "Replied" }],
        outcomes: [], deals: [deal], revenue: emptyRevenue, goal: 30000 },
      "POST /deals/1/stage": { ...deal, stage: "replied" },
    });
    renderAt("/pipeline", "/pipeline", <Pipeline />);
    fireEvent.click(await screen.findByRole("button", { name: "Move Test Biomedical Services forward" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ stage: "replied" }));
  });
});
