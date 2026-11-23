import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AgentTrace, AIChip } from "../components/intel";
import { Shell } from "../components/Shell";
import ProspectDetail from "../pages/ProspectDetail";
import Research from "../pages/Research";
import { mockApi, renderAt } from "./helpers";
import { card, detail } from "./fixtures";

const aiOff = { configured: false, provider: null, model: null, agent_supported: false, note: "AI unavailable — rule-based research active.",
  last_success: null, last_error: null, fallback: "Rule-based research continues", usage_24h: { calls: 0, tokens_in: 0, tokens_out: 0, cost_usd: 0 },
  usage_30d: { calls: 0, tokens_in: 0, tokens_out: 0, cost_usd: 0 }, limits: { max_model_calls: 6, max_tool_calls: 14, max_pages: 6, max_seconds: 150, max_cost_usd: 0.03 } };

describe("AI observability", () => {
  it("says plainly when AI is unavailable", async () => {
    mockApi({ "/ai/status": aiOff });
    render(<AIChip />);
    expect(await screen.findByText("AI unavailable — rule-based research active")).toBeInTheDocument();
  });

  it("shows connected AI with the model", async () => {
    mockApi({ "/ai/status": { ...aiOff, configured: true, agent_supported: true, provider: "OpenRouter", model: "openrouter/auto" } });
    render(<AIChip />);
    expect(await screen.findByText(/AI connected · openrouter\/auto/)).toBeInTheDocument();
  });

  it("renders only real tool events, including rejections", () => {
    render(<AgentTrace events={detail.agent_events} />);
    expect(screen.getByText("Checked official company page /about")).toBeInTheDocument();
    expect(screen.getByText("Rejected an unsupported claim (quote not found on the page)")).toBeInTheDocument();
    render(<AgentTrace events={[]} empty="Nothing yet" />);
    expect(screen.getByText("Nothing yet")).toBeInTheDocument();
  });
});

describe("Company dossier", () => {
  it("shows classifications, key questions, published people and the AI trace", async () => {
    mockApi({ "GET /companies/7": detail, "/ai/status": aiOff });
    renderAt("/prospects/7", "/prospects/:id", <ProspectDetail />);
    expect(await screen.findByText("Key questions")).toBeInTheDocument();
    expect(screen.getByText("Operational fit")).toBeInTheDocument();
    expect(screen.getByText("Hypothesis — not confirmed by the buyer.")).toBeInTheDocument();
    expect(screen.getByText("R. Kumar")).toBeInTheDocument();
    expect(screen.getByText("Service-heavy lab equipment firm.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry AI research" })).toBeInTheDocument();
  });

  it("runs AI research on demand and reports the outcome", async () => {
    const calls = mockApi({ "GET /companies/7": { ...detail, ai_status: "not_run", dossier: {}, agent_events: [] }, "/ai/status": aiOff,
      "POST /companies/7/ai-research": { ...detail, ai_status: "unavailable", dossier: {} } });
    renderAt("/prospects/7", "/prospects/:id", <ProspectDetail />);
    fireEvent.click(await screen.findByRole("button", { name: "Research with AI" }));
    expect(await screen.findByText(/AI research: unavailable/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/companies/7/ai-research")).toBe(true);
  });
});

describe("Research page", () => {
  it("lists dossiers and runs", async () => {
    mockApi({ "/research": { total: 1, items: [{ ...card, people: 1, testimonials: 2, research_error: null, ai_researched_at: "2026-11-20T10:00:00", agent_outcome: "partial" }],
      jobs: [] }, "/ai/status": aiOff });
    renderAt("/research", "/research", <Research />);
    expect(await screen.findByText("Test Biomedical Services")).toBeInTheDocument();
    expect(screen.getByText("2 testimonials")).toBeInTheDocument();
  });

  it("has a helpful empty state", async () => {
    mockApi({ "/research": { total: 0, items: [], jobs: [] }, "/ai/status": aiOff });
    renderAt("/research", "/research", <Research />);
    expect(await screen.findByText("No dossiers yet")).toBeInTheDocument();
  });
});

describe("Theme", () => {
  it("is dark by default and remembers light", async () => {
    try { localStorage.removeItem("ioi_theme"); } catch { /* jsdom without storage */ }
    document.documentElement.classList.remove("dark");
    render(<MemoryRouter><Shell><p>x</p></Shell></MemoryRouter>);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Toggle dark mode" })[0]); });
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
