import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

// End-to-end tests run against a SEPARATE backend (port 8765) with a throwaway database, so test approvals and
// payments never touch production records. Discovery reads the real local Overture file (no network).
// A tiny local website (port 8080) stands in for a company site; the backend may fetch it only because
// IOI_ALLOW_PRIVATE_NETWORK is set for this test instance.
const DB = join(tmpdir(), "ioi-e2e.db");
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:8765", channel: "chrome", headless: true, screenshot: "only-on-failure", viewport: { width: 1360, height: 900 } },
  webServer: [
    { command: "python3 -m http.server 8080 --bind 127.0.0.1 --directory e2e/site", port: 8080, reuseExistingServer: false },
    {
      command: `rm -f ${DB} ${DB}-wal ${DB}-shm && cd ../backend && uv run python -m app.main`,
      url: "http://127.0.0.1:8765/api/v3/status",
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        IOI_DATABASE_URL: `sqlite:///${DB}`, IOI_HOST: "127.0.0.1", IOI_PORT: "8765", IOI_API_TOKEN: "", IOI_SCHEDULER_ENABLED: "false",
        IOI_ALLOW_PRIVATE_NETWORK: "true", IOI_OPENROUTER_API_KEY: "", IOI_ANTHROPIC_API_KEY: "",
      },
    },
  ],
});
