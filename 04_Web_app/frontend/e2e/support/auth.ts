import type { Page } from "@playwright/test";
import { createAuthenticatedSessionFixture } from "../../src/test/authAdminFixtures";

const SESSION_PATH = "/api/v1/auth/session";

export async function installAuthenticatedAdminSession(page: Page): Promise<void> {
  await page.route(`**${SESSION_PATH}`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (request.method() !== "GET" || url.pathname !== SESSION_PATH || url.search !== "") {
      await route.fallback();
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: {
        "Cache-Control": "no-store",
        Pragma: "no-cache",
        "X-Content-Type-Options": "nosniff",
      },
      body: JSON.stringify(createAuthenticatedSessionFixture("admin")),
    });
  });
}
