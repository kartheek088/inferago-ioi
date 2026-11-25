import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Ext, isWebUrl } from "../components/ui";
import RecoveryDashboard, { STATUS } from "../pages/recovery/Dashboard";
import { mockApi, renderAt } from "./helpers";

const overview = {
  businesses_discovered: 3, with_own_website: 2, websites_checked: 2, checks_recorded: 2,
  by_status: { healthy: 0, unhealthy_confirmed: 0, unhealthy_suspected: 1, access_restricted: 1 },
  high_priority: 0, needs_verification: 2, migrated: 0, excluded: 0,
};

const item = (over: Record<string, unknown>) => ({
  company_id: 1, name: "Sharma Engineering", locality: "Adyar", website: "https://sharma.example/",
  status: "access_restricted", observed_class: null, confidence: "high",
  reasons: ["HTTP 403 or bot challenge: access restricted, not evidence of an outage"],
  final_url: null, http_status: 403, checked_at: new Date().toISOString(), ...over,
});

describe("external links", () => {
  it("only makes http(s) URLs clickable", () => {
    expect(isWebUrl("https://sharma.example/")).toBe(true);
    expect(isWebUrl("http://sharma.example/")).toBe(true);
    expect(isWebUrl("javascript:alert(1)")).toBe(false);
    expect(isWebUrl("data:text/html,<script>x</script>")).toBe(false);
    expect(isWebUrl("not a url")).toBe(false);
    const { container } = render(<Ext href="javascript:alert(1)">bad</Ext>);
    expect(container.querySelector("a")).toBeNull();
  });
});

describe("Website Recovery", () => {
  it("never labels an access restriction as an outage", () => {
    expect(STATUS.access_restricted.label).not.toMatch(/fail|down|unavailable/i);
    expect(STATUS.network_failure.label).toMatch(/could not verify/i);
  });

  it("shows real counts and an honest empty High-Priority tab", async () => {
    mockApi({ "/recovery/overview": overview, "/recovery/companies": { tab: "high_priority", items: [] } });
    renderAt("/website-recovery", "/website-recovery", <RecoveryDashboard />);
    expect(await screen.findByRole("heading", { name: "Website Recovery" })).toBeInTheDocument();
    expect(await screen.findByText(/No confirmed failures/)).toBeInTheDocument();
    expect(screen.getByText(/not built yet/)).toBeInTheDocument();
  });

  it("lists a bot-blocked site as access restricted, and runs a bounded check", async () => {
    const calls = mockApi({
      "/recovery/overview": overview,
      "/recovery/companies": { tab: "needs_verification", items: [item({})] },
      "POST /recovery/check": { checked: 1, skipped_recent: 0, failures_detected: 0, confirmed: 0, network_failures: 0,
        blocked_by_policy: 0, access_restricted: 1, errors: 0, results: [] },
    });
    renderAt("/website-recovery", "/website-recovery", <RecoveryDashboard />);
    expect(await screen.findByText("Sharma Engineering")).toBeInTheDocument();
    expect(screen.getByText("Website access restricted")).toBeInTheDocument();
    expect(screen.queryByText("Website failure confirmed")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Check next 10 websites/ }));
    await waitFor(() => expect(screen.getByText(/This run: 1 checked/)).toBeInTheDocument());
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ limit: 10, force: false });
  });
});
