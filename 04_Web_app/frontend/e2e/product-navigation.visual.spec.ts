import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type {
  CalculationHistoryV1,
  HistoryItem,
} from "../src/shared/api/generated/calculation-history-v1";
import {
  createCalculationHistoryFixture,
  createHelpCatalogFixture,
  createWorkspaceHomeFixture,
} from "../src/test/productNavigationFixtures";
import { installAuthenticatedAdminSession } from "./support/auth";
import {
  createGeoCatalogFixture,
  createModelOverviewV2Fixture,
  createModelPassportV2Fixture,
  createWorkspaceGeoBudgetFixture,
} from "./support/business-semantics-fixtures";

const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/phase-e1b-business-semantics-v1/", import.meta.url),
);

const ALLOWED_PATHS = new Set([
  "/api/v1/workspace/home",
  "/api/v1/workspace/geo-budget",
  "/api/v1/meta/geo-catalog",
  "/api/v1/calculations/history",
  "/api/v1/models/active-v2",
  "/api/v1/model/overview-v2",
  "/api/v1/help/catalog",
]);

const FORBIDDEN_COPY = [
  "Дополнительные заказы",
  "Заказы на 100 000 ₽",
  "Механизм среднего чека",
  "Часть дополнительного оборота",
  "Digital_Performance",
  "OOH_Total",
  "orders_per_user",
  "avg_basket",
  "turnover_per_user",
  "... ещё",
] as const;

interface NavigationOptions {
  home?: unknown;
  geoBudget?: unknown;
  geoCatalog?: unknown;
  passport?: unknown;
  model?: unknown;
  help?: unknown;
  status?: number;
  delayMs?: number;
}

interface RouteGuard {
  allowed: string[];
  forbidden: string[];
}

const guards = new WeakMap<Page, RouteGuard>();

test.beforeEach(async ({ page }) => {
  await installAuthenticatedAdminSession(page);
});

test.afterEach(async ({ page }) => {
  const guard = guards.get(page);
  if (guard) expect(guard.forbidden, "legacy or malformed product-navigation requests").toEqual([]);
});

function errorPayload(displayText = "Сведения временно недоступны.") {
  return {
    error: {
      code: "BUSINESS_SEMANTICS_UNAVAILABLE",
      display_text: displayText,
      retryable: true,
      user_action: "Повторите запрос позже.",
    },
  };
}

function historyResponse(url: URL): CalculationHistoryV1 {
  const source = createCalculationHistoryFixture();
  const page = Number(url.searchParams.get("page") ?? "1");
  const pageSize = Number(url.searchParams.get("page_size") ?? "25");
  const status = url.searchParams.get("status");
  const search = url.searchParams.get("search");
  const createdFrom = url.searchParams.get("created_from");
  const createdTo = url.searchParams.get("created_to");
  const sort = url.searchParams.get("sort") ?? "created_desc";
  let items = [...source.items];
  if (status === "active") {
    items = items.filter((item) => ["queued", "running", "cancel_requested"].includes(item.status));
  } else if (status) {
    items = items.filter((item) => item.status === status);
  }
  if (search) {
    const normalized = search.toLocaleLowerCase("ru-RU");
    // The backend contract searches campaign_name only.
    items = items.filter((item) => item.campaign_name.toLocaleLowerCase("ru-RU").includes(normalized));
  }
  if (createdFrom) items = items.filter((item) => item.created_at_utc.slice(0, 10) >= createdFrom);
  if (createdTo) items = items.filter((item) => item.created_at_utc.slice(0, 10) <= createdTo);
  const direction = sort === "created_asc" ? 1 : -1;
  items.sort((left, right) => {
    if (sort === "campaign_asc") return left.campaign_name.localeCompare(right.campaign_name, "ru");
    if (sort === "completed_desc") {
      return (right.completed_at_utc ?? "").localeCompare(left.completed_at_utc ?? "");
    }
    return direction * left.created_at_utc.localeCompare(right.created_at_utc);
  });
  const total = items.length;
  return {
    ...source,
    filters: {
      status: status as CalculationHistoryV1["filters"]["status"],
      search,
      created_from: createdFrom,
      created_to: createdTo,
      sort: sort as CalculationHistoryV1["filters"]["sort"],
    },
    pagination: {
      page,
      page_size: pageSize,
      total_items: total,
      total_pages: total === 0 ? 0 : Math.ceil(total / pageSize),
    },
    items: items.slice((page - 1) * pageSize, page * pageSize),
  };
}

async function fulfill(route: Route, payload: unknown, status = 200, delayMs = 0) {
  if (delayMs) await new Promise((resolve) => setTimeout(resolve, delayMs));
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
}

async function installNavigationRoutes(
  page: Page,
  options: NavigationOptions = {},
): Promise<RouteGuard> {
  const guard: RouteGuard = { allowed: [], forbidden: [] };
  guards.set(page, guard);

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    if (method === "GET" && url.pathname === "/api/v1/auth/session" && !url.search) {
      await route.fallback();
      return;
    }
    if (method !== "GET" || !ALLOWED_PATHS.has(url.pathname)) {
      guard.forbidden.push(`${method} ${url.pathname}${url.search}`);
      await fulfill(route, errorPayload("Маршрут теста не разрешен."), 599);
      return;
    }
    if (url.pathname !== "/api/v1/calculations/history" && url.search) {
      guard.forbidden.push(`${method} ${url.pathname}${url.search}`);
      await fulfill(route, errorPayload("Параметры запроса не разрешены."), 599);
      return;
    }
    guard.allowed.push(`${url.pathname}${url.search}`);
    const status = options.status ?? 200;
    const payload = status === 200
      ? url.pathname === "/api/v1/workspace/home"
        ? (options.home ?? createWorkspaceHomeFixture())
        : url.pathname === "/api/v1/workspace/geo-budget"
          ? (options.geoBudget ?? createWorkspaceGeoBudgetFixture())
          : url.pathname === "/api/v1/meta/geo-catalog"
            ? (options.geoCatalog ?? createGeoCatalogFixture())
            : url.pathname === "/api/v1/calculations/history"
              ? historyResponse(url)
              : url.pathname === "/api/v1/models/active-v2"
                ? (options.passport ?? createModelPassportV2Fixture())
                : url.pathname === "/api/v1/model/overview-v2"
                  ? (options.model ?? createModelOverviewV2Fixture())
                  : (options.help ?? createHelpCatalogFixture())
      : errorPayload();
    await fulfill(route, payload, status, options.delayMs ?? 0);
  });

  return guard;
}

async function expectNoForbiddenCopy(page: Page) {
  const text = await page.locator("body").innerText();
  for (const forbidden of FORBIDDEN_COPY) expect(text).not.toContain(forbidden);
  expect(text).not.toContain("Кампания, сегмент или номер расчета");
}

async function expectNoOverflow(page: Page) {
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

test("Home adds geo-budget and geo-catalog without inventing a map", async ({ page }) => {
  const guard = await installNavigationRoutes(page);
  await page.goto("/");

  await expect(page.getByRole("heading", {
    name: "Планируйте бюджет и проверяйте результат в одном месте",
  })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Бюджет проверенных кампаний по географиям" }))
    .toBeVisible();
  await expect(page.getByText("Бюджет в проверенных кампаниях").locator("..")).toContainText("12 млн ₽");
  await expect(page.getByText("Карта пока недоступна", { exact: true })).toBeVisible();
  await expect(page.getByText(/подключения утвержденного справочника координат/)).toBeVisible();
  await expect(page.getByText("Дополнительный оборот", { exact: true }).first()).toBeVisible();
  expect(guard.allowed.some((call) => call.startsWith("/api/v1/workspace/home"))).toBe(true);
  expect(guard.allowed.some((call) => call.startsWith("/api/v1/workspace/geo-budget"))).toBe(true);
  expect(guard.allowed.some((call) => call.startsWith("/api/v1/meta/geo-catalog"))).toBe(true);
  await expectNoForbiddenCopy(page);
});

test("History keeps backend search semantics and URL filters", async ({ page }) => {
  const guard = await installNavigationRoutes(page);
  await page.goto("/calculations?status=succeeded&search=завершенная&sort=campaign_asc&page=1&page_size=25");

  const search = page.getByRole("searchbox", { name: "Поиск" });
  await expect(search).toHaveAttribute("placeholder", "Поиск по названию кампании");
  await expect(page.getByText("Демонстрационная завершенная кампания", { exact: true }).first())
    .toBeVisible();
  await expect(page.getByText("Демонстрационная активная кампания", { exact: true })).toHaveCount(0);
  expect(guard.allowed.some((call) => (
    call.startsWith("/api/v1/calculations/history?")
    && call.includes("status=succeeded")
    && call.includes("search=")
    && call.includes("sort=campaign_asc")
  ))).toBe(true);

  await search.fill("несуществующая кампания");
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(page.getByText("Поиск ничего не нашел", { exact: true })).toBeVisible();
  await expectNoForbiddenCopy(page);
});

test("History preserves null and known zero semantics", async ({ page }) => {
  await installNavigationRoutes(page);
  await page.goto("/calculations");
  const failed = page.getByRole("row").filter({ hasText: "Демонстрационная кампания с ошибкой" });
  await expect(failed).toContainText("Нет данных");
  const active = page.getByRole("row").filter({ hasText: "Демонстрационная активная кампания" });
  await expect(active).toContainText("0");
});

test("Model navigation uses the paired v2 contracts", async ({ page }) => {
  const guard = await installNavigationRoutes(page);
  await page.goto("/model");

  await expect(page.getByRole("heading", { name: "Дополнительный оборот" })).toBeVisible();
  await expect(page.getByText("Serving-показателей").locator("..")).toContainText("1");
  await expect(page.getByText("Активных serving-моделей").locator("..")).toContainText("4");
  await expect(page.getByText("Исследовательских моделей в пакете").locator("..")).toContainText("12");
  expect(guard.allowed.some((call) => call.startsWith("/api/v1/models/active-v2"))).toBe(true);
  expect(guard.allowed.some((call) => call.startsWith("/api/v1/model/overview-v2"))).toBe(true);
  await expectNoForbiddenCopy(page);
});

test("Help filters legacy target claims in articles", async ({ page }) => {
  const help = createHelpCatalogFixture();
  help.sections[0].articles[0].body.push({
    block_type: "paragraph",
    text: "Средний чек и orders_per_user использовались в старом описании.",
  });
  await installNavigationRoutes(page, { help });
  await page.goto("/help");
  await expect(page.getByRole("heading", { name: "Справка", exact: true })).toBeVisible();
  await expectNoForbiddenCopy(page);
});

test("unsupported geo and model contracts fail closed", async ({ page }) => {
  await installNavigationRoutes(page, {
    geoBudget: { ...createWorkspaceGeoBudgetFixture(), schema_version: "2.0.0" },
  });
  await page.goto("/");
  await expect(page.getByText("Карта пока недоступна", { exact: true })).toBeVisible();
  await expect(page.getByText("Бюджет в проверенных кампаниях")).toHaveCount(0);

  await page.unroute("**/api/v1/**");
  await installAuthenticatedAdminSession(page);
  await installNavigationRoutes(page, {
    passport: { ...createModelPassportV2Fixture(), schema_version: "3.0.0" },
  });
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Формат сведений не поддерживается" })).toBeVisible();
});

test("loading and HTTP failure states remain controlled", async ({ page }) => {
  await installNavigationRoutes(page, { delayMs: 600 });
  const navigation = page.goto("/");
  await expect(page.getByRole("status").filter({ hasText: "Загрузка рабочего пространства" }))
    .toBeVisible();
  await navigation;
  await expect(page.getByRole("heading", { name: "Что происходит сейчас" })).toBeVisible();

  await page.unroute("**/api/v1/**");
  await installAuthenticatedAdminSession(page);
  await installNavigationRoutes(page, { status: 503 });
  await page.goto("/help");
  await expect(page.getByRole("heading", { name: "Сведения временно недоступны" })).toBeVisible();
});

for (const viewport of [
  { width: 375, height: 812 },
  { width: 812, height: 375 },
  { width: 1_440, height: 900 },
]) {
  test(`product navigation has no overflow at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await installNavigationRoutes(page);
    for (const path of ["/", "/calculations", "/model", "/help"]) {
      await page.goto(path);
      await expectNoOverflow(page);
      await expectNoForbiddenCopy(page);
    }
  });
}

for (const theme of ["dark", "light"] as const) {
  test(`Home geo-budget review ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1_440, height: 900 });
    await setTheme(page, theme);
    await installNavigationRoutes(page);
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.getByRole("heading", { name: "Бюджет проверенных кампаний по географиям" }))
      .toBeVisible();
    await expectNoOverflow(page);
    await expectNoForbiddenCopy(page);
    mkdirSync(REVIEW_DIRECTORY, { recursive: true });
    await page.screenshot({
      path: `${REVIEW_DIRECTORY}home-geo-budget-${theme}.png`,
      fullPage: false,
      animations: "disabled",
      caret: "hide",
    });
  });
}

test("the product-navigation allowlist contains only approved projections", () => {
  expect([...ALLOWED_PATHS]).toEqual([
    "/api/v1/workspace/home",
    "/api/v1/workspace/geo-budget",
    "/api/v1/meta/geo-catalog",
    "/api/v1/calculations/history",
    "/api/v1/models/active-v2",
    "/api/v1/model/overview-v2",
    "/api/v1/help/catalog",
  ]);
});

// Keep the imported type tied to server-side history rows: this makes fixture
// drift fail typecheck instead of silently weakening the E2E contract.
const _historyItemTypecheck: HistoryItem | null = null;
void _historyItemTypecheck;
