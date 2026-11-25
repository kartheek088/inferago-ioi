import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Ext, isWebUrl } from "../components/ui";
import RecoveryDashboard, { STATUS } from "../pages/recovery/Dashboard";
import { mockApi, renderAt } from "./helpers";

const overview = {
  businesses_discovered: 3, with_own_website: 2, websites_checked: 2, checks_recorded: 2,
  by_status: { unhealthy_suspected: 1, access_restricted: 1 }, failures_detected: 1, pending_confirmation: 1, confirmed: 0,
  high_priority: 0, needs_verification: 2, migrated: 0, excluded: 0, r0: 0, r1: 0, active_verified: 0,
  alternatives_found: 0, with_usable_contact: 1, scope: { categories: null, window_days: 90 },
};
const scope = { categories: null, window_days: 90, available: [{ industry: "equipment_sales_service", category: "hvac_service", count: 4 }] };

const item = (over: Record<string, unknown> = {}) => ({
  company_id: 1, name: "Sharma Engineering", locality: "Adyar", business_type: "hvac_service", website: "https://sharma.example/",
  status: "access_restricted", observed_class: null, confidence: "high",
  reasons: ["HTTP 403: access restricted, not evidence of an outage"], checked_at: new Date().toISOString(),
  qualification: "R2", bucket: "needs_verification", summary: "Still to check: Website failure confirmed", activity: "activity_unclear", ...over,
});

const dossier = {
  company: { id: 1, name: "Sharma Engineering", website: "https://sharma.example/", business_type: "hvac_service", location_confidence: "partial", location_reason: null },
  checks: [],
  qualification: { category: "R2", bucket: "needs_verification", summary: "Still to check: Business currently operating", friction: ["Existing web vendor: unknown"],
    gates: [{ key: "failure", label: "Website failure confirmed", passed: true, detail: "Same failure seen twice" },
            { key: "operating", label: "Business currently operating", passed: false, detail: "Not verified" }] },
  activity: { status: "activity_unclear", reasons: ["No dated evidence yet"], window_days: 90, manual: [], automatic: [] },
  alternatives: [],
  contacts: [{ id: 5, kind: "phone", kind_label: "mobile", value: "+91 98400 12345", route: "directory", source_url: "https://example.test/",
    needs_review: "Mobile number from a directory — it may be a person's own number. Check before use.", usable: false,
    reviewable: true, review: null }],
  check_yourself: [{ label: "Google", url: "https://www.google.com/search?q=%22Sharma%22" }],
};

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
    mockApi({ "/recovery/overview": overview, "/recovery/scope": scope, "/recovery/companies": { tab: "high_priority", items: [] } });
    renderAt("/website-recovery", "/website-recovery", <RecoveryDashboard />);
    expect(await screen.findByRole("heading", { name: "Website Recovery" })).toBeInTheDocument();
    expect(await screen.findByText(/No R0\/R1 leads yet/)).toBeInTheDocument();
    expect(screen.getByText(/never visits Facebook, Instagram, IndiaMART or Justdial/)).toBeInTheDocument();
    expect(screen.getByText("1 waiting for the 24 h recheck")).toBeInTheDocument();
  });

  it("lists a bot-blocked site as access restricted, and runs a bounded check", async () => {
    const calls = mockApi({
      "/recovery/overview": overview, "/recovery/scope": scope,
      "/recovery/companies": { tab: "high_priority", items: [item()] },
      "POST /recovery/check": { checked: 1, skipped_recent: 0, failures_detected: 0, confirmed: 0, network_failures: 0,
        access_restricted: 1, errors: 0, alternatives_working: 0 },
    });
    renderAt("/website-recovery", "/website-recovery", <RecoveryDashboard />);
    expect(await screen.findByText("Sharma Engineering")).toBeInTheDocument();
    expect(screen.getByText("Website access restricted")).toBeInTheDocument();
    expect(screen.queryByText("Website failure confirmed")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Check next 10 websites/ }));
    await waitFor(() => expect(screen.getByText(/This run: 1 checked/)).toBeInTheDocument());
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ limit: 10, force: false });
  });

  it("opens the dossier: gates, review-flagged contacts, and records a call", async () => {
    const calls = mockApi({
      "/recovery/overview": overview, "/recovery/scope": scope,
      "/recovery/companies": { tab: "high_priority", items: [item()] },
      "/recovery/companies/1": dossier,
      "POST /recovery/companies/1/evidence": { id: 9 },
    });
    renderAt("/website-recovery", "/website-recovery", <RecoveryDashboard />);
    fireEvent.click(await screen.findByRole("button", { name: /Sharma Engineering/ }));
    expect(await screen.findByText("Business currently operating")).toBeInTheDocument();
    expect(screen.getByLabelText("not passed")).toBeInTheDocument();
    expect(screen.getByText(/may be a person's own number/)).toBeInTheDocument();

    const form = screen.getByRole("form", { name: "Record what you verified" });
    fireEvent.change(form.querySelector("textarea")!, { target: { value: "Answered, still trading" } });
    fireEvent.click(within(form).getByRole("checkbox"));
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/evidence"))).toBe(true));
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/evidence"));
    expect(post?.body).toMatchObject({ kind: "phone_call", signal: "active", statement: "Answered, still trading", confirms_chennai: true, published_on: null });
  });

  it("lets the owner approve a flagged contact as the business line", async () => {
    const calls = mockApi({
      "/recovery/overview": overview, "/recovery/scope": scope,
      "/recovery/companies": { tab: "high_priority", items: [item()] },
      "/recovery/companies/1": dossier,
      "POST /recovery/contacts/5/review": { id: 5, usable: true, review: "approved" },
    });
    renderAt("/website-recovery", "/website-recovery", <RecoveryDashboard />);
    fireEvent.click(await screen.findByRole("button", { name: /Sharma Engineering/ }));
    fireEvent.click(await screen.findByRole("button", { name: "It's the business line" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/recovery/contacts/5/review")).toBe(true));
    expect(calls.find((c) => c.url === "/recovery/contacts/5/review")?.body).toEqual({ decision: "approved" });
  });
});

describe("local dates", () => {
  it("uses the local calendar date, not the UTC one", async () => {
    const { today } = await import("../pages/recovery/Dossier");
    expect(today(new Date(2026, 10, 26, 3, 37))).toBe("2026-11-26");
  });
});
