import { defineConfig, devices } from "@playwright/test";

const localBrowserChannel = process.env.PLAYWRIGHT_CHANNEL;
const localPort = Number(process.env.PLAYWRIGHT_PORT ?? "4173");
const localBaseUrl = `http://127.0.0.1:${localPort}`;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./artifacts/playwright",
  reporter: "list",
  use: {
    baseURL: localBaseUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(localBrowserChannel ? { channel: localBrowserChannel } : {}),
      },
    },
  ],
  webServer: {
    command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${localPort}`,
    env: {
      VITE_API_BASE_URL: "",
      VITE_RESULT_PROVIDER: "http",
    },
    url: localBaseUrl,
    reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVER === "true",
    timeout: 120_000,
  },
});
