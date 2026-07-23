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
  createHistoricalModelGeoBudgetFixture,
  createModelOverviewV2Fixture,
  createModelPassportV2Fixture,
  createPartialHistoricalModelGeoBudgetFixture,
  createUnavailableHistoricalModelGeoBudgetFixture,
} from "./support/business-semantics-fixtures";

const GEO_REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/phase-e1f-historical-home-map-v1/", import.meta.url),
);

const ALLOWED_PATHS = new Set([
  "/api/v1/workspace/home",
  "/api/v1/model/historical-geo-budget",
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
  historicalGeoBudget?: unknown;
  passport?: unknown;
  model?: unknown;
  help?: unknown;
  status?: number;
  historicalGeoBudgetStatus?: number;
  delayMs?: number;
  geoDelayMs?: number;
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
    const status = url.pathname === "/api/v1/model/historical-geo-budget"
      ? (options.historicalGeoBudgetStatus ?? options.status ?? 200)
      : (options.status ?? 200);
    const payload = status === 200
      ? url.pathname === "/api/v1/workspace/home"
        ? (options.home ?? createWorkspaceHomeFixture())
        : url.pathname === "/api/v1/model/historical-geo-budget"
          ? (options.historicalGeoBudget ?? createHistoricalModelGeoBudgetFixture())
          : url.pathname === "/api/v1/calculations/history"
            ? historyResponse(url)
            : url.pathname === "/api/v1/models/active-v2"
              ? (options.passport ?? createModelPassportV2Fixture())
              : url.pathname === "/api/v1/model/overview-v2"
                ? (options.model ?? createModelOverviewV2Fixture())
                : (options.help ?? createHelpCatalogFixture())
      : errorPayload();
    const delayMs = url.pathname === "/api/v1/model/historical-geo-budget"
      ? (options.geoDelayMs ?? options.delayMs ?? 0)
      : (options.delayMs ?? 0);
    await fulfill(route, payload, status, delayMs);
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

async function expectMapLabelsInsideCanvasWithoutOverlap(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  const canvas = page.getByRole("group", {
    name: "Карта исторического рекламного бюджета модели по географиям",
  });
  const canvasBox = await canvas.boundingBox();
  expect(canvasBox, "historical map canvas must have a layout box").not.toBeNull();
  if (!canvasBox) return;

  const labels = canvas.locator("[data-map-label]");
  const boxes: Array<{ geoId: string; x: number; y: number; width: number; height: number }> = [];
  for (let index = 0; index < await labels.count(); index += 1) {
    const label = labels.nth(index);
    if (!await label.isVisible()) continue;
    const box = await label.boundingBox();
    expect(box, `visible historical label ${index} must have a layout box`).not.toBeNull();
    if (!box) continue;
    const geoId = await label.getAttribute("data-map-label") ?? `label-${index}`;
    expect(box.x, `${geoId} left edge`).toBeGreaterThanOrEqual(canvasBox.x - 1);
    expect(box.y, `${geoId} top edge`).toBeGreaterThanOrEqual(canvasBox.y - 1);
    expect(box.x + box.width, `${geoId} right edge`)
      .toBeLessThanOrEqual(canvasBox.x + canvasBox.width + 1);
    expect(box.y + box.height, `${geoId} bottom edge`)
      .toBeLessThanOrEqual(canvasBox.y + canvasBox.height + 1);
    boxes.push({ geoId, ...box });
  }

  expect(boxes.length, "historical map must keep readable permanent labels").toBeGreaterThan(0);
  for (let leftIndex = 0; leftIndex < boxes.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < boxes.length; rightIndex += 1) {
      const left = boxes[leftIndex];
      const right = boxes[rightIndex];
      const overlapX = Math.min(left.x + left.width, right.x + right.width)
        - Math.max(left.x, right.x);
      const overlapY = Math.min(left.y + left.height, right.y + right.height)
        - Math.max(left.y, right.y);
      expect(
        overlapX > 1 && overlapY > 1,
        `historical labels ${left.geoId} and ${right.geoId} overlap`,
      ).toBe(false);
    }
  }
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

async function captureHistoricalGeoReview(page: Page, filename: string) {
  const section = page.locator("section").filter({
    has: page.getByRole("heading", {
      name: "Исторический рекламный бюджет в данных модели",
    }),
  });
  await expect(section).toBeVisible();
  await expect(page.getByText("Демонстрационные данные", { exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  const reviewSurface = page.locator("main#main-content");
  await expect(reviewSurface).toBeVisible();
  mkdirSync(GEO_REVIEW_DIRECTORY, { recursive: true });
  await reviewSurface.screenshot({
    path: `${GEO_REVIEW_DIRECTORY}${filename}`,
    animations: "disabled",
    caret: "hide",
  });
}

test("Home renders the historical model budget without frontend aggregation or fallback", async ({ page }) => {
  const guard = await installNavigationRoutes(page);
  await page.goto("/");

  await expect(page.getByRole("heading", {
    name: "Планируйте бюджет и проверяйте результат в одном месте",
  })).toBeVisible();
  await expect(page.getByRole("heading", {
    name: "Исторический рекламный бюджет в данных модели",
  }))
    .toBeVisible();
  const historicalSection = page.locator("section").filter({
    has: page.getByRole("heading", {
      name: "Исторический рекламный бюджет в данных модели",
    }),
  });
  await expect(historicalSection.getByText("Общий рекламный бюджет").locator(".."))
    .toContainText("8,7 млрд ₽");
  await expect(historicalSection.getByText("Географий", { exact: true }).locator(".."))
    .toContainText("220");
  await expect(historicalSection).toContainText("Период данных: 01.01.2025 — 31.05.2026");
  await expect(historicalSection).not.toContainText("Кампании");

  const map = page.getByRole("group", {
    name: "Карта исторического рекламного бюджета модели по географиям",
  });
  await expect(map).toBeVisible();
  const markers = map.locator("[data-map-marker]");
  const labels = map.locator("[data-map-label]");
  await expect(markers).toHaveCount(220);
  await expect(labels).toHaveCount(10);

  const payload = createHistoricalModelGeoBudgetFixture();
  const expectedTopTen = [...payload.rows]
    .sort((left, right) => right.historical_total_budget_rub - left.historical_total_budget_rub)
    .slice(0, 10)
    .map((row) => row.geo_id)
    .sort();
  const actualLabels = (await labels.evaluateAll((nodes) => nodes.map(
    (node) => node.getAttribute("data-map-label") ?? "",
  ))).sort();
  expect(actualLabels).toEqual(expectedTopTen);
  await expect(markers.last()).toHaveAttribute(
    "data-budget-rub",
    String(Math.max(...payload.rows.map((row) => row.historical_total_budget_rub))),
  );
  await expect(page.getByText("Координаты городов: GeoNames, CC BY 4.0.")).toBeVisible();
  await expect(page.getByText("Контур карты: Natural Earth, public domain.")).toBeVisible();
  await expect(page.getByText("Подписаны 10 городов с наибольшим бюджетом")).toBeVisible();
  await expect(page.getByText("Карта пока недоступна", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Дополнительный оборот", { exact: true }).first()).toBeVisible();
  expect(guard.allowed.some((call) => call.startsWith("/api/v1/workspace/home"))).toBe(true);
  expect(guard.allowed.filter((call) => call === "/api/v1/model/historical-geo-budget"))
    .toHaveLength(1);
  expect(guard.allowed.some((call) => call.startsWith("/api/v1/workspace/geo-budget"))).toBe(false);
  expect(guard.allowed.some((call) => call.startsWith("/api/v1/meta/geo-catalog"))).toBe(false);
  await expectNoForbiddenCopy(page);
});

test("historical map tooltip supports mouse and keyboard with Escape restore", async ({ page }) => {
  await installNavigationRoutes(page);
  await page.goto("/");

  const source = createHistoricalModelGeoBudgetFixture().rows[0];
  const marker = page.locator(`[data-map-marker="${source.geo_id}"]`);
  await marker.hover();
  let tooltip = page.getByRole("tooltip");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText(source.geo_display_name);
  await expect(tooltip).toContainText("Исторический рекламный бюджет");
  await expect(tooltip).toContainText("1,5 млрд ₽");
  await expect(tooltip).toContainText("Доля общего бюджета");
  await expect(tooltip).toContainText("17,3 %");
  await expect(tooltip).not.toContainText("Дней с рекламной активностью");
  await expect(tooltip).toContainText("01.01.2025 — 31.05.2026");
  await expect(tooltip).not.toContainText("Кампаний");

  await page.mouse.move(0, 0);
  await expect(tooltip).toHaveCount(0);
  await marker.focus();
  tooltip = page.getByRole("tooltip");
  await expect(tooltip).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(tooltip).toHaveCount(0);
  await expect(marker).toBeFocused();
});

test("historical map preserves partial and controlled unavailable semantics", async ({ page }) => {
  const partial = createPartialHistoricalModelGeoBudgetFixture();
  await installNavigationRoutes(page, { historicalGeoBudget: partial });
  await page.goto("/");

  const map = page.getByRole("group", {
    name: "Карта исторического рекламного бюджета модели по географиям",
  });
  await expect(map).toBeVisible();
  await expect(map.locator("[data-map-marker]")).toHaveCount(219);
  await expect(page.getByText("Частичное покрытие", { exact: true })).toBeVisible();
  await expect(page.getByText("Не удалось разместить географий: 1", { exact: true })).toBeVisible();
  const coverageNotice = page.getByText("Частичное покрытие", { exact: true })
    .locator("..").locator("..");
  await expect(coverageNotice).toContainText("Неразмещенный бюджет:");
  await page.getByText("Показать географии", { exact: true }).click();
  await expect(page.getByText(partial.coverage.unlocated_geographies[0].geo_display_name, {
    exact: true,
  })).toBeVisible();

  await page.unroute("**/api/v1/**");
  await installAuthenticatedAdminSession(page);
  const unavailable = createUnavailableHistoricalModelGeoBudgetFixture();
  await installNavigationRoutes(page, { historicalGeoBudget: unavailable });
  await page.goto("/");
  await expect(page.getByText("Карта пока недоступна", { exact: true })).toBeVisible();
  await expect(page.getByText("Исторические расходы активной модели временно недоступны.", {
    exact: true,
  })).toBeVisible();
  const unavailableSection = page.locator("section").filter({
    has: page.getByRole("heading", {
      name: "Исторический рекламный бюджет в данных модели",
    }),
  });
  await expect(unavailableSection.getByText("Общий рекламный бюджет").locator(".."))
    .toContainText("Нет данных");
  await expect(unavailableSection.getByText("Географий", { exact: true }).locator(".."))
    .toContainText("Нет данных");
  await expect(page.getByRole("group", {
    name: "Карта исторического рекламного бюджета модели по географиям",
  })).toHaveCount(0);
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
    historicalGeoBudget: {
      ...createHistoricalModelGeoBudgetFixture(),
      schema_version: "2.0.0",
    },
  });
  await page.goto("/");
  await expect(page.getByText("Формат данных карты не поддерживается", { exact: true }))
    .toBeVisible();
  await expect(page.getByText(/непроверенные координаты или бюджеты/)).toBeVisible();
  await expect(page.getByText("Общий рекламный бюджет")).toHaveCount(0);
  await expect(page.getByRole("heading", {
    name: "Планируйте бюджет и проверяйте результат в одном месте",
  })).toBeVisible();

  await page.unroute("**/api/v1/**");
  await installAuthenticatedAdminSession(page);
  await installNavigationRoutes(page, {
    passport: { ...createModelPassportV2Fixture(), schema_version: "3.0.0" },
  });
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Формат сведений не поддерживается" })).toBeVisible();
});

test("loading and HTTP failure states remain controlled", async ({ page }) => {
  await installNavigationRoutes(page, { geoDelayMs: 600 });
  const navigation = page.goto("/");
  await expect(page.getByRole("status").filter({ hasText: "Загружаем карту бюджета" }))
    .toBeVisible();
  await navigation;
  await expect(page.getByRole("heading", { name: "Что происходит сейчас" })).toBeVisible();

  await page.unroute("**/api/v1/**");
  await installAuthenticatedAdminSession(page);
  await installNavigationRoutes(page, { status: 503 });
  await page.goto("/help");
  await expect(page.getByRole("heading", { name: "Сведения временно недоступны" })).toBeVisible();
});

test("a geo endpoint network error does not replace the Home page", async ({ page }) => {
  const guard = await installNavigationRoutes(page, { historicalGeoBudgetStatus: 503 });
  await page.goto("/");

  await expect(page.getByRole("heading", {
    name: "Планируйте бюджет и проверяйте результат в одном месте",
  })).toBeVisible();
  await expect(page.getByText("Не удалось загрузить карту", { exact: true })).toBeVisible();
  await expect(page.getByText(
    "Остальные сведения на странице сохранены. Повторите запрос.",
    { exact: true },
  )).toBeVisible();
  await expect(page.getByRole("button", { name: "Повторить" })).toBeVisible();
  await expect(page.getByText("Общий рекламный бюджет")).toHaveCount(0);
  expect(guard.allowed.filter((call) => call === "/api/v1/model/historical-geo-budget"))
    .toHaveLength(1);
  expect(guard.allowed.some((call) => call.startsWith("/api/v1/workspace/geo-budget"))).toBe(false);
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
      if (path === "/") await expectMapLabelsInsideCanvasWithoutOverlap(page);
    }
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`@review-e1f Home historical map and tooltip ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1_440, height: 900 });
    await setTheme(page, theme);
    await installNavigationRoutes(page);
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const map = page.getByRole("group", {
      name: "Карта исторического рекламного бюджета модели по географиям",
    });
    await expect(map.locator("[data-map-marker]")).toHaveCount(220);
    await expect(map.locator("[data-map-label]")).toHaveCount(10);
    await expectNoOverflow(page);
    await expectNoForbiddenCopy(page);
    await captureHistoricalGeoReview(page, `home-historical-${theme}.png`);

    await map.locator("[data-map-marker]").last().focus();
    await expect(page.getByRole("tooltip")).toBeVisible();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toContainText("Исторический рекламный бюджет");
    await expect(tooltip).not.toContainText("Дней с рекламной активностью");
    await expect(tooltip).toContainText("Период данных");
    await expect(tooltip).not.toContainText("Кампаний");
    await captureHistoricalGeoReview(page, `home-historical-tooltip-${theme}.png`);
  });
}

test("@review-e1f Home historical unavailable light", async ({ page }) => {
  await page.setViewportSize({ width: 1_440, height: 900 });
  await setTheme(page, "light");
  await installNavigationRoutes(page, {
    historicalGeoBudget: createUnavailableHistoricalModelGeoBudgetFixture(),
  });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByText("Карта пока недоступна", { exact: true })).toBeVisible();
  await expect(page.getByText("Исторические расходы активной модели временно недоступны.", {
    exact: true,
  })).toBeVisible();
  await expectNoOverflow(page);
  await captureHistoricalGeoReview(page, "home-historical-unavailable-light.png");
});

test("@review-e1f Home historical mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setTheme(page, "light");
  await installNavigationRoutes(page);
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const map = page.getByRole("group", {
    name: "Карта исторического рекламного бюджета модели по географиям",
  });
  await expect(map).toBeVisible();
  await expect(map.locator('[data-map-label][data-mobile-visible="true"]')).toHaveCount(5);
  await expectNoOverflow(page);
  await captureHistoricalGeoReview(page, "home-historical-mobile.png");
});

test("the product-navigation allowlist contains only approved projections", () => {
  expect([...ALLOWED_PATHS]).toEqual([
    "/api/v1/workspace/home",
    "/api/v1/model/historical-geo-budget",
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
