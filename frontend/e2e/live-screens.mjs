// Read-only screenshots of the running IOI app (navigation only; no clicks on actions).
import { chromium } from "@playwright/test";

const out = process.argv[2];
const base = "http://127.0.0.1:8000";
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const shot = async (path, name, opts = {}) => {
  await page.goto(base + path, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: opts.full ?? false });
};
await shot("/", "live-home");
await shot("/discover", "live-discover", { full: true });
await shot("/prospects?tab=strong", "live-prospects");
await shot("/research", "live-research");
const id = process.argv[3];
if (id) await shot(`/prospects/${id}`, "live-dossier", { full: true });
await shot("/settings?tab=ai", "live-settings-ai", { full: true });
await page.setViewportSize({ width: 390, height: 844 });
await shot("/", "live-mobile-home");
await browser.close();
console.log("ok");
