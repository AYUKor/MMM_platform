import { expect, test, type Page, type Route } from "@playwright/test";
import { fileURLToPath } from "node:url";
import type {
  CalculationHistoryV1,
  HistoryItem,
} from "../src/shared/api/generated/calculation-history-v1";
import type { ModelOverviewV1 } from "../src/shared/api/generated/model-overview-v1";
import type { WorkspaceHomeV1 } from "../src/shared/api/generated/workspace-home-v1";
import {
  createCalculationHistoryFixture,
  createHelpCatalogFixture,
  createModelOverviewFixture,
  createWorkspaceHomeFixture,
  SYNTHETIC_NAVIGATION_BADGE,
} from "../src/test/productNavigationFixtures";
import { installAuthenticatedAdminSession } from "./support/auth";

const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/phase-d-navigation-v1/", import.meta.url),
);

const ALLOWED_API_PATHS = new Set([
  "/api/v1/workspace/home",
  "/api/v1/calculations/history",
  "/api/v1/model/overview",
  "/api/v1/help/catalog",
]);

const RAW_COPY = [
  /\bbackend\b/i,
  /\bAPI\b/i,
  /\bworker\b/i,
  /registry key/i,
  /\bfilesystem\b/i,
  /model_id/i,
  /page_size/i,
  /created_from/i,
  /created_to/i,
  /Кампания, сегмент или номер расчета/i,
] as const;

const SMALL_CONTENT_TARGETS = [
  { name: "home compact facts", selector: '[class*="compactFacts"] dt' },
  { name: "home warnings", selector: '[class*="warningList"] span' },
  { name: "model scope", selector: '[class*="scopeStrip"] small' },
  { name: "model list indexes", selector: '[class*="listIndex"]' },
  { name: "model limitations", selector: '[class*="limitationsList"] small' },
  { name: "model versions", selector: '[class*="versionList"] span' },
  { name: "model artifacts", selector: '[class*="artifactList"] span' },
  { name: "model requirements", selector: '[class*="requirementsList"] small' },
  { name: "model update timestamp", selector: '[class*="updatedLine"]' },
  { name: "help search results", selector: '[class*="helpResultList"] span' },
  { name: "mobile history facts", selector: '[class*="historyCardFacts"] dt' },
  { name: "sidebar brand", selector: '[class*="brandCopy"] small' },
  { name: "sidebar administration", selector: '[class*="adminLabel"]' },
  { name: "sidebar identity", selector: '[class*="identityCopy"] small' },
] as const;

const SMALL_CONTENT_SELECTOR = SMALL_CONTENT_TARGETS
  .map((target) => target.selector)
  .join(", ");

type JsonResponse = {
  status?: number;
  payload: unknown;
  delayMs?: number;
};

type HistoryResponder = (
  url: URL,
  requestIndex: number,
) => JsonResponse;

interface NavigationRouteOptions {
  home?: JsonResponse;
  history?: HistoryResponder;
  model?: JsonResponse;
  help?: JsonResponse;
}

interface NavigationRouteGuard {
  allowedCalls: string[];
  forbiddenCalls: string[];
}

const routeGuards = new WeakMap<Page, NavigationRouteGuard>();

test.beforeEach(async ({ page }) => {
  await installAuthenticatedAdminSession(page);
});

test.afterEach(async ({ page }) => {
  const guard = routeGuards.get(page);
  if (guard) {
    expect(guard.forbiddenCalls, "legacy or unapproved product API calls").toEqual([]);
  }
});

function clone<T>(value: T): T {
  return structuredClone(value);
}

function errorPayload(
  code: string,
  displayText: string,
  retryable = true,
) {
  return {
    error: {
      code,
      display_text: displayText,
      retryable,
      user_action: "Проверьте параметры и повторите запрос.",
    },
  };
}

async function fulfill(route: Route, response: JsonResponse) {
  if (response.delayMs) {
    await new Promise((resolve) => setTimeout(resolve, response.delayMs));
  }
  await route.fulfill({
    status: response.status ?? 200,
    contentType: "application/json",
    body: JSON.stringify(response.payload),
  });
}

function historyQuery(url: URL) {
  const page = Number(url.searchParams.get("page") ?? "1");
  const pageSize = Number(url.searchParams.get("page_size") ?? "25");
  return {
    page,
    pageSize,
    status: url.searchParams.get("status"),
    search: url.searchParams.get("search"),
    createdFrom: url.searchParams.get("created_from"),
    createdTo: url.searchParams.get("created_to"),
    sort: url.searchParams.get("sort") ?? "created_desc",
  };
}

function historySummary(items: readonly HistoryItem[]): CalculationHistoryV1["summary"] {
  const summary: CalculationHistoryV1["summary"] = {
    all: items.length,
    active: 0,
    succeeded: 0,
    failed: 0,
    cancelled: 0,
    timed_out: 0,
  };
  for (const item of items) {
    if (["queued", "running", "cancel_requested"].includes(item.status)) {
      summary.active += 1;
    } else {
      summary[item.status] += 1;
    }
  }
  return summary;
}

function compareHistory(left: HistoryItem, right: HistoryItem, sort: string): number {
  if (sort === "campaign_asc") {
    return left.campaign_name.localeCompare(right.campaign_name, "ru") ||
      left.job_id.localeCompare(right.job_id);
  }
  if (sort === "completed_desc") {
    const leftTime = left.completed_at_utc ?? "";
    const rightTime = right.completed_at_utc ?? "";
    return rightTime.localeCompare(leftTime) || right.job_id.localeCompare(left.job_id);
  }
  const direction = sort === "created_asc" ? 1 : -1;
  return direction * left.created_at_utc.localeCompare(right.created_at_utc) ||
    left.job_id.localeCompare(right.job_id);
}

function historyResponse(
  url: URL,
  source = createCalculationHistoryFixture(),
): CalculationHistoryV1 {
  const query = historyQuery(url);
  let items = [...source.items];
  if (query.status === "active") {
    items = items.filter((item) => ["queued", "running", "cancel_requested"].includes(item.status));
  } else if (query.status) {
    items = items.filter((item) => item.status === query.status);
  }
  if (query.search) {
    const search = query.search.toLocaleLowerCase("ru-RU");
    items = items.filter((item) =>
      item.campaign_name.toLocaleLowerCase("ru-RU").includes(search) ||
      item.job_id.toLocaleLowerCase("ru-RU").includes(search) ||
      (item.segments ?? []).some((segment) =>
        segment.toLocaleLowerCase("ru-RU").includes(search),
      ),
    );
  }
  if (query.createdFrom) {
    items = items.filter((item) => item.created_at_utc.slice(0, 10) >= query.createdFrom!);
  }
  if (query.createdTo) {
    items = items.filter((item) => item.created_at_utc.slice(0, 10) <= query.createdTo!);
  }
  items.sort((left, right) => compareHistory(left, right, query.sort));
  const totalItems = items.length;
  const totalPages = totalItems === 0 ? 0 : Math.ceil(totalItems / query.pageSize);
  const start = (query.page - 1) * query.pageSize;
  return {
    ...clone(source),
    filters: {
      status: query.status as CalculationHistoryV1["filters"]["status"],
      search: query.search,
      created_from: query.createdFrom,
      created_to: query.createdTo,
      sort: query.sort as CalculationHistoryV1["filters"]["sort"],
    },
    pagination: {
      page: query.page,
      page_size: query.pageSize,
      total_items: totalItems,
      total_pages: totalPages,
    },
    items: items.slice(start, start + query.pageSize),
  };
}

function manyHistoryRows(total = 32): CalculationHistoryV1 {
  const source = createCalculationHistoryFixture();
  const statuses: HistoryItem["status"][] = [
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
  ];
  const items = Array.from({ length: total }, (_, index) => {
    const base = clone(source.items[index % source.items.length]);
    const value = index + 1;
    const status = statuses[index % statuses.length];
    const terminal = !["running", "queued", "cancel_requested"].includes(status);
    const succeeded = status === "succeeded";
    base.job_id = `job_${value.toString(16).padStart(12, "0")}`;
    base.campaign_name = `Демонстрационная кампания ${String(value).padStart(2, "0")}`;
    base.created_at_utc = `2026-07-${String(1 + (index % 17)).padStart(2, "0")}T08:00:00Z`;
    base.completed_at_utc = terminal
      ? `2026-07-${String(1 + (index % 17)).padStart(2, "0")}T08:10:00Z`
      : null;
    base.status = status;
    base.status_display_text = status === "running"
      ? "Выполняется"
      : status === "succeeded"
        ? "Расчет завершен"
        : status === "failed"
          ? "Расчет завершился с ошибкой"
          : status === "cancelled"
            ? "Расчет отменен"
            : "Превышено время";
    base.progress_path = `/calculations/${base.job_id}/progress`;
    base.result_available = succeeded;
    base.report_available = succeeded;
    base.result_path = succeeded ? `/calculations/${base.job_id}/result` : null;
    return base;
  });
  return {
    ...source,
    summary: historySummary(items),
    pagination: {
      page: 1,
      page_size: 25,
      total_items: items.length,
      total_pages: Math.ceil(items.length / 25),
    },
    items,
  };
}

function emptyHome(): WorkspaceHomeV1 {
  const value = createWorkspaceHomeFixture();
  value.summary = { running: 0, queued: 0, completed_30d: 0, failed_30d: 0 };
  value.active_calculations = [];
  value.recent_calculations = [];
  value.warnings = [];
  return value;
}

function unavailableModel(): ModelOverviewV1 {
  const value = createModelOverviewFixture();
  value.active_model = {
    ...value.active_model,
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
  value.capabilities = value.capabilities.map((item) => ({
    ...item,
    status: "unavailable",
  })) as ModelOverviewV1["capabilities"];
  value.versions = [];
  return value;
}

async function installNavigationRoutes(
  page: Page,
  options: NavigationRouteOptions = {},
): Promise<NavigationRouteGuard> {
  const guard: NavigationRouteGuard = { allowedCalls: [], forbiddenCalls: [] };
  routeGuards.set(page, guard);

  // Register the catch-all first. Playwright invokes the more recently
  // registered exact handlers below before this guard.
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/v1/auth/session" && url.search === "") {
      await route.fallback();
      return;
    }
    guard.forbiddenCalls.push(`${request.method()} ${url.pathname}`);
    await route.fulfill({ status: 599, body: "blocked unapproved product endpoint" });
  });

  const exactHandler = async (
    route: Route,
    path: string,
    response: JsonResponse,
  ) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== "GET" || url.pathname !== path || url.search) {
      guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed product request" });
      return;
    }
    guard.allowedCalls.push(`${request.method()} ${url.pathname}`);
    await fulfill(route, response);
  };

  await page.route("**/api/v1/workspace/home", (route) => exactHandler(
    route,
    "/api/v1/workspace/home",
    options.home ?? { payload: createWorkspaceHomeFixture() },
  ));

  let historyCalls = 0;
  await page.route("**/api/v1/calculations/history*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== "GET" || url.pathname !== "/api/v1/calculations/history") {
      guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed history request" });
      return;
    }
    for (const required of ["page", "page_size", "sort"]) {
      if (!url.searchParams.has(required)) {
        guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
        await route.fulfill({ status: 599, body: "blocked incomplete history request" });
        return;
      }
    }
    guard.allowedCalls.push(`${request.method()} ${url.pathname}${url.search}`);
    const response = options.history?.(url, historyCalls) ?? {
      payload: historyResponse(url),
    };
    historyCalls += 1;
    await fulfill(route, response);
  });

  await page.route("**/api/v1/model/overview", (route) => exactHandler(
    route,
    "/api/v1/model/overview",
    options.model ?? { payload: createModelOverviewFixture() },
  ));

  await page.route("**/api/v1/help/catalog", (route) => exactHandler(
    route,
    "/api/v1/help/catalog",
    options.help ?? { payload: createHelpCatalogFixture() },
  ));

  return guard;
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

async function expectNoDocumentOverflow(page: Page) {
  const diagnostic = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const offenders = [...document.querySelectorAll<HTMLElement>("body *")]
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          element: element.tagName.toLowerCase(),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        };
      })
      .filter((item) => item.width > 0 && item.right > viewportWidth + 1)
      .slice(0, 12);
    return {
      overflow: document.documentElement.scrollWidth - viewportWidth,
      offenders,
    };
  });
  expect(diagnostic.overflow, JSON.stringify(diagnostic, null, 2)).toBeLessThanOrEqual(0);
}

async function expectNoRawCopy(page: Page) {
  const accessibilityCopy = await page.locator("body").evaluate((body) => {
    const attributes = [...body.querySelectorAll<HTMLElement>(
      "[aria-label], [title], [placeholder]",
    )]
      .flatMap((element) => [
        element.getAttribute("aria-label"),
        element.getAttribute("title"),
        element.getAttribute("placeholder"),
      ])
      .filter((value): value is string => value !== null);
    return [body.innerText, ...attributes].join("\n");
  });
  for (const pattern of RAW_COPY) expect(accessibilityCopy).not.toMatch(pattern);
}

type ContrastSample = {
  background: string;
  color: string;
  ratio: number;
  target: string;
  text: string;
};

async function measureSmallContentContrast(page: Page): Promise<ContrastSample[]> {
  return page.locator(SMALL_CONTENT_SELECTOR).evaluateAll((elements, targets) => {
    type Rgba = { r: number; g: number; b: number; a: number };

    const parseColor = (value: string): Rgba => {
      if (value === "transparent") return { r: 0, g: 0, b: 0, a: 0 };
      if (value.startsWith("color(srgb")) {
        const channels = value.match(/[\d.]+/g)?.map(Number) ?? [];
        return {
          r: (channels[0] ?? 0) * 255,
          g: (channels[1] ?? 0) * 255,
          b: (channels[2] ?? 0) * 255,
          a: channels[3] ?? 1,
        };
      }
      const channels = value.match(/[\d.]+/g)?.map(Number) ?? [];
      return {
        r: channels[0] ?? 0,
        g: channels[1] ?? 0,
        b: channels[2] ?? 0,
        a: channels[3] ?? 1,
      };
    };

    const over = (foreground: Rgba, background: Rgba): Rgba => {
      const alpha = foreground.a + background.a * (1 - foreground.a);
      if (alpha === 0) return { r: 0, g: 0, b: 0, a: 0 };
      return {
        r: (foreground.r * foreground.a + background.r * background.a *
          (1 - foreground.a)) / alpha,
        g: (foreground.g * foreground.a + background.g * background.a *
          (1 - foreground.a)) / alpha,
        b: (foreground.b * foreground.a + background.b * background.a *
          (1 - foreground.a)) / alpha,
        a: alpha,
      };
    };

    const luminance = ({ r, g, b }: Rgba) => {
      const linear = [r, g, b].map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
    };

    const contrast = (left: Rgba, right: Rgba) => {
      const lighter = Math.max(luminance(left), luminance(right));
      const darker = Math.min(luminance(left), luminance(right));
      return (lighter + 0.05) / (darker + 0.05);
    };

    return elements.flatMap((element) => {
      const htmlElement = element as HTMLElement;
      const rect = htmlElement.getBoundingClientRect();
      const text = htmlElement.innerText.trim();
      if (rect.width === 0 || rect.height === 0 || text.length === 0) return [];

      let background: Rgba = { r: 0, g: 0, b: 0, a: 0 };
      let ancestor: Element | null = htmlElement;
      while (ancestor) {
        const layer = parseColor(getComputedStyle(ancestor).backgroundColor);
        background = over(background, layer);
        ancestor = ancestor.parentElement;
      }
      background = over(background, { r: 255, g: 255, b: 255, a: 1 });
      const colorValue = getComputedStyle(htmlElement).color;
      const foreground = over(parseColor(colorValue), background);
      const ratio = contrast(foreground, background);

      return targets
        .filter((target) => htmlElement.matches(target.selector))
        .map((target) => ({
          background: `rgb(${Math.round(background.r)}, ${Math.round(background.g)}, ${Math.round(background.b)})`,
          color: colorValue,
          ratio,
          target: target.name,
          text: text.slice(0, 80),
        }));
    });
  }, SMALL_CONTENT_TARGETS);
}

async function expectSyntheticBadge(page: Page) {
  await expect(page.getByText(SYNTHETIC_NAVIGATION_BADGE, { exact: true }).first()).toBeVisible();
}

async function captureExactViewport(page: Page, fileName: string) {
  await page.evaluate(async () => { await document.fonts.ready; });
  const image = await page.screenshot({
    path: `${REVIEW_DIRECTORY}${fileName}`,
    animations: "disabled",
    caret: "hide",
    fullPage: false,
    scale: "css",
  });
  expect(image.readUInt32BE(16)).toBe(1_440);
  expect(image.readUInt32BE(20)).toBe(900);
}

type ScreenshotCase = {
  stem: string;
  path: string;
  heading: string;
  reviewFocus?: string;
  options?: NavigationRouteOptions;
};

const screenshotCases: readonly ScreenshotCase[] = [
  {
    stem: "01-home-active",
    path: "/",
    heading: "Планируйте бюджет",
    reviewFocus: "Активные расчеты",
  },
  {
    stem: "02-home-empty",
    path: "/",
    heading: "Планируйте бюджет",
    reviewFocus: "Активные расчеты",
    options: { home: { payload: emptyHome() } },
  },
  {
    stem: "03-history",
    path: "/calculations",
    heading: "История расчетов",
    options: {
      history: (url) => ({ payload: historyResponse(url, manyHistoryRows()) }),
    },
  },
  {
    stem: "04-history-filtered",
    path: "/calculations?status=failed&search=ошибкой&sort=created_desc&page=1&page_size=25",
    heading: "История расчетов",
  },
  {
    stem: "05-model",
    path: "/model",
    heading: "Модель",
  },
  {
    stem: "06-model-unavailable",
    path: "/model",
    heading: "Модель",
    options: { model: { payload: unavailableModel() } },
  },
  {
    stem: "07-help",
    path: "/help?section=scenarios&article=scenarios_s1_s6",
    heading: "Справка",
  },
  {
    stem: "08-error-states",
    path: "/help",
    heading: "Сведения временно недоступны",
    options: {
      help: {
        status: 503,
        payload: errorPayload(
          "PRODUCT_NAVIGATION_UNAVAILABLE",
          "Сведения для этой страницы временно недоступны.",
        ),
      },
    },
  },
] as const;

test.describe("Phase D review screenshots", () => {
  for (const screenshotCase of screenshotCases) {
    for (const theme of ["dark", "light"] as const) {
      test(`${screenshotCase.stem}-${theme}`, async ({ page }) => {
        await page.setViewportSize({ width: 1_440, height: 900 });
        await setTheme(page, theme);
        await installNavigationRoutes(page, screenshotCase.options);
        await page.goto(screenshotCase.path);
        await expect(page.getByRole("heading", {
          name: screenshotCase.heading,
          exact: false,
        }).first()).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        if (screenshotCase.stem !== "08-error-states") await expectSyntheticBadge(page);
        await expectNoDocumentOverflow(page);
        await expectNoRawCopy(page);
        if (screenshotCase.reviewFocus) {
          const reviewFocus = page.getByRole("heading", {
            name: screenshotCase.reviewFocus,
            exact: true,
          });
          await reviewFocus.scrollIntoViewIfNeeded();
          await page.evaluate(() => window.scrollBy(0, -120));
        }
        await captureExactViewport(page, `${screenshotCase.stem}-${theme}.png`);
      });
    }
  }
});

test.describe("Phase D endpoint and state boundary", () => {
  test("each product page uses only its approved projection", async ({ page }) => {
    const guard = await installNavigationRoutes(page);
    for (const [path, heading] of [
      ["/", "Планируйте бюджет"],
      ["/calculations", "История расчетов"],
      ["/model", "Модель"],
      ["/help", "Справка"],
    ] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, exact: false }).first()).toBeVisible();
    }
    expect(guard.allowedCalls.some((call) => call.includes("/api/v1/workspace/home"))).toBe(true);
    expect(guard.allowedCalls.some((call) => call.includes("/api/v1/calculations/history"))).toBe(true);
    expect(guard.allowedCalls.some((call) => call.includes("/api/v1/model/overview"))).toBe(true);
    expect(guard.allowedCalls.some((call) => call.includes("/api/v1/help/catalog"))).toBe(true);
  });

  test("loading composition is announced and replaced with ready content", async ({ page }) => {
    await installNavigationRoutes(page, {
      home: { payload: createWorkspaceHomeFixture(), delayMs: 500 },
    });
    const navigation = page.goto("/");
    await expect(
      page.getByRole("status").filter({ hasText: "Загрузка рабочего пространства" }),
    ).toBeVisible();
    await navigation;
    await expect(page.getByRole("heading", { name: "Планируйте бюджет", exact: false })).toBeVisible();
  });

  test("home distinguishes known zero from unavailable business facts", async ({ page }) => {
    const home = createWorkspaceHomeFixture();
    home.summary.queued = 0;
    await installNavigationRoutes(page, { home: { payload: home } });
    await page.goto("/");
    await expect(page.getByText("В очереди", { exact: true }).locator("..")).toContainText("0");
    const missingCampaign = page
      .getByText("Демонстрационная кампания с ошибкой", { exact: true })
      .first()
      .locator("xpath=ancestor::li[1]");
    await expect(missingCampaign).toContainText("Нет данных");
    await expect(missingCampaign).not.toContainText("0 ₽");
  });

  test("home renders contract-backed active and honest empty states", async ({ page }) => {
    await installNavigationRoutes(page);
    await page.goto("/");
    await expect(page.getByText("Демонстрационная активная кампания", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Открыть ход расчета" })).toHaveAttribute(
      "href",
      "/calculations/job_000000000001/progress",
    );

    await page.unroute("**/api/v1/workspace/home");
    await page.route("**/api/v1/workspace/home", async (route) => {
      await fulfill(route, { payload: emptyHome() });
    });
    await page.reload();
    await expect(page.getByText("Активных расчетов нет", { exact: true })).toBeVisible();
    await expect(page.getByText("Завершенных расчетов пока нет", { exact: true })).toBeVisible();
  });

  test("model unavailable is explicit and contains no invented score or version", async ({ page }) => {
    await installNavigationRoutes(page, { model: { payload: unavailableModel() } });
    await page.goto("/model");
    await expect(page.getByRole("heading", {
      name: "Сведения об активной модели пока недоступны",
      exact: false,
    })).toBeVisible();
    const text = await page.locator("body").innerText();
    expect(text).not.toMatch(/\b[1-9]\/10\b/);
    expect(text).not.toContain("run_synthetic_v1");
    await expect(page.getByText("История версий пока недоступна", { exact: true })).toBeVisible();
  });

  test("unsupported contract fails closed", async ({ page }) => {
    const payload = { ...createModelOverviewFixture(), schema_version: "2.0.0" };
    await installNavigationRoutes(page, { model: { payload } });
    await page.goto("/model");
    await expect(page.getByRole("heading", { name: "Формат сведений не поддерживается" })).toBeVisible();
    await expect(page.getByText("Демонстрационная MMM", { exact: true })).toHaveCount(0);
  });

  for (const [status, code, heading] of [
    [404, "ROUTE_NOT_FOUND", "Раздел не найден"],
    [409, "PRODUCT_NAVIGATION_INCONSISTENT", "Опубликованные сведения временно не согласованы"],
    [503, "PRODUCT_NAVIGATION_UNAVAILABLE", "Сведения временно недоступны"],
  ] as const) {
    test(`renders controlled HTTP ${status}`, async ({ page }) => {
      await installNavigationRoutes(page, {
        help: {
          status,
          payload: errorPayload(code, "Контролируемое пользовательское состояние."),
        },
      });
      await page.goto("/help");
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
      await expectNoRawCopy(page);
    });
  }
});

test.describe("Phase D history server state", () => {
  test("URL restores filters, sort and page through backend requests", async ({ page }) => {
    const source = manyHistoryRows();
    const guard = await installNavigationRoutes(page, {
      history: (url) => ({ payload: historyResponse(url, source) }),
    });
    const first = "/calculations?status=failed&search=кампания&created_from=2026-07-01&created_to=2026-07-17&sort=campaign_asc&page=1&page_size=10";
    const second = "/calculations?status=active&sort=created_desc&page=1&page_size=25";
    await page.goto(first);
    await expect(page.getByRole("heading", { name: "История расчетов" })).toBeVisible();
    await page.goto(second);
    await expect(page).toHaveURL(new RegExp("status=active"));
    await page.goBack();
    await expect(page).toHaveURL(new RegExp("status=failed"));
    await expect(page).toHaveURL(new RegExp("sort=campaign_asc"));
    await page.goForward();
    await expect(page).toHaveURL(new RegExp("status=active"));
    await page.reload();
    await expect(page).toHaveURL(new RegExp("page_size=25"));
    expect(guard.allowedCalls.some((call) => call.includes("status=failed"))).toBe(true);
    expect(guard.allowedCalls.some((call) => call.includes("status=active"))).toBe(true);
  });

  test("changing sort preserves draft search and dates until filters are applied", async ({ page }) => {
    const guard = await installNavigationRoutes(page);
    await page.goto("/calculations");
    const search = page.getByLabel("Поиск", { exact: true });
    const createdFrom = page.getByLabel("Создан с", { exact: true });
    const createdTo = page.getByLabel("Создан по", { exact: true });
    await expect(search).toHaveAttribute("placeholder", "Поиск по названию кампании");
    await expect(page.getByPlaceholder("Кампания, сегмент или номер расчета")).toHaveCount(0);
    await search.fill("кампания");
    await createdFrom.fill("2026-07-01");
    await createdTo.fill("2026-07-17");
    await page.getByRole("combobox", { name: "Сортировка", exact: true })
      .selectOption("campaign_asc");
    await expect(search).toHaveValue("кампания");
    await expect(createdFrom).toHaveValue("2026-07-01");
    await expect(createdTo).toHaveValue("2026-07-17");
    await page.getByRole("button", { name: "Применить", exact: true }).click();
    await expect(page).toHaveURL(new RegExp("created_to=2026-07-17"));
    const appliedQuery = new URL(page.url()).searchParams;
    expect(appliedQuery.get("search")).toBe("кампания");
    expect(appliedQuery.get("created_from")).toBe("2026-07-01");
    expect(appliedQuery.get("created_to")).toBe("2026-07-17");
    expect(guard.allowedCalls.some((call) =>
      call.includes("search=%D0%BA%D0%B0%D0%BC%D0%BF%D0%B0%D0%BD%D0%B8%D1%8F") &&
      call.includes("created_from=2026-07-01") &&
      call.includes("created_to=2026-07-17") &&
      call.includes("sort=campaign_asc")
    )).toBe(true);
  });

  test("pagination is server-side and replaces rows from the returned page", async ({ page }) => {
    const source = manyHistoryRows();
    const guard = await installNavigationRoutes(page, {
      history: (url) => ({ payload: historyResponse(url, source) }),
    });
    await page.goto("/calculations?page=1&page_size=10");
    const firstPageName = "Демонстрационная кампания 17";
    const table = page.getByRole("table");
    await expect(table.getByText(firstPageName, { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Далее", exact: true }).click();
    await expect(page).toHaveURL(new RegExp("page=2"));
    await expect(table.getByText(firstPageName, { exact: true })).toHaveCount(0);
    expect(guard.allowedCalls.some((call) => call.includes("page=2"))).toBe(true);
  });

  test("empty history, filtered empty and search empty have distinct copy", async ({ page }) => {
    const empty = createCalculationHistoryFixture();
    empty.summary = historySummary([]);
    empty.items = [];
    empty.pagination = { page: 1, page_size: 25, total_items: 0, total_pages: 0 };
    await installNavigationRoutes(page, {
      history: (url) => ({ payload: historyResponse(url, empty) }),
    });
    await page.goto("/calculations");
    await expect(page.getByText("Расчетов пока нет", { exact: true })).toBeVisible();

    await page.unroute("**/api/v1/calculations/history*");
    const nonEmptySource = createCalculationHistoryFixture();
    await page.route("**/api/v1/calculations/history*", async (route) => {
      const url = new URL(route.request().url());
      await fulfill(route, { payload: historyResponse(url, nonEmptySource) });
    });
    await page.goto("/calculations?status=cancelled");
    await expect(page.getByText("Нет результатов по выбранным фильтрам", { exact: true })).toBeVisible();
    await page.goto("/calculations?search=несуществующая-кампания");
    await expect(page.getByText("Поиск ничего не нашел", { exact: true })).toBeVisible();
  });

  test("422 keeps the last visible snapshot across multiple cached history queries", async ({ page }) => {
    const displayText = "Диапазон дат заполнен некорректно.";
    const firstSource = createCalculationHistoryFixture();
    firstSource.items = [clone(firstSource.items[1])];
    firstSource.items[0].campaign_name = "Последний видимый снимок A";
    firstSource.summary = historySummary(firstSource.items);
    firstSource.pagination = { page: 1, page_size: 25, total_items: 1, total_pages: 1 };
    const secondSource = createCalculationHistoryFixture();
    secondSource.items = [clone(secondSource.items[2])];
    secondSource.items[0].campaign_name = "Промежуточный снимок B";
    secondSource.summary = historySummary(secondSource.items);
    secondSource.pagination = { page: 1, page_size: 25, total_items: 1, total_pages: 1 };
    await installNavigationRoutes(page, {
      history: (url) => url.searchParams.has("created_from")
        ? {
            status: 422,
            payload: errorPayload("PRODUCT_NAVIGATION_QUERY_INVALID", displayText),
          }
        : url.searchParams.get("status") === "failed"
          ? { payload: historyResponse(url, secondSource) }
          : { payload: historyResponse(url, firstSource) },
    });
    await page.goto("/calculations");
    const table = page.getByRole("table");
    await expect(table.getByText("Последний видимый снимок A", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /С ошибкой/ }).click();
    await expect(table.getByText("Промежуточный снимок B", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /^Все/ }).click();
    await expect(table.getByText("Последний видимый снимок A", { exact: true })).toBeVisible();
    await page.getByLabel("Создан с", { exact: true }).fill("2026-07-20");
    await page.getByLabel("Создан по", { exact: true }).fill("2026-07-10");
    await page.getByRole("button", { name: /применить/i }).click();
    await expect(page.getByRole("status").filter({ hasText: displayText })).toBeVisible();
    await expect(table.getByText("Последний видимый снимок A", { exact: true })).toBeVisible();
    await expect(table.getByText("Промежуточный снимок B", { exact: true })).toHaveCount(0);
  });

  test("history renders null as unavailable and a known zero as zero", async ({ page }) => {
    const source = createCalculationHistoryFixture();
    const zero = clone(source.items[1]);
    zero.job_id = "job_000000000004";
    zero.campaign_name = "Демонстрационная кампания с нулевыми значениями";
    zero.total_budget_rub = 0;
    zero.channels_n = 0;
    zero.geographies_n = 0;
    zero.warnings_count = 0;
    zero.progress_path = "/calculations/job_000000000004/progress";
    zero.result_path = "/calculations/job_000000000004/result";
    source.items.push(zero);
    source.summary.succeeded += 1;
    source.summary.all += 1;
    await installNavigationRoutes(page, {
      history: (url) => ({ payload: historyResponse(url, source) }),
    });
    await page.goto("/calculations");
    const table = page.getByRole("table");
    const missing = table.getByRole("row").filter({
      hasText: "Демонстрационная кампания с ошибкой",
    });
    await expect(missing).toContainText("Нет данных");
    const knownZero = table.getByRole("row").filter({
      hasText: "Демонстрационная кампания с нулевыми значениями",
    });
    await expect(knownZero).toContainText("0");
    await expect(knownZero).not.toContainText("Нет данных");
  });
});

test.describe("Phase D help URL and keyboard state", () => {
  test("deep link, refresh, back and forward restore the selected article", async ({ page }) => {
    await installNavigationRoutes(page);
    await page.goto("/help?section=scenarios&article=scenarios_s1_s6");
    await expect(page.getByRole("heading", { name: "Зачем нужны шесть сценариев" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Зачем нужны шесть сценариев" })).toBeVisible();
    await page.getByRole("button", { name: /надежность/i }).click();
    await expect(page).toHaveURL(new RegExp("section=reliability"));
    await page.goBack();
    await expect(page).toHaveURL(new RegExp("section=scenarios"));
    await page.goForward();
    await expect(page).toHaveURL(new RegExp("section=reliability"));
  });

  test("help search uses title summary and keywords without requesting another endpoint", async ({ page }) => {
    const guard = await installNavigationRoutes(page);
    await page.goto("/help");
    const searchbox = page.getByRole("searchbox", { name: /поиск/i });
    await expect(searchbox).toBeVisible();
    await expect(page.getByRole("heading", { name: "Справка", exact: true })).toBeVisible();
    const callsBeforeSearch = guard.allowedCalls.filter((call) =>
      call.includes("/api/v1/help/catalog")
    ).length;
    await searchbox.fill("сценарии");
    await expect(page.getByText("Зачем нужны шесть сценариев", { exact: true })).toBeVisible();
    const callsAfterSearch = guard.allowedCalls.filter((call) =>
      call.includes("/api/v1/help/catalog")
    ).length;
    expect(callsAfterSearch).toBe(callsBeforeSearch);
  });

  test("primary navigation and help controls are keyboard accessible", async ({ page }) => {
    await installNavigationRoutes(page);
    await page.goto("/help");
    const sidebar = page.getByRole("complementary", { name: "Основная навигация" });
    const productNavigation = sidebar.getByRole("navigation", { name: "Разделы продукта" });
    await expect(productNavigation.getByRole("link", { name: "Главная" })).toBeVisible();
    const search = page.getByRole("searchbox", { name: /поиск/i });
    await search.focus();
    await expect(search).toBeFocused();
    await search.press("Tab");
    const focused = page.locator(":focus");
    await expect(focused).toBeVisible();
    const outline = await focused.evaluate((element) => {
      const style = getComputedStyle(element);
      return { style: style.outlineStyle, width: style.outlineWidth };
    });
    expect(outline.style).not.toBe("none");
    expect(outline.width).not.toBe("0px");
  });
});

test.describe("Phase D responsive, motion and copy QA", () => {
  for (const viewport of [
    { name: "mobile", width: 375, height: 812 },
    { name: "landscape", width: 812, height: 375 },
  ] as const) {
    test(`${viewport.name} navigation pages do not overflow`, async ({ page }) => {
      const home = createWorkspaceHomeFixture();
      home.active_calculations[0].campaign_name = "Очень длинное название кампании для нескольких регионов и медиаканалов";
      const help = createHelpCatalogFixture();
      help.sections[2].articles[0].body.push({
        block_type: "paragraph",
        text: "Длинное объяснение сценариев проверяет перенос строк, читаемость и отсутствие выхода содержимого за границы экрана. ".repeat(8),
      });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await installNavigationRoutes(page, {
        home: { payload: home },
        history: (url) => ({ payload: historyResponse(url, manyHistoryRows(100)) }),
        help: { payload: help },
      });
      for (const path of [
        "/",
        "/calculations?page=1&page_size=100",
        "/model",
        "/help?section=scenarios&article=scenarios_s1_s6",
      ]) {
        await page.goto(path);
        await expectNoDocumentOverflow(page);
        await expectNoRawCopy(page);
      }
    });
  }

  test("mobile history uses cards without document overflow", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await installNavigationRoutes(page);
    await page.goto("/calculations");
    await expect(page.getByRole("table")).toBeHidden();
    await expect(
      page.getByText("Демонстрационная активная кампания", { exact: true })
        .filter({ visible: true })
        .first(),
    ).toBeVisible();
    await expectNoDocumentOverflow(page);
  });

  for (const theme of ["dark", "light"] as const) {
    test(`small product copy meets WCAG contrast in ${theme} theme`, async ({ page }) => {
      await page.setViewportSize({ width: 1_440, height: 900 });
      await setTheme(page, theme);
      const model = createModelOverviewFixture();
      model.artifacts = [{
        artifact_id: "methodology_note",
        title: "Описание методологии",
        status: "unavailable",
        path: null,
        display_text: "Материал пока недоступен",
      }];
      await installNavigationRoutes(page, { model: { payload: model } });
      const samples: ContrastSample[] = [];

      await page.goto("/");
      await expect(page.getByText("Демонстрационная активная кампания", { exact: true }))
        .toBeVisible();
      samples.push(...await measureSmallContentContrast(page));

      await page.goto("/model");
      await expect(page.getByRole("heading", { name: "Демонстрационная MMM" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Опубликованные материалы" })).toBeVisible();
      samples.push(...await measureSmallContentContrast(page));

      await page.goto("/help");
      await page.getByRole("searchbox", { name: "Поиск по справке" }).fill("сценарии");
      await expect(page.getByRole("heading", { name: "Найденные статьи" })).toBeVisible();
      samples.push(...await measureSmallContentContrast(page));
      await page.locator('[class*="helpResultList"] button').first().hover();
      samples.push(...await measureSmallContentContrast(page));

      await page.setViewportSize({ width: 375, height: 812 });
      await page.goto("/calculations");
      await expect(
        page.getByText("Демонстрационная активная кампания", { exact: true })
          .filter({ visible: true })
          .first(),
      ).toBeVisible();
      await expect(page.getByRole("table")).toBeHidden();
      samples.push(...await measureSmallContentContrast(page));

      const coveredTargets = [...new Set(samples.map((sample) => sample.target))];
      for (const target of SMALL_CONTENT_TARGETS) {
        expect(coveredTargets, `${target.name} was not measured`).toContain(target.name);
      }
      const minimum = samples.reduce((current, sample) =>
        sample.ratio < current.ratio ? sample : current
      );
      test.info().annotations.push({
        type: "contrast",
        description: `${minimum.ratio.toFixed(3)}:1 — ${minimum.text}`,
      });
      console.info(
        `[contrast:${theme}] minimum ${minimum.ratio.toFixed(3)}:1`,
        JSON.stringify(minimum),
      );
      expect(minimum.ratio, JSON.stringify(minimum, null, 2)).toBeGreaterThanOrEqual(4.5);
    });
  }

  test("reduced motion leaves no active looping animations", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await installNavigationRoutes(page);
    await page.goto("/");
    const activeAnimations = await page.locator("body *").evaluateAll((elements) =>
      elements.filter((element) => {
        const style = getComputedStyle(element);
        return style.animationName !== "none" && style.animationDuration !== "0s" &&
          style.animationIterationCount === "infinite";
      }).length,
    );
    expect(activeAnimations).toBe(0);
  });

  test("all four pages contain no raw technical copy", async ({ page }) => {
    await installNavigationRoutes(page);
    for (const path of ["/", "/calculations", "/model", "/help"]) {
      await page.goto(path);
      await expectNoRawCopy(page);
    }
  });

  test("unknown route renders the product 404", async ({ page }) => {
    await installNavigationRoutes(page);
    await page.goto("/unknown-product-section");
    await expect(page.getByRole("heading", { name: "Раздел не найден" })).toBeVisible();
  });
});

test("the allowlist itself contains exactly the four Phase D endpoints", () => {
  expect([...ALLOWED_API_PATHS]).toEqual([
    "/api/v1/workspace/home",
    "/api/v1/calculations/history",
    "/api/v1/model/overview",
    "/api/v1/help/catalog",
  ]);
});
