import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import fixture from "../src/test/fixtures/campaign_catalog_v1_synthetic.json" with { type: "json" };
import { installAuthenticatedAdminSession } from "./support/auth";

const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/campaign-catalog-v1/", import.meta.url),
);

const CATALOG_PATH = "/api/v1/campaign-catalog";
const CARD_PATH = /^\/api\/v1\/campaign-catalog\/([1-9][0-9]{0,3})$/;

/** Identifiers of the model and the package never reach the screen. */
const FORBIDDEN_COPY = [
  "Digital_Performance",
  "OOH_Total",
  "Нац_ТВ",
  "Рег_ТВ",
  "pkg_",
  "artifact_",
  "synthetic",
  "computed",
  "up_to_120_days",
  "120_days_and_longer",
  "turnover_increment",
  "undefined",
  "NaN",
] as const;

type Json = Record<string, unknown>;

interface RouteGuard {
  forbidden: string[];
}

const guards = new WeakMap<Page, RouteGuard>();

test.beforeEach(async ({ page }) => {
  await installAuthenticatedAdminSession(page);
});

test.afterEach(async ({ page }) => {
  const guard = guards.get(page);
  if (guard) expect(guard.forbidden, "requests outside the campaign catalog").toEqual([]);
});

function catalog(): Json {
  return structuredClone(fixture) as unknown as Json;
}

function card(number: number): Json | null {
  const source = catalog();
  const campaign = (source.campaigns as Json[]).find((item) => item.number === number);
  if (!campaign) return null;
  return {
    contract_name: "campaign_card_v1",
    schema_version: "1.0.0",
    record_origin: "verified_model_package_artifact",
    package_id: source.package_id,
    model_version: source.model_version,
    model_display_name: source.model_display_name,
    artifact_id: source.artifact_id,
    catalog_version: source.catalog_version,
    period_start: source.period_start,
    period_end: source.period_end,
    roas_level_label: source.roas_level_label,
    notes: source.notes,
    campaign,
    updated_at_utc: source.updated_at_utc,
  };
}

function unpublished(): Json {
  return {
    contract_name: "campaign_catalog_v1",
    schema_version: "1.0.0",
    record_origin: "model_package_artifact_unavailable",
    status: "unavailable",
    title: "Прошлые кампании",
    display_text: "Каталог прошлых кампаний для активной модели пока не опубликован.",
    package_id: source().package_id,
    model_version: null,
    model_display_name: null,
    artifact_id: null,
    catalog_version: null,
    period_start: null,
    period_end: null,
    roas_level_label: null,
    summary: null,
    download: null,
    notes: [],
    campaigns: [],
    updated_at_utc: null,
  };
}

function source(): Json {
  return fixture as unknown as Json;
}

async function fulfill(route: Route, payload: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
}

async function installCatalogRoutes(page: Page, options: { list?: Json } = {}) {
  const guard: RouteGuard = { forbidden: [] };
  guards.set(page, guard);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/v1/auth/session" && !url.search) {
      await route.fallback();
      return;
    }
    if (request.method() !== "GET" || url.search) {
      guard.forbidden.push(`${request.method()} ${url.pathname}${url.search}`);
      await fulfill(route, { error: { code: "TEST_ROUTE_FORBIDDEN" } }, 599);
      return;
    }
    if (url.pathname === CATALOG_PATH) {
      await fulfill(route, options.list ?? catalog());
      return;
    }
    const match = CARD_PATH.exec(url.pathname);
    if (match) {
      const payload = card(Number(match[1]));
      await fulfill(route, payload ?? { error: { code: "CAMPAIGN_NOT_FOUND" } }, payload ? 200 : 404);
      return;
    }
    guard.forbidden.push(`GET ${url.pathname}`);
    await fulfill(route, { error: { code: "TEST_ROUTE_FORBIDDEN" } }, 599);
  });
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

async function expectCleanScreen(page: Page) {
  const text = await page.locator("body").innerText();
  for (const forbidden of FORBIDDEN_COPY) expect(text, `screen shows ${forbidden}`).not.toContain(forbidden);
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )).toBeLessThanOrEqual(0);
}

async function capture(page: Page, filename: string, fullPage = true) {
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  mkdirSync(REVIEW_DIRECTORY, { recursive: true });
  await page.screenshot({ path: `${REVIEW_DIRECTORY}${filename}`, fullPage, animations: "disabled", caret: "hide" });
}

for (const theme of ["light", "dark"] as const) {
  test(`past campaigns list and card, ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await setTheme(page, theme);
    await installCatalogRoutes(page);

    await page.goto("/campaigns");
    await expect(page.getByRole("heading", { level: 1, name: "Кампании прошлых периодов" })).toBeVisible();
    await expect(page.getByText("12 кампаний, оценка есть у 11")).toBeVisible();
    await expect(page.getByRole("link", { name: "Кампании" })).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("link", { name: /Скачать Excel/ })).toHaveAttribute("href", "/api/v1/campaign-catalog/download");
    await expect(page.getByRole("table").getByRole("row")).toHaveCount(10);
    await expectCleanScreen(page);
    await capture(page, `01-list-${theme}.png`);

    await page.getByRole("tab", { name: /Длиннее 120 дней/ }).click();
    await page.getByRole("searchbox", { name: "Поиск кампании" }).fill("Казань");
    await expect(page).toHaveURL(/\/campaigns\?tab=long&q=/);
    await expect(page.getByRole("table").getByRole("row")).toHaveCount(4);
    await expect(page.getByRole("status").filter({ hasText: "Показано" })).toHaveText("Показано 3 из 3");
    await expectCleanScreen(page);
    await capture(page, `02-list-long-search-${theme}.png`);

    await page.getByRole("table").getByRole("link", { name: "Тестовая кампания 7" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Тестовая кампания 7" })).toBeVisible();
    await expect(page).toHaveURL(/\/campaigns\/7\?tab=long&q=/);
    await expect(page.getByRole("heading", { name: /Как читать оценку · уровень ROAS по отрасли/ })).toBeVisible();
    await expectCleanScreen(page);
    await capture(page, `03-card-${theme}.png`);

    await page.getByRole("link", { name: "Все кампании" }).click();
    await expect(page).toHaveURL(/\/campaigns\?tab=long&q=/);
    await expect(page.getByRole("searchbox", { name: "Поиск кампании" })).toHaveValue("Казань");
  });
}

test("campaign without an estimate, light", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await setTheme(page, "light");
  await installCatalogRoutes(page);

  await page.goto("/campaigns/5");
  await expect(page.getByRole("status").filter({ hasText: "Нет оценки эффекта" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "ROAS", exact: true })).toHaveCount(0);
  await expectCleanScreen(page);
  await capture(page, "04-card-no-estimate-light.png");
});

test("card with small effects and regions next to cities, light", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await setTheme(page, "light");
  await installCatalogRoutes(page);

  await page.goto("/campaigns/11");
  await expect(page.getByRole("heading", { level: 1, name: "Тестовая кампания 11" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "География" })).toBeVisible();
  await expect(page.getByText("1 город и 2 региона").first()).toBeVisible();
  await expect(page.getByText("+0,003", { exact: true })).toBeVisible();
  await expectCleanScreen(page);
  await capture(page, "08-card-small-effects-light.png");
});

test("phone width keeps the list and the card readable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setTheme(page, "light");
  await installCatalogRoutes(page);

  await page.goto("/campaigns");
  await expect(page.getByRole("heading", { level: 1, name: "Кампании прошлых периодов" })).toBeVisible();
  await expect(page.getByRole("table")).toBeHidden();
  await expect(page.locator("article").filter({ hasText: "Тестовая кампания 8" })).toBeVisible();
  await expectCleanScreen(page);
  await capture(page, "05-list-phone-light.png", false);

  await setTheme(page, "dark");
  await page.goto("/campaigns/10");
  await expect(page.getByRole("heading", { level: 1, name: "Тестовая кампания 10" })).toBeVisible();
  await expectCleanScreen(page);
  await capture(page, "06-card-phone-dark.png", false);
});

test("catalog that is not published yet", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await setTheme(page, "light");
  await installCatalogRoutes(page, { list: unpublished() });

  await page.goto("/campaigns");
  await expect(page.getByText("Каталог пока не опубликован")).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  await expectCleanScreen(page);
  await capture(page, "07-not-published-light.png", false);
});
