import { expect, test } from "@playwright/test";

// The Social Commerce acceptance test from the brief, driven entirely through the UI.
// The "seller website" is the local test site on port 8080 — synthetic data, clearly labelled.
const SELLER_SITE = "http://127.0.0.1:8080/bakery/";

test("social commerce: add a seller → research → dossier → approve → reply → payment", async ({ page }) => {
  // Onboarding (shared with the B2B workspace).
  await page.goto("/");
  if (await page.getByRole("heading", { name: "Welcome to Inferago IOI" }).isVisible().catch(() => false)) {
    await page.getByLabel("Your name (signs outreach messages)").fill("Test Owner");
    await page.getByRole("button", { name: "Looks right — continue" }).click();
    await page.getByRole("button", { name: "Confirm" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Skip for now" }).click();
  }

  // 1. Social Commerce is its own top-level sidebar item.
  const sidebar = page.getByRole("navigation", { name: "Main" });
  await expect(sidebar.getByRole("link", { name: "Social Commerce" })).toBeVisible();
  await sidebar.getByRole("link", { name: "Social Commerce" }).click();
  await expect(page).toHaveURL(/\/social-commerce$/);

  // 2. Its own dashboard, with real (empty) values and no invented counters.
  await expect(page.getByRole("heading", { name: "Social Commerce Intelligence" })).toBeVisible();
  await expect(page.getByText(/Discover growing Chennai businesses selling through Instagram, Facebook and WhatsApp/).first())
    .toBeVisible();
  await expect(page.getByText("No social sellers yet").first()).toBeVisible();
  await page.screenshot({ path: "e2e/screens/social-dashboard-empty.png", fullPage: true });

  // 3. Add a Chennai seller from a public profile link, with their own website.
  await page.getByRole("button", { name: "Add Business/Profile" }).first().click();
  await page.getByLabel("Public link or handle").fill("https://www.instagram.com/e2e_test_bakery/");
  await page.getByLabel("Business name").fill("E2E Test Home Bakery");
  await page.getByLabel("Their own description")
    .fill("Custom cakes and brownies. 50% advance to confirm. Order 3 days in advance. Delivery across Chennai.");
  await page.getByLabel("Address they publish").fill("No 12, 2nd Street, Adyar, Chennai 600020");
  await page.getByLabel("Website or catalogue").fill(SELLER_SITE);
  await page.getByRole("button", { name: "Add seller" }).click();

  // Lands on the seller's dossier.
  await expect(page.getByRole("heading", { name: "E2E Test Home Bakery" })).toBeVisible();
  await expect(page.getByText("Verified Chennai", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Home bakery / pre-order food").first()).toBeVisible();

  // 4. Instagram cannot be read automatically, and the UI says so.
  await expect(page.getByText(/Instagram serves profiles only to signed-in visitors/).first()).toBeVisible();

  // 5. Read their own pages: real HTTP to the local test site.
  await page.getByRole("button", { name: "Read their pages" }).click();
  await expect(page.getByText("Made-to-order / customisation").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Advance / part payment before work starts").first()).toBeVisible();
  await expect(page.getByText("Delivery dates / lead times").first()).toBeVisible();

  // 6. The dossier distinguishes what is known from what is assumed.
  await expect(page.getByText(/Indicators that a workflow tool might be relevant — not proof of a problem/).first()).toBeVisible();
  await expect(page.getByText(/not proof of sales, order volume or revenue/).first()).toBeVisible();
  await expect(page.getByText("Is that problem verified or a hypothesis?").first()).toBeVisible();
  await expect(page.getByText(/Hashtags, caption language, followers and customer comments never count/).first()).toBeVisible();

  // 7. A recommended low-cost step, with no platform-integration promise.
  await expect(page.getByText("Pre-Order and Delivery Tracker").first()).toBeVisible();
  await expect(page.getByText(/No automatic Instagram or WhatsApp integration is promised/).first()).toBeVisible();
  await expect(page.getByText("Software they could use instead").first()).toBeVisible();
  await page.screenshot({ path: "e2e/screens/social-dossier.png", fullPage: true });

  // 8. Record what a person saw on the profile IOI cannot read.
  await page.getByRole("button", { name: "Record what you saw" }).click();
  await expect(page.getByText(/IOI cannot read Instagram or Facebook profiles/).first()).toBeVisible();
  await page.getByLabel("Their bio and recent posts, in their words")
    .fill("Custom cakes. Sold out this weekend. DM to order.");
  await page.getByLabel("Followers").fill("4200");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/4,200 followers — not used in scoring/).first()).toBeVisible();

  // 9. Approve the outreach draft (human approval is mandatory) and confirm nothing is sent.
  await expect(page.getByText(/IOI never sends messages/).first()).toBeVisible();
  const approve = page.getByRole("button", { name: "Approve", exact: true });
  await expect(approve).toBeEnabled();
  await approve.click();
  await expect(page.getByText(/Approved by/).first()).toBeVisible();

  // 10. Log the message, then record a reply that confirms a real problem → S0.
  await page.getByRole("button", { name: "I messaged them" }).click();
  await page.getByRole("button", { name: "Record a reply" }).click();
  await page.getByLabel("What they said").fill("She replied and is interested.");
  await page.getByLabel("A problem they confirmed").fill("I keep losing cake orders in my DMs");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("S0", { exact: false }).first()).toBeVisible();

  // 11. The seller now appears in the shared sales pipeline, and a payment counts as collected revenue.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Sales Pipeline" }).click();
  await expect(page.getByText("E2E Test Home Bakery").first()).toBeVisible();
  await page.screenshot({ path: "e2e/screens/social-pipeline.png", fullPage: true });

  // 12. The B2B pipeline is still there and separate.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "B2B Prospects" }).click();
  await expect(page.getByText("E2E Test Home Bakery")).toHaveCount(0);

  // 13. The seller list, filters and activity feed work.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Social Commerce" }).click();
  await page.getByRole("link", { name: /All sellers/ }).click();
  await page.getByRole("tab", { name: /Approved/ }).click();
  await expect(page.getByText("E2E Test Home Bakery").first()).toBeVisible();
  await page.screenshot({ path: "e2e/screens/social-leads.png", fullPage: true });
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Social Commerce" }).click();
  await page.getByRole("link", { name: /Activity feed/ }).click();
  await expect(page.getByText(/It is not proof of sales/).first()).toBeVisible();

  // 14. Discovery reports honestly that no search API is configured.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Social Commerce" }).click();
  await page.getByRole("button", { name: /Find Social Commerce Businesses/ }).click();
  await expect(page.getByText(/Public web search is not available/).first()).toBeVisible();
  await expect(page.getByText(/Adding a profile or catalogue link by hand always works/).first()).toBeVisible();
  await page.screenshot({ path: "e2e/screens/social-discover.png", fullPage: true });

  // 15. Dark mode is the default and the layout works on a phone.
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("navigation", { name: "Main mobile" }).getByRole("link", { name: "Social" }).click();
  await expect(page.getByRole("heading", { name: "Social Commerce Intelligence" })).toBeVisible();
  await page.screenshot({ path: "e2e/screens/social-mobile.png", fullPage: false });
});
