import { expect, test } from "@playwright/test";

// The primary acceptance test from the IOI 3.0 brief, driven entirely through the UI.
test("first run → discovery → prospect → outreach → reply → pipeline → payment", async ({ page }) => {
  // 1. First-time user: setup wizard
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome to Inferago IOI" })).toBeVisible();
  await page.getByLabel("Your name (signs outreach messages)").fill("Test Owner");
  await page.getByRole("button", { name: "Looks right — continue" }).click();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("Business directory file ready")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Skip for now" }).click();

  // 2. Clean dashboard with real (empty) values
  await expect(page.getByRole("heading", { name: /Here's your sales workspace/ })).toBeVisible();
  await expect(page.getByText("No prospects ready yet")).toBeVisible();
  await expect(page.getByText("₹0").first()).toBeVisible();

  // 3. Start a real discovery job (Quick: real Overture records, no internet) and watch progress
  await page.getByRole("link", { name: "Discover" }).first().click();
  await page.getByText("Quick", { exact: true }).click();
  await page.getByLabel("New businesses (max)").fill("15");
  await page.getByRole("button", { name: "Start Discovery" }).click();
  await expect(page.getByText("1. Finding businesses")).toBeVisible();
  await expect(page.getByText("completed", { exact: true }).first()).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(/businesses in this campaign/)).toBeVisible();
  await page.screenshot({ path: "e2e/screens/discover.png", fullPage: true });

  // 4. Relevant Chennai businesses are listed
  await page.getByRole("link", { name: "Prospects" }).first().click();
  await page.getByRole("tab", { name: /All Businesses/ }).click();
  await expect(page.getByTestId("prospect-card").first()).toBeVisible();
  const cards = await page.getByTestId("prospect-card").count();
  expect(cards).toBeGreaterThan(0);
  await page.screenshot({ path: "e2e/screens/prospects.png" });

  // 5. Add a business with a website (local stand-in site) and research it
  await page.getByRole("button", { name: "Add business" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Business name *").fill("E2E Test Biomedical Services");
  await dlg.getByLabel("Industry").selectOption("equipment_sales_service");
  await dlg.getByLabel(/^Address/).fill("14 Usman Road, T Nagar, Chennai 600017");
  await dlg.getByLabel("Official website").fill("http://127.0.0.1:8080/");
  await dlg.getByLabel("Where you found it (link) *").fill("https://example.org/e2e-source");
  await dlg.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByPlaceholder("Search name or area").fill("E2E Test");
  await page.getByRole("link", { name: "E2E Test Biomedical Services" }).click();
  await page.getByRole("button", { name: "Research further" }).click();
  await expect(page.getByText("Research finished")).toBeVisible({ timeout: 60_000 });

  // 6. The profile explains facts vs hypotheses, solution and contact
  await expect(page.getByRole("heading", { name: "Why IOI selected this company" })).toBeVisible();
  await expect(page.getByText("Verified", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Hypothesis", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("ServiceFlow Setup").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "service@e2e-test.example" })).toBeVisible();
  await page.screenshot({ path: "e2e/screens/prospect-detail.png", fullPage: true });

  // 7. Approve the outreach draft
  await page.getByRole("button", { name: "Approve for Outreach" }).click();
  await expect(page.getByText(/Approved by owner/)).toBeVisible();

  // 8. Record contact and a reply in Outreach
  await page.getByRole("link", { name: "Outreach" }).first().click();
  await page.getByRole("button", { name: "Mark as contacted" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByRole("button", { name: "Record reply" }).click();
  await page.getByRole("dialog").getByLabel("Problem they described (optional)").fill("Service calls are tracked in a notebook");
  await page.getByRole("dialog").getByLabel("What they said *").fill("Service manager wants a demo next week");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Pipeline: replied")).toBeVisible();
  await page.screenshot({ path: "e2e/screens/outreach.png", fullPage: true });

  // 9. Move through the pipeline: proposal, then an actual payment
  await page.getByRole("link", { name: "Sales Pipeline" }).first().click();
  await page.getByRole("button", { name: "E2E Test Biomedical Services", exact: true }).click();
  const deal = page.getByRole("dialog");
  await deal.getByLabel("Proposal title").fill("ServiceFlow pilot");
  await deal.getByLabel("Proposal amount").fill("30000");
  await deal.getByRole("button", { name: "Record proposal sent" }).click();
  await expect(deal.getByText("Proposal recorded as sent")).toBeVisible();
  await deal.getByLabel("Payment amount").fill("30000");
  await deal.getByRole("button", { name: "Record payment received" }).click();
  await expect(deal.getByText("Payment recorded")).toBeVisible();
  await deal.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("region", { name: "Advance Received" }).getByText("E2E Test Biomedical Services")).toBeVisible();
  await page.screenshot({ path: "e2e/screens/pipeline.png" });

  // 10. Home shows the actual collected revenue
  await page.getByRole("link", { name: "Home" }).first().click();
  await expect(page.getByText("₹30,000").first()).toBeVisible();
  await page.screenshot({ path: "e2e/screens/home-after.png", fullPage: true });

  // Settings and responsive / dark checks
  await page.getByRole("link", { name: "Settings" }).first().click();
  await page.getByRole("tab", { name: "Advanced" }).click();
  await expect(page.getByText("Source health")).toBeVisible();
  await page.screenshot({ path: "e2e/screens/settings-advanced.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("navigation", { name: "Main mobile" }).getByRole("link", { name: "Prospects" }).click();
  await page.getByRole("button", { name: "Toggle dark mode" }).first().click();
  await page.screenshot({ path: "e2e/screens/mobile-dark-prospects.png", fullPage: false });
});
