import { expect, test, type Page, type Route } from "@playwright/test";
import type { ModelOverviewV1 } from "../src/shared/api/generated/model-overview-v1";
import { createModelOverviewFixture } from "../src/test/productNavigationFixtures";

function unavailableModel(): ModelOverviewV1 {
  const overview = createModelOverviewFixture();
  overview.active_model = {
    ...overview.active_model,
    status: { code: "unavailable", display_text: "Модель недоступна" },
    model_id: null,
    display_name: null,
    version: null,
    published_at_utc: null,
    framework: null,
    training_period: null,
    supported_scope: null,
    description: "Сведения об активной модели пока недоступны.",
  };
  overview.capabilities = overview.capabilities.map((capability) => ({
    ...capability,
    status: "unavailable",
  }));
  overview.versions = [];
  return overview;
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

async function expectNoDocumentOverflow(page: Page) {
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  )).toBe(false);
}

async function expectNoRawModelNames(page: Page) {
  const text = await page.locator("body").innerText();
  for (const rawName of [
    "model_overview_v1",
    "model_id",
    "model_run_id",
    "capability_cells_n",
    "allowed_use_counts",
    "record_origin",
  ]) {
    expect(text).not.toContain(rawName);
  }
}

async function mockOverview(
  page: Page,
  response: { status?: number; payload: unknown; delayMs?: number },
) {
  const legacyCalls: string[] = [];
  await page.route("**/api/v1/models/active", async (route) => {
    legacyCalls.push(route.request().url());
    await route.fulfill({ status: 599, body: "legacy model endpoint is forbidden" });
  });
  await page.route("**/api/v1/model/overview", async (route: Route) => {
    if (response.delayMs) {
      await new Promise((resolve) => setTimeout(resolve, response.delayMs));
    }
    await route.fulfill({
      status: response.status ?? 200,
      contentType: "application/json",
      body: JSON.stringify(response.payload),
    });
  });
  return legacyCalls;
}

for (const theme of ["dark", "light"] as const) {
  test(`Model overview ready ${theme} desktop`, async ({ page }) => {
    await page.setViewportSize({ width: 1_440, height: 960 });
    await setTheme(page, theme);
    const legacyCalls = await mockOverview(page, {
      payload: createModelOverviewFixture(),
    });
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.goto("/model");
    await expect(page.getByRole("heading", { name: "Модель", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Демонстрационная MMM" })).toBeVisible();
    await expect(page.getByText("Демонстрационные данные", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Что умеет текущая версия" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Ограничения" })).toBeVisible();
    await expectNoRawModelNames(page);
    await expectNoDocumentOverflow(page);
    expect(legacyCalls).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
}

test("Model overview mobile has no page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const legacyCalls = await mockOverview(page, {
    payload: createModelOverviewFixture(),
  });
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Что можно получить в расчете" })).toBeVisible();
  await expectNoDocumentOverflow(page);

  await page.setViewportSize({ width: 812, height: 375 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Модель", exact: true })).toBeVisible();
  await expectNoDocumentOverflow(page);
  expect(legacyCalls).toEqual([]);
});

test("Model overview unavailable state is explicit", async ({ page }) => {
  const legacyCalls = await mockOverview(page, { payload: unavailableModel() });
  await page.goto("/model");
  await expect(page.getByRole("heading", {
    name: "Сведения об активной модели пока недоступны",
  })).toBeVisible();
  await expect(page.getByText("История версий пока недоступна", { exact: true })).toBeVisible();
  await expectNoRawModelNames(page);
  expect(legacyCalls).toEqual([]);
});

test("Model overview 503 is controlled and retryable", async ({ page }) => {
  const legacyCalls = await mockOverview(page, {
    status: 503,
    payload: {
      error: {
        code: "PRODUCT_NAVIGATION_UNAVAILABLE",
        display_text: "Сведения временно недоступны.",
        retryable: true,
        user_action: "Повторите запрос позже.",
      },
    },
  });
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Сведения временно недоступны" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Повторить" })).toBeVisible();
  await expectNoRawModelNames(page);
  expect(legacyCalls).toEqual([]);
});

test("Model overview rejects an unsupported contract", async ({ page }) => {
  const unsupported = {
    ...createModelOverviewFixture(),
    schema_version: "2.0.0",
  };
  const legacyCalls = await mockOverview(page, { payload: unsupported });
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Формат сведений не поддерживается" }))
    .toBeVisible();
  await expect(page.getByText(/не прошел защитную проверку/)).toBeVisible();
  await expectNoRawModelNames(page);
  expect(legacyCalls).toEqual([]);
});

test("Model overview loading state is announced", async ({ page }) => {
  const legacyCalls = await mockOverview(page, {
    payload: createModelOverviewFixture(),
    delayMs: 1_500,
  });
  await page.goto("/model");
  await expect(page.getByRole("status").filter({ hasText: "Загрузка сведений о модели" }))
    .toBeVisible();
  expect(legacyCalls).toEqual([]);
});
