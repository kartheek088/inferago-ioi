import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import SocialDashboard from "../pages/social/Dashboard";
import SocialLeads from "../pages/social/Leads";
import SocialLeadDetail from "../pages/social/LeadDetail";
import SocialActivityFeed from "../pages/social/ActivityFeed";
import SocialDiscoverPage from "../pages/social/Discover";
import { mockApi, renderAt } from "./helpers";
import { sellerCard, sellerDetail, socialDiscover, socialOverview } from "./social-fixtures";

describe("Social Commerce dashboard", () => {
  it("shows the heading, subtitle and the primary action", async () => {
    mockApi({ "/social/overview": socialOverview });
    renderAt("/social-commerce", "/social-commerce", <SocialDashboard />);
    expect(await screen.findByRole("heading", { name: "Social Commerce Intelligence" })).toBeInTheDocument();
    expect(screen.getByText(/Discover growing Chennai businesses selling through Instagram, Facebook and WhatsApp/))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Find Social Commerce Businesses/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add Business\/Profile/ })).toBeInTheDocument();
  });

  it("shows real zeros and an honest empty state with no data", async () => {
    mockApi({ "/social/overview": { ...socialOverview, stats: { ...socialOverview.stats, discovered: 0, high_fit: 0, verified_sellers: 0 } } });
    renderAt("/social-commerce", "/social-commerce", <SocialDashboard />);
    expect(await screen.findByText("No social sellers yet")).toBeInTheDocument();
    expect(screen.getByText(/Adding a profile by hand always works/)).toBeInTheDocument();
  });

  it("never invents counters — every number comes from the API", async () => {
    mockApi({ "/social/overview": socialOverview });
    renderAt("/social-commerce", "/social-commerce", <SocialDashboard />);
    expect(await screen.findByText("Businesses discovered")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument(); // discovered
    expect(screen.getByText("₹6,000")).toBeInTheDocument(); // collected
  });

  it("says plainly that Instagram and Facebook are never fetched automatically", async () => {
    mockApi({ "/social/overview": socialOverview });
    renderAt("/social-commerce", "/social-commerce", <SocialDashboard />);
    expect(await screen.findByText(/need you to look/)).toBeInTheDocument();
    expect(screen.getByText(/only to signed-in visitors, so IOI never fetches them/)).toBeInTheDocument();
  });

  it("lists sources that are unavailable instead of hiding them", async () => {
    mockApi({ "/social/overview": socialOverview });
    renderAt("/social-commerce", "/social-commerce", <SocialDashboard />);
    expect(await screen.findByText("Sources that are not available")).toBeInTheDocument();
    expect(screen.getByText(/No search API is configured/)).toBeInTheDocument();
  });
});

describe("Social discovery", () => {
  it("reports the search API as unavailable without a key", async () => {
    mockApi({ "/social/discover": socialDiscover, "/social/jobs": { items: [] } });
    renderAt("/social-commerce/discover", "/social-commerce/discover", <SocialDiscoverPage />);
    expect(await screen.findByText(/Public web search is not available/)).toBeInTheDocument();
    expect(screen.getAllByText(/IOI_SEARCH_PROVIDER/).length).toBeGreaterThan(0);
  });

  it("offers the real discovery modes and a start button", async () => {
    mockApi({ "/social/discover": socialDiscover, "/social/jobs": { items: [] } });
    renderAt("/social-commerce/discover", "/social-commerce/discover", <SocialDiscoverPage />);
    expect(await screen.findByRole("button", { name: /Find Social Sellers/ })).toBeInTheDocument();
    const modes = screen.getByLabelText("How deep");
    expect(within(modes).getAllByRole("option").map((o) => o.textContent)).toHaveLength(3);
  });

  it("shows run progress in labelled groups, not one mixed total", async () => {
    const job = { ...socialDiscover.active_job! };
    mockApi({ "/social/discover": { ...socialDiscover, active_job: job }, "/social/jobs": { items: [] } });
    renderAt("/social-commerce/discover", "/social-commerce/discover", <SocialDiscoverPage />);
    expect(await screen.findByText("This run")).toBeInTheDocument();
    expect(screen.getByText("Campaign totals")).toBeInTheDocument();
  });
});

describe("Social sellers list", () => {
  it("shows a seller with its category, location confidence and complexity", async () => {
    mockApi({ "/social/sellers": { items: [sellerCard], total: 1 }, "/social/counts": { all: 1, ready: 1 } });
    renderAt("/social-commerce/leads", "/social-commerce/leads", <SocialLeads />);
    expect(await screen.findByText("Asha Cakes")).toBeInTheDocument();
    // "Verified Chennai" also appears as a filter option, so scope to the seller card.
    expect(screen.getByText(/Verified Chennai · adyar/)).toBeInTheDocument();
    // The category name is also a filter option, so assert it appears on the card itself.
    const cardLink = screen.getByRole("link", { name: /Asha Cakes/ });
    expect(within(cardLink).getByText("Home bakery / pre-order food")).toBeInTheDocument();
    expect(within(cardLink).getByText("3 complexity indicators")).toBeInTheDocument();
  });

  it("offers platform, category and location filters", async () => {
    mockApi({ "/social/sellers": { items: [sellerCard], total: 1 }, "/social/counts": { all: 1 } });
    renderAt("/social-commerce/leads", "/social-commerce/leads", <SocialLeads />);
    expect(await screen.findByLabelText("Platform")).toBeInTheDocument();
    expect(screen.getByLabelText("What they sell")).toBeInTheDocument();
    expect(screen.getByLabelText("Location confidence")).toBeInTheDocument();
    expect(screen.getByLabelText("Research state")).toBeInTheDocument();
  });

  it("shows an honest empty state", async () => {
    mockApi({ "/social/sellers": { items: [], total: 0 }, "/social/counts": { all: 0 } });
    renderAt("/social-commerce/leads", "/social-commerce/leads", <SocialLeads />);
    expect(await screen.findByText("Nothing here yet")).toBeInTheDocument();
  });
});

describe("Seller dossier", () => {
  it("separates verified facts from hypotheses and says which is which", async () => {
    mockApi({ "/social/sellers/1": sellerDetail });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    expect(await screen.findByRole("heading", { name: "Asha Cakes" })).toBeInTheDocument();
    expect(screen.getByText("Is that problem verified or a hypothesis?")).toBeInTheDocument();
    expect(screen.getByText(/Hypothesis from their own public posts/)).toBeInTheDocument();
  });

  it("states that order complexity is not proof of a problem", async () => {
    mockApi({ "/social/sellers/1": sellerDetail });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    expect(await screen.findByText(/Indicators that a workflow tool might be relevant — not proof of a problem/))
      .toBeInTheDocument();
  });

  it("states that a post is not proof of sales", async () => {
    mockApi({ "/social/sellers/1": sellerDetail });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    expect(await screen.findByText(/not proof of sales, order volume or revenue/)).toBeInTheDocument();
  });

  it("shows followers but labels them as never used in scoring", async () => {
    mockApi({ "/social/sellers/1": sellerDetail });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    expect(await screen.findByText(/4,200 followers — not used in scoring/)).toBeInTheDocument();
  });

  it("explains that weak evidence never establishes a location", async () => {
    mockApi({ "/social/sellers/1": sellerDetail });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    expect(await screen.findByText(/Hashtags, caption language, followers and customer comments never count/))
      .toBeInTheDocument();
  });

  it("offers 'Record what you saw' when a profile cannot be read", async () => {
    mockApi({ "/social/sellers/1": sellerDetail });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    const btn = await screen.findByRole("button", { name: /Record what you saw/ });
    await userEvent.click(btn);
    expect(await screen.findByText(/IOI cannot read Instagram or Facebook profiles/)).toBeInTheDocument();
    expect(screen.getByText(/Recorded for context. Never used in scoring./)).toBeInTheDocument();
  });

  it("requires every check before approval is possible", async () => {
    mockApi({ "/social/sellers/1": { ...sellerDetail, sales_ready: false, review_status: "new" } });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    const approve = await screen.findByRole("button", { name: /Approve/ });
    expect(approve).toBeDisabled();
    expect(approve).toHaveAttribute("title", "Every mandatory check has to pass first");
  });

  it("states that IOI never sends the message", async () => {
    mockApi({ "/social/sellers/1": sellerDetail });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    expect(await screen.findByText(/IOI never sends messages/)).toBeInTheDocument();
  });

  it("promises no automatic platform integration", async () => {
    mockApi({ "/social/sellers/1": sellerDetail });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    expect(await screen.findByText(/No automatic Instagram or WhatsApp integration is promised/)).toBeInTheDocument();
  });

  it("lists existing software to consider before building", async () => {
    mockApi({ "/social/sellers/1": sellerDetail });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    expect(await screen.findByText("Software they could use instead")).toBeInTheDocument();
    expect(screen.getByText("Google Forms + Sheets")).toBeInTheDocument();
  });

  it("confirms a detected signal through the API", async () => {
    const calls = mockApi({
      "/social/sellers/1": sellerDetail,
      "POST /social/sellers/1/activity/5/review": sellerDetail,
    });
    renderAt("/social-commerce/leads/1", "/social-commerce/leads/:id", <SocialLeadDetail />);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(calls.some((c) => c.url.includes("/activity/5/review")
      && (c.body as { review_status: string }).review_status === "confirmed")).toBe(true);
  });
});

describe("Social activity feed", () => {
  it("states what a post does and does not prove", async () => {
    mockApi({ "/social/activity": { items: [], note: "A post shows a seller is active. It is not proof of sales, order volume or revenue." } });
    renderAt("/social-commerce/activity", "/social-commerce/activity", <SocialActivityFeed />);
    expect(await screen.findByText(/It is not proof of sales/)).toBeInTheDocument();
    expect(screen.getByText("No activity recorded yet")).toBeInTheDocument();
  });

  it("separates activity from demand indicators", async () => {
    mockApi({ "/social/activity": {
      items: [{ ...sellerDetail.activity[0], seller: { id: 1, name: "Asha Cakes" } },
              { ...sellerDetail.activity[1], seller: { id: 1, name: "Asha Cakes" } }],
      note: "A post shows a seller is active.",
    } });
    renderAt("/social-commerce/activity", "/social-commerce/activity", <SocialActivityFeed />);
    expect(await screen.findByText("activity")).toBeInTheDocument();
    expect(screen.getByText("demand indicator")).toBeInTheDocument();
  });
});
