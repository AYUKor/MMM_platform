import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type {
  JobResultViewV1,
  ScenarioId,
} from "../src/shared/api/generated/job-result-view-v1";
import type {
  MediaPlanRow,
  ScenarioMediaPlanV1,
} from "../src/shared/api/generated/scenario-media-plan-v1";
import {
  createBestRawJobResultFixture,
  createNoSafeJobResultFixture,
  createPartialCoverageJobResultFixture,
  createRecommendedJobResultFixture,
  createReportReadyJobResultFixture,
  createScenarioMediaPlanFixture,
  createUnavailableJobResultFixture,
} from "../src/test/jobResultFixtures";

const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/job-result-v1/", import.meta.url),
);
const SCENARIO_IDS = new Set<ScenarioId>(["S01", "S02", "S03", "S04", "S05", "S06"]);
const RAW_TERMS = [
  "backend",
  "api",
  "worker",
  "posterior",
  "candidate_id",
  "optimizer_raw_rank",
  "optimizer_reliable_rank",
  "scenario_id",
  "page_size",
] as const;
const FORBIDDEN_USER_COPY = [
  "Каноническая рекомендация",
  "Открытый сценарий",
  "Без выдуманной оценки",
  "Готовые сводки сервиса",
  "Интерфейс не пересортировывает",
] as const;

mkdirSync(REVIEW_DIRECTORY, { recursive: true });

type MediaMode = "normal" | "large" | "empty";

interface ProductRouteOptions {
  resultStatus?: number;
  resultErrorCode?: string;
  resultPayload?: unknown;
  resultDelayMs?: number;
  mediaStatus?: number;
  mediaMode?: MediaMode;
  artifactStatus?: number;
}

interface ProductRouteGuard {
  resultViewCalls: number;
  mediaPlanCalls: number;
  artifactCalls: number;
  forbiddenCalls: string[];
}

const routeGuards = new WeakMap<Page, ProductRouteGuard>();

test.afterEach(async ({ page }) => {
  const guard = routeGuards.get(page);
  if (guard) expect(guard.forbiddenCalls, "legacy or unapproved API calls").toEqual([]);
});

function errorPayload(code: string) {
  return {
    error: {
      code,
      display_text: "Контролируемое тестовое состояние.",
      retryable: code === "RESOURCE_NOT_READY",
      user_action: "Следуйте инструкции на экране.",
    },
  };
}

function queryScenario(url: URL): ScenarioId | null {
  const value = url.searchParams.get("scenario_id");
  return value !== null && SCENARIO_IDS.has(value as ScenarioId)
    ? value as ScenarioId
    : null;
}

function queryPositiveInteger(url: URL, name: string, fallback: number): number {
  const raw = url.searchParams.get(name);
  if (raw === null) return fallback;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : Number.NaN;
}

function splitRows(rows: readonly MediaPlanRow[], parts = 5): MediaPlanRow[] {
  return rows
    .flatMap((row) => Array.from({ length: parts }, (_, index) => ({
      ...row,
      segment: `${String(index + 1).padStart(2, "0")} · ${row.segment}`,
      source_budget_rub: row.source_budget_rub / parts,
      selected_budget_rub: row.selected_budget_rub / parts,
      delta_rub: row.delta_rub / parts,
      source_budget_share: row.source_budget_share / parts,
      selected_budget_share: row.selected_budget_share / parts,
    })))
    .sort((left, right) => {
      const leftKey = `${left.segment}\u0000${left.geo}\u0000${left.channel}`;
      const rightKey = `${right.segment}\u0000${right.geo}\u0000${right.channel}`;
      return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
    });
}

function largeMediaPlan(
  result: JobResultViewV1,
  scenarioId: ScenarioId,
  page: number,
  pageSize: number,
  channel: string | null,
  geo: string | null,
): ScenarioMediaPlanV1 {
  const plan = structuredClone(createScenarioMediaPlanFixture({
    resultView: result,
    scenarioId,
    page: 1,
    pageSize: 100,
  }));
  const allRows = splitRows(plan.rows);
  const filteredRows = allRows.filter((row) =>
    (channel === null || row.channel === channel) &&
    (geo === null || row.geo === geo));
  const start = (page - 1) * pageSize;
  plan.filters = { channel, geo, date: null };
  plan.pagination = {
    page,
    page_size: pageSize,
    total_rows: filteredRows.length,
    total_pages: filteredRows.length === 0 ? 0 : Math.ceil(filteredRows.length / pageSize),
  };
  plan.filtered_totals = {
    source_budget_rub: filteredRows.reduce((sum, row) => sum + row.source_budget_rub, 0),
    selected_budget_rub: filteredRows.reduce((sum, row) => sum + row.selected_budget_rub, 0),
    delta_rub: filteredRows.reduce((sum, row) => sum + row.delta_rub, 0),
  };
  plan.rows = filteredRows.slice(start, start + pageSize);
  return plan;
}

function emptyMediaPlan(
  result: JobResultViewV1,
  scenarioId: ScenarioId,
  page: number,
  pageSize: number,
  channel: string | null,
  geo: string | null,
): ScenarioMediaPlanV1 {
  const plan = structuredClone(createScenarioMediaPlanFixture({
    resultView: result,
    scenarioId,
    channel: "Синтетический канал без строк",
    page,
    pageSize,
  }));
  plan.filters = { channel, geo, date: null };
  return plan;
}

function buildMediaPlan(
  result: JobResultViewV1,
  url: URL,
  mode: MediaMode,
): ScenarioMediaPlanV1 | null {
  const scenarioId = queryScenario(url);
  const page = queryPositiveInteger(url, "page", 1);
  const pageSize = queryPositiveInteger(url, "page_size", 100);
  const channel = url.searchParams.get("channel");
  const geo = url.searchParams.get("geo");
  if (scenarioId === null || !Number.isFinite(page) || !Number.isFinite(pageSize) || pageSize > 500) {
    return null;
  }
  if (mode === "large") return largeMediaPlan(result, scenarioId, page, pageSize, channel, geo);
  if (mode === "empty") return emptyMediaPlan(result, scenarioId, page, pageSize, channel, geo);
  return createScenarioMediaPlanFixture({
    resultView: result,
    scenarioId,
    page,
    pageSize,
    channel,
    geo,
  });
}

async function installProductRoutes(
  page: Page,
  result: JobResultViewV1,
  options: ProductRouteOptions = {},
): Promise<ProductRouteGuard> {
  const guard: ProductRouteGuard = {
    resultViewCalls: 0,
    mediaPlanCalls: 0,
    artifactCalls: 0,
    forbiddenCalls: [],
  };
  routeGuards.set(page, guard);

  // Registered first: exact product routes below take precedence. Everything
  // else under /api/v1 is a hard test failure, including legacy result,
  // overview, errors and progress endpoints.
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    guard.forbiddenCalls.push(`${request.method()} ${new URL(request.url()).pathname}`);
    await route.fulfill({ status: 599, body: "blocked unapproved endpoint" });
  });

  await page.route("**/api/v1/jobs/*/result-view", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== "GET" || url.pathname !== `/api/v1/jobs/${result.job_id}/result-view` || url.search) {
      guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed result-view request" });
      return;
    }
    guard.resultViewCalls += 1;
    if (options.resultDelayMs) await new Promise((resolve) => setTimeout(resolve, options.resultDelayMs));
    const status = options.resultStatus ?? 200;
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(status === 200
        ? (options.resultPayload ?? result)
        : errorPayload(options.resultErrorCode ?? (status === 404 ? "JOB_NOT_FOUND" : status === 409 ? "RESULT_VIEW_INCONSISTENT" : "RESULT_VIEW_UNAVAILABLE"))),
    });
  });

  await page.route("**/api/v1/jobs/*/media-plan*", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== "GET" || url.pathname !== `/api/v1/jobs/${result.job_id}/media-plan`) {
      guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed media-plan request" });
      return;
    }
    guard.mediaPlanCalls += 1;
    const status = options.mediaStatus ?? 200;
    const plan = status === 200 ? buildMediaPlan(result, url, options.mediaMode ?? "normal") : null;
    await route.fulfill({
      status: plan === null && status === 200 ? 422 : status,
      contentType: "application/json",
      body: JSON.stringify(plan ?? errorPayload("MEDIA_PLAN_QUERY_UNSUPPORTED")),
    });
  });

  const artifactHandler = async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const expectedPath = result.report.artifact?.download_path;
    if (request.method() !== "GET" || expectedPath === undefined || url.pathname !== expectedPath || url.search) {
      guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed artifact request" });
      return;
    }
    guard.artifactCalls += 1;
    await route.fulfill({
      status: options.artifactStatus ?? 200,
      contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      headers: {
        "Content-Disposition": `attachment; filename="${result.report.artifact?.display_name ?? "result.xlsx"}"`,
      },
      body: "synthetic xlsx review artifact",
    });
  };
  // Register at both levels: Chrome's native download stream is context-owned,
  // while the explicit endpoint integrity probe below is a page fetch.
  await page.route("**/api/v1/artifacts/*/download", artifactHandler);
  await page.context().route("**/api/v1/artifacts/*/download", artifactHandler);

  return guard;
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

async function openResult(
  page: Page,
  result: JobResultViewV1,
  search = "?tab=overview",
) {
  await page.goto(`/calculations/${result.job_id}/result${search}`);
  await expect(page.getByRole("heading", { name: result.campaign.campaign_name })).toBeVisible();
  if (result.record_origin === "sanitized_fixture") {
    await expect(page.getByText("Демонстрационные данные", { exact: true }).first()).toBeVisible();
  }
  await page.evaluate(async () => { await document.fonts.ready; });
}

async function expectNoDocumentOverflow(page: Page) {
  const diagnostic = await page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const offenders = [...document.querySelectorAll<HTMLElement>("body *")]
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          selector: `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}${typeof element.className === "string" && element.className ? `.${element.className.split(/\s+/).join(".")}` : ""}`,
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
        };
      })
      .filter((item) => item.right > viewportWidth + 1 && item.width > 0)
      .sort((left, right) => right.right - left.right)
      .slice(0, 12);
    return {
      overflow: document.documentElement.scrollWidth - viewportWidth,
      viewportWidth,
      documentWidth: document.documentElement.scrollWidth,
      offenders,
    };
  });
  expect(diagnostic.overflow, JSON.stringify(diagnostic, null, 2)).toBeLessThanOrEqual(0);
}

async function expectNoRawTerms(page: Page) {
  const visibleText = (await page.locator("body").innerText()).toLowerCase();
  for (const term of RAW_TERMS) expect(visibleText).not.toContain(term.toLowerCase());
}

async function expectNoForbiddenUserCopy(page: Page) {
  const visibleText = (await page.locator("body").innerText()).toLowerCase();
  for (const phrase of FORBIDDEN_USER_COPY) {
    expect(visibleText).not.toContain(phrase.toLowerCase());
  }
}

async function expectAllowedCallsOnly(page: Page) {
  expect(routeGuards.get(page)?.forbiddenCalls ?? []).toEqual([]);
}

type ScreenshotCase = {
  name: string;
  result: () => JobResultViewV1;
  search: string;
  expected: string;
  focusExpected?: boolean;
};

const screenshotCases: readonly ScreenshotCase[] = [
  {
    name: "01-overview-recommended",
    result: createRecommendedJobResultFixture,
    search: "?tab=overview",
    expected: "Рекомендуемое распределение бюджета",
  },
  {
    name: "02-overview-no-safe",
    result: createNoSafeJobResultFixture,
    search: "?tab=overview",
    expected: "Безопасная автоматическая рекомендация не сформирована",
  },
  {
    name: "03-scenarios",
    result: createRecommendedJobResultFixture,
    search: "?tab=scenarios",
    expected: "Сравнение рассчитанных вариантов",
  },
  {
    name: "04-best-raw",
    result: createBestRawJobResultFixture,
    search: "?tab=scenarios",
    expected: "Математически сильный, но не рекомендованный вариант",
    focusExpected: true,
  },
  {
    name: "05-media-plan",
    result: createRecommendedJobResultFixture,
    search: "?tab=media-plan&scenario=S06",
    expected: "Изменение бюджета по каналам и географиям",
    focusExpected: true,
  },
  {
    name: "06-media-plan-partial",
    result: createPartialCoverageJobResultFixture,
    search: "?tab=media-plan&scenario=S06",
    expected: "Не распределено",
    focusExpected: true,
  },
  {
    name: "07-report",
    result: createReportReadyJobResultFixture,
    search: "?tab=report",
    expected: "mmm_campaign_result.xlsx",
    focusExpected: true,
  },
  {
    name: "08-unavailable",
    result: createUnavailableJobResultFixture,
    search: "?tab=overview",
    expected: "Рекомендация недоступна",
  },
] as const;

test.describe("job result review screenshots", () => {
  for (const screenshotCase of screenshotCases) {
    for (const theme of ["dark", "light"] as const) {
      test(`${screenshotCase.name}-${theme}`, async ({ page }) => {
        const result = screenshotCase.result();
        await page.setViewportSize({ width: 1_440, height: 900 });
        await setTheme(page, theme);
        await installProductRoutes(page, result);
        await openResult(page, result, screenshotCase.search);
        const expected = page.getByText(screenshotCase.expected, { exact: false }).first();
        await expect(expected).toBeVisible();
        if (screenshotCase.focusExpected) {
          await expected.evaluate((element) => {
            (element.closest("section") ?? element).scrollIntoView({ block: "start" });
          });
          await page.evaluate(() => window.scrollBy(0, -152));
          await expect(expected).toBeInViewport();
        }
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expectNoDocumentOverflow(page);
        await expectNoRawTerms(page);
        await expectNoForbiddenUserCopy(page);
        await expectAllowedCallsOnly(page);
        await page.screenshot({
          path: `${REVIEW_DIRECTORY}${screenshotCase.name}-${theme}.png`,
          fullPage: false,
          animations: "disabled",
        });
      });
    }
  }
});

test.describe("job result tabs and URL state", () => {
  test("renders four tabs and restores each section in the URL", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result);
    await openResult(page, result);

    for (const [tab, query, heading] of [
      ["Обзор", "overview", "Рекомендуемое распределение бюджета"],
      ["Сценарии и надежность", "scenarios", "Сравнение рассчитанных вариантов"],
      ["Медиаплан", "media-plan", "Медиаплан было → рекомендуется"],
      ["Отчет", "report", "Отчет готов"],
    ] as const) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
      await expect(page.getByRole("tab", { name: tab, exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByText(heading, { exact: false }).first()).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`tab=${query}`));
    }
    await expectNoRawTerms(page);
  });

  test("scenario selector is view-only and does not mutate recommendation", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result);
    await openResult(page, result, "?tab=media-plan&scenario=S05");
    await expect(page.getByRole("radio", { name: /S5.*Устойчивый ориентир/ })).toBeChecked();
    await expect(page.getByText("Только просмотр", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Исходный план → просматриваемый сценарий" })).toBeVisible();
    await expectNoForbiddenUserCopy(page);

    const sourceRadio = page.getByRole("radio", { name: /S1.*Как загружено/ });
    await sourceRadio.focus();
    await sourceRadio.press("Space");
    await expect(page).toHaveURL(/tab=media-plan&scenario=S01/);
    await expect(page.getByText("Только просмотр", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Обзор", exact: true }).click();
    await expect(page.getByText("S6 · Адаптивное распределение", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Рекомендован системой", { exact: true })).toBeVisible();
  });

  test("back and forward restore media scenario without changing it", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result);
    await openResult(page, result, "?tab=media-plan&scenario=S05");
    await expect(page.getByRole("radio", { name: /S5.*Устойчивый ориентир/ })).toBeChecked();
    await page.getByRole("tab", { name: "Сценарии и надежность", exact: true }).click();
    await expect(page).toHaveURL(/tab=scenarios/);
    await page.goBack();
    await expect(page).toHaveURL(/tab=media-plan&scenario=S05/);
    await expect(page.getByRole("radio", { name: /S5.*Устойчивый ориентир/ })).toBeChecked();
    await page.goForward();
    await expect(page).toHaveURL(/tab=scenarios/);
  });

  test("tabs support arrows, Home and End", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result);
    await openResult(page, result);
    const overview = page.getByRole("tab", { name: "Обзор", exact: true });
    await overview.focus();
    await overview.press("ArrowRight");
    const scenarios = page.getByRole("tab", { name: "Сценарии и надежность", exact: true });
    await expect(scenarios).toBeFocused();
    await expect(scenarios).toHaveAttribute("aria-selected", "true");
    await scenarios.press("End");
    const report = page.getByRole("tab", { name: "Отчет", exact: true });
    await expect(report).toBeFocused();
    await report.press("Home");
    await expect(overview).toBeFocused();
    await expect(overview).toHaveAttribute("aria-selected", "true");
  });
});

test.describe("job result media plan", () => {
  test("switches scenarios and applies channel and geo filters", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    const guard = await installProductRoutes(page, result);
    await openResult(page, result, "?tab=media-plan&scenario=S06");
    await expect(page.locator("tbody tr")).toHaveCount(4);
    await expect(page.getByText("Запрошенный бюджет", { exact: true })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Изменение, %" })).toBeVisible();
    await expect(page.getByText("Строка прошла опубликованные проверки качества.").first()).toBeVisible();

    await page.getByRole("combobox", { name: "Канал", exact: true }).selectOption("Онлайн-видео");
    await expect(page.locator("tbody tr")).toHaveCount(2);
    await page.getByRole("combobox", { name: "География", exact: true }).selectOption("Москва");
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await page.getByRole("button", { name: "Сбросить", exact: true }).click();
    await expect(page.locator("tbody tr")).toHaveCount(4);

    const benchmarkRadio = page.getByRole("radio", { name: /S5.*Устойчивый ориентир/ });
    await benchmarkRadio.focus();
    await benchmarkRadio.press("Space");
    await expect(page).toHaveURL(/scenario=S05/);
    await expect(page.getByText("Только просмотр", { exact: true })).toBeVisible();
    expect(guard.mediaPlanCalls).toBeGreaterThanOrEqual(5);
  });

  test("paginates a long synthetic media plan", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result, { mediaMode: "large" });
    await openResult(page, result, "?tab=media-plan&scenario=S06");
    await page.getByLabel("Строк на странице").selectOption("10");
    await expect(page.getByText("Страница 1 из 2", { exact: true })).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(10);
    await page.getByRole("button", { name: "Далее", exact: true }).click();
    await expect(page.getByText("Страница 2 из 2", { exact: true })).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(10);
  });

  test("renders a controlled empty filtered result", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result, { mediaMode: "empty" });
    await openResult(page, result, "?tab=media-plan&scenario=S06");
    await expect(page.getByText("По выбранным фильтрам строк нет", { exact: true })).toBeVisible();
    await expect(page.getByText("Это корректный пустой результат", { exact: false })).toBeVisible();
    const globalTotals = page.getByRole("region", { name: "Итоги медиаплана" });
    await expect(globalTotals.getByText("Исходный бюджет").locator("..")).toContainText("12 млн ₽");
  });

  test("renders media-plan 422 inside its tab", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result, { mediaStatus: 422 });
    await openResult(page, result, "?tab=media-plan&scenario=S06");
    await expect(page.getByRole("heading", { name: "Такие параметры пока не поддерживаются" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Сбросить фильтры" })).toBeVisible();
    await expect(page.getByRole("heading", { name: result.campaign.campaign_name })).toBeVisible();
  });
});

test.describe("job result report and controlled failures", () => {
  test("downloads only the canonical report artifact", async ({ page }) => {
    const result = createReportReadyJobResultFixture();
    const guard = await installProductRoutes(page, result);
    await openResult(page, result, "?tab=report");
    const downloadLinks = page.getByRole("link", { name: "Скачать отчет", exact: true });
    await expect(downloadLinks).toHaveCount(2);
    for (const link of await downloadLinks.all()) {
      const href = await link.getAttribute("href");
      expect(new URL(href ?? "", page.url()).pathname).toBe(result.report.artifact?.download_path);
    }
    const downloadPromise = page.waitForEvent("download");
    await page
      .getByRole("region", { name: result.report.artifact?.display_name })
      .getByRole("link", { name: "Скачать отчет", exact: true })
      .click();
    const download = await downloadPromise;
    await expect(page.getByRole("heading", { name: result.report.artifact?.display_name })).toBeVisible();
    expect(await download.failure()).toBeNull();
    expect(new URL(download.url()).pathname).toBe(result.report.artifact?.download_path);
    const mediaType = await page.evaluate(async (downloadPath) => {
      const response = await fetch(downloadPath);
      return response.headers.get("content-type");
    }, result.report.artifact?.download_path ?? "");
    expect(mediaType).toContain("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    // Depending on the Chrome channel, the native download is observed by the
    // context route, the page route, or both. Every observed call is already
    // guarded above against any non-canonical path or query.
    expect(guard.artifactCalls).toBeGreaterThanOrEqual(1);
  });

  for (const [status, heading] of [
    [404, "Результат не найден"],
    [409, "Данные временно не согласованы"],
    [503, "Результат временно недоступен"],
  ] as const) {
    test(`renders result-view HTTP ${status}`, async ({ page }) => {
      const result = createRecommendedJobResultFixture();
      await installProductRoutes(page, result, { resultStatus: status });
      await page.goto(`/calculations/${result.job_id}/result`);
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
      await expect(page.locator("body")).not.toContainText("RESULT_VIEW_");
    });
  }

  test("distinguishes a not-ready result from a missing job", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result, {
      resultStatus: 404,
      resultErrorCode: "RESOURCE_NOT_READY",
    });
    await page.goto(`/calculations/${result.job_id}/result`);
    await expect(page.getByRole("heading", { name: "Результат еще не готов" })).toBeVisible();
    await expect(page.getByText("Откройте ход расчета", { exact: false })).toBeVisible();
    await expect(page.getByRole("link", { name: "Открыть ход расчета" })).toBeVisible();
  });

  test("rejects an unsupported result contract", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result, {
      resultPayload: { ...result, schema_version: "2.0.0" },
    });
    await page.goto(`/calculations/${result.job_id}/result`);
    await expect(page.getByRole("heading", { name: "Формат результата не поддерживается" })).toBeVisible();
  });

  test("shows a matching skeleton while result-view is loading", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await installProductRoutes(page, result, { resultDelayMs: 600 });
    const navigation = page.goto(`/calculations/${result.job_id}/result`);
    await expect(page.getByText("Получаем результат расчета…", { exact: true })).toBeVisible();
    await navigation;
    await expect(page.getByRole("heading", { name: result.campaign.campaign_name })).toBeVisible();
  });
});

test.describe("job result responsive and visual QA", () => {
  test("mobile long campaign and warning have no document overflow", async ({ page }) => {
    const result = createPartialCoverageJobResultFixture();
    result.campaign.campaign_name = "Очень длинное название кампании для Москвы, Санкт-Петербурга и нескольких регионов присутствия";
    result.campaign.segments = [
      "Очень длинный сегмент покупателей с повышенной частотой покупок",
      "Покупатели новых магазинов и форматов с дополнительными условиями",
    ];
    result.warnings[0].display_text = "Очень подробное пользовательское объяснение ограничения покрытия с длинным текстом, который должен переноситься внутри карточки и не выходить за границы мобильного экрана.";
    await page.setViewportSize({ width: 375, height: 812 });
    await installProductRoutes(page, result);
    await openResult(page, result);
    await expectNoDocumentOverflow(page);
  });

  test("mobile media table scroll remains inside its own region", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await page.setViewportSize({ width: 375, height: 812 });
    await installProductRoutes(page, result, { mediaMode: "large" });
    await openResult(page, result, "?tab=media-plan&scenario=S06");
    const tableRegion = page.getByRole("region", { name: "Таблица медиаплана, прокручивается по горизонтали" });
    await expect(tableRegion).toBeVisible();
    const hasInnerOverflow = await tableRegion.evaluate((element) => element.scrollWidth > element.clientWidth);
    expect(hasInnerOverflow).toBe(true);
    await expectNoDocumentOverflow(page);
  });

  test("landscape layout has no document overflow", async ({ page }) => {
    const result = createBestRawJobResultFixture();
    await page.setViewportSize({ width: 812, height: 375 });
    await installProductRoutes(page, result);
    await openResult(page, result, "?tab=scenarios");
    await expectNoDocumentOverflow(page);
  });

  test("reduced motion leaves no active looping animations", async ({ page }) => {
    const result = createRecommendedJobResultFixture();
    await page.emulateMedia({ reducedMotion: "reduce" });
    await installProductRoutes(page, result);
    await openResult(page, result);
    const animated = await page.locator("body *").evaluateAll((elements) => elements.filter((element) => {
      const style = getComputedStyle(element);
      return style.animationName !== "none" && style.animationDuration !== "0s";
    }).length);
    expect(animated).toBe(0);
  });

  test("all product tabs avoid raw names and body overlap", async ({ page }) => {
    const result = createBestRawJobResultFixture();
    await installProductRoutes(page, result, { mediaMode: "large" });
    await openResult(page, result);
    for (const tab of ["Обзор", "Сценарии и надежность", "Медиаплан", "Отчет"] as const) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
      await expectNoRawTerms(page);
      await expectNoForbiddenUserCopy(page);
      await expectNoDocumentOverflow(page);
    }
  });
});
