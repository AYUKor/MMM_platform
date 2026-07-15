import { defineConfig, devices } from "@playwright/test";

const localBrowserChannel = process.env.PLAYWRIGHT_CHANNEL;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./artifacts/playwright",
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
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
    command: "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173",
    env: {
      VITE_API_BASE_URL: "",
      VITE_RESULT_PROVIDER: "http",
    },
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
