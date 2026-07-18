import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ModelOverviewV2 } from "../src/shared/api/generated/model-overview-v2";
import type { ModelPassportV2 } from "../src/shared/api/generated/model-passport-v2";
import { installAuthenticatedAdminSession } from "./support/auth";
import {
  createModelOverviewV2Fixture,
  createModelPassportV2Fixture,
} from "./support/business-semantics-fixtures";

const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/phase-e1b-business-semantics-v1/", import.meta.url),
);

const FORBIDDEN_COPY = [
  "turnover_per_user",
  "Digital_Performance",
  "OOH_Total",
  "orders_per_user",
  "avg_basket",
  "model_run_id",
  "package_id",
  "posterior_ready",
  "preprod_restricted",
] as const;

interface ModelRouteOptions {
  passport?: unknown;
  overview?: unknown;
  status?: number;
  delayMs?: number;
}

interface ModelRouteGuard {
  allowed: string[];
  forbidden: string[];
}

const guards = new WeakMap<Page, ModelRouteGuard>();

test.beforeEach(async ({ page }) => {
  await installAuthenticatedAdminSession(page);
});

test.afterEach(async ({ page }) => {
  const guard = guards.get(page);
  if (guard) expect(guard.forbidden, "legacy or malformed model requests").toEqual([]);
});

function errorPayload() {
  return {
    error: {
      code: "BUSINESS_SEMANTICS_UNAVAILABLE",
      display_text: "Сведения временно недоступны.",
      retryable: true,
      user_action: "Повторите запрос позже.",
    },
  };
}

async function installModelRoutes(
  page: Page,
  options: ModelRouteOptions = {},
): Promise<ModelRouteGuard> {
  const guard: ModelRouteGuard = { allowed: [], forbidden: [] };
  guards.set(page, guard);

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/v1/auth/session" && !url.search) {
      await route.fallback();
      return;
    }
    guard.forbidden.push(`${request.method()} ${url.pathname}${url.search}`);
    await route.fulfill({ status: 599, body: "blocked unapproved endpoint" });
  });

  const exactHandler = async (route: Route, path: string, payload: unknown) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== "GET" || url.pathname !== path || url.search) {
      guard.forbidden.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed model request" });
      return;
    }
    guard.allowed.push(path);
    if (options.delayMs) await new Promise((resolve) => setTimeout(resolve, options.delayMs));
    const status = options.status ?? 200;
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(status === 200 ? payload : errorPayload()),
    });
  };

  await page.route("**/api/v1/models/active-v2", (route) => exactHandler(
    route,
    "/api/v1/models/active-v2",
    options.passport ?? createModelPassportV2Fixture(),
  ));
  await page.route("**/api/v1/model/overview-v2", (route) => exactHandler(
    route,
    "/api/v1/model/overview-v2",
    options.overview ?? createModelOverviewV2Fixture(),
  ));

  return guard;
}

async function expectNoForbiddenCopy(page: Page) {
  const text = await page.locator("body").innerText();
  for (const forbidden of FORBIDDEN_COPY) expect(text).not.toContain(forbidden);
}

async function expectNoDocumentOverflow(page: Page) {
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )).toBeLessThanOrEqual(0);
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

test("Model uses active-v2 and overview-v2 with one turnover serving target", async ({ page }) => {
  const guard = await installModelRoutes(page);
  await page.goto("/model");

  await expect(page.getByRole("heading", { name: "Модель", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Дополнительный оборот" })).toBeVisible();
  await expect(page.getByText("Serving-показателей").locator("..")).toContainText("1");
  await expect(page.getByText("Активных serving-моделей").locator("..")).toContainText("4");
  await expect(page.getByText("Исследовательских моделей в пакете").locator("..")).toContainText("12");
  await expect(page.getByText(/Модели заказов и среднего чека сохранены для исследований/))
    .toBeVisible();
  await expect(page.getByText("Цифровая реклама", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Наружная реклама", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Радио/).first()).toBeVisible();
  await expect(page.getByText(/Indoor/).first()).toBeVisible();
  await expect(page.getByText("Historical replay пройден.", { exact: true })).toBeVisible();
  await expect(page.getByText("Sealed OOT пока недоступен.", { exact: true })).toBeVisible();
  await expect(page.getByText(/не является решением о запуске кампании/)).toBeVisible();
  expect(guard.allowed).toEqual(expect.arrayContaining([
    "/api/v1/models/active-v2",
    "/api/v1/model/overview-v2",
  ]));
  await expectNoForbiddenCopy(page);
});

test("Model unavailable is a controlled research/preprod state", async ({ page }) => {
  const passport: ModelPassportV2 = createModelPassportV2Fixture();
  passport.serving.calculation_allowed = false;
  const overview: ModelOverviewV2 = createModelOverviewV2Fixture(passport);
  await installModelRoutes(page, { passport, overview });
  await page.goto("/model");

  await expect(page.getByText("Расчеты недоступны", { exact: true })).toBeVisible();
  await expect(page.getByText("Research / preprod", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Модель не утверждена для production-использования.", { exact: true }))
    .toBeVisible();
  await expectNoForbiddenCopy(page);
});

test("Model rejects unsupported and internally inconsistent contracts", async ({ page }) => {
  await installModelRoutes(page, {
    passport: { ...createModelPassportV2Fixture(), schema_version: "3.0.0" },
  });
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Формат сведений не поддерживается" })).toBeVisible();

  await page.unroute("**/api/v1/models/active-v2");
  await page.unroute("**/api/v1/model/overview-v2");
  const passport = createModelPassportV2Fixture();
  const overview = createModelOverviewV2Fixture(passport);
  overview.serving.serving_policy_version = "turnover_serving_v1";
  overview.summary.training_period.end_date = "2025-11-30";
  await page.route("**/api/v1/models/active-v2", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(passport) });
  });
  await page.route("**/api/v1/model/overview-v2", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(overview) });
  });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Формат сведений не поддерживается" })).toBeVisible();
});

test("Model loading and 503 states are controlled", async ({ page }) => {
  await installModelRoutes(page, { delayMs: 700 });
  const navigation = page.goto("/model");
  await expect(page.getByRole("status").filter({ hasText: "Загрузка сведений о модели" }))
    .toBeVisible();
  await navigation;
  await expect(page.getByRole("heading", { name: "Дополнительный оборот" })).toBeVisible();

  await page.unroute("**/api/v1/models/active-v2");
  await page.unroute("**/api/v1/model/overview-v2");
  await page.route("**/api/v1/models/active-v2", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify(errorPayload()) });
  });
  await page.route("**/api/v1/model/overview-v2", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify(errorPayload()) });
  });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Сведения временно недоступны" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Повторить" })).toBeVisible();
});

for (const viewport of [
  { width: 375, height: 812 },
  { width: 812, height: 375 },
  { width: 1_440, height: 900 },
]) {
  test(`Model has no document overflow at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await installModelRoutes(page);
    await page.goto("/model");
    await expect(page.getByRole("heading", { name: "Дополнительный оборот" })).toBeVisible();
    await expectNoDocumentOverflow(page);
    await expectNoForbiddenCopy(page);
  });
}

for (const theme of ["dark", "light"] as const) {
  test(`Model turnover-only review ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1_440, height: 900 });
    await setTheme(page, theme);
    await installModelRoutes(page);
    await page.goto("/model");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.getByRole("heading", { name: "Дополнительный оборот" })).toBeVisible();
    await expectNoDocumentOverflow(page);
    await expectNoForbiddenCopy(page);
    mkdirSync(REVIEW_DIRECTORY, { recursive: true });
    await page.screenshot({
      path: `${REVIEW_DIRECTORY}model-${theme}.png`,
      fullPage: false,
      animations: "disabled",
      caret: "hide",
    });
  });
}
