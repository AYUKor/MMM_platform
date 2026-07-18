import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { JobResultViewV2 } from "../src/shared/api/generated/job-result-view-v2";
import type { ScenarioId } from "../src/shared/api/generated/scenario-media-plan-v2";
import {
  buildJobResultViewV2,
  buildScenarioMediaPlanV2,
  CONTROL_REQUESTED_BUDGET,
  TEST_JOB_ID,
} from "../src/test/businessSemanticsV2Fixtures";
import { createAuthenticatedSessionFixture } from "../src/test/authAdminFixtures";
import { installAuthenticatedAdminSession } from "./support/auth";
import { measureContentContrast, type ContrastTarget } from "./support/contrast";

const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/phase-e1b-business-semantics-v1/", import.meta.url),
);

const FORBIDDEN_COPY = [
  "Дополнительные заказы",
  "Заказы на 100 000 ₽",
  "Механизм среднего чека",
  "Часть дополнительного оборота",
  "Рекомендован системой",
  "Digital_Performance",
  "OOH_Total",
  "orders_per_user",
  "avg_basket",
  "S5.1",
  "S5.2",
  "... ещё",
] as const;

const RESULT_CONTRAST_TARGETS = [
  { name: "campaign facts", selector: '[class*="campaignMeta"] dt' },
  { name: "metric range labels", selector: '[class*="metricRange"]' },
  { name: "metric guidance", selector: '[class*="metricNote"], [class*="metricHelp"]' },
  { name: "risk facts", selector: '[class*="riskRow"] dt, [class*="riskRow"] > div:first-child span' },
  { name: "scenario budget labels", selector: '[class*="scenarioBudget"] dt' },
  { name: "scenario metric labels", selector: '[class*="scenarioMetrics"] dt, [class*="scenarioMetrics"] small' },
  { name: "scenario risk labels", selector: '[class*="compactRisk"] dt' },
  { name: "scenario footnotes", selector: '[class*="scenarioFooter"]' },
] as const satisfies readonly ContrastTarget[];

interface RouteGuard {
  resultCalls: string[];
  reportCalls: string[];
  mediaCalls: string[];
  mediaSelections: Array<{ scenarioId: ScenarioId; isSelected: boolean }>;
  artifactCalls: string[];
  forbiddenCalls: string[];
}

const routeGuards = new WeakMap<Page, RouteGuard>();

test.beforeEach(async ({ page }) => {
  await installAuthenticatedAdminSession(page);
});

test.afterEach(async ({ page }) => {
  const guard = routeGuards.get(page);
  if (guard) expect(guard.forbiddenCalls, "legacy or malformed result requests").toEqual([]);
});

function errorPayload(code: string, displayText = "Контролируемое тестовое состояние.") {
  return {
    error: {
      code,
      display_text: displayText,
      retryable: true,
      user_action: "Повторите запрос позже.",
    },
  };
}

function buildReportArtifactsPayload(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  const result = buildJobResultViewV2();
  return {
    contract_name: "job_result_view_v1",
    schema_version: "1.0.0",
    job_id: TEST_JOB_ID,
    result_id: result.result_id,
    campaign: {
      campaign_name: "КОНФЛИКТУЮЩАЯ КАМПАНИЯ ИЗ V1",
      total_budget_rub: 1,
    },
    scenarios: [{ scenario_id: "S01", metrics: { incremental_turnover_rub: { p50: 999_999_999_999 } } }],
    report: {
      status: "ready",
      display_text: "Excel-отчет готов.",
      generated_at_utc: "2026-07-18T12:00:00Z",
      artifact: {
        artifact_id: "artifact_1234567890abcdef",
        display_name: "mmm_campaign_result.xlsx",
        media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes: 65_536,
        sha256: "a".repeat(64),
        download_path: "/api/v1/artifacts/artifact_1234567890abcdef/download",
      },
      sheets: [
        { sheet_name: "Итоги", title: "Итоги", description: "Основные результаты расчета." },
        { sheet_name: "Медиаплан", title: "Медиаплан", description: null },
      ],
      working_media_plan: {
        status: "unavailable",
        display_text: "Отдельный рабочий медиаплан пока не опубликован.",
        artifact: null,
      },
      ...overrides,
    },
  };
}

async function installViewerSession(page: Page): Promise<void> {
  await page.unroute("**/api/v1/auth/session");
  await page.route("**/api/v1/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(createAuthenticatedSessionFixture("viewer")),
    });
  });
}

async function installResultRoutes(
  page: Page,
  options: {
    resultStatus?: number;
    resultPayload?: unknown;
    resultDelayMs?: number;
    mediaStatus?: number;
    reportPayload?: unknown;
    artifactStatus?: number;
  } = {},
): Promise<RouteGuard> {
  const result = buildJobResultViewV2();
  const reportPayload = options.reportPayload ?? buildReportArtifactsPayload();
  const guard: RouteGuard = {
    resultCalls: [],
    reportCalls: [],
    mediaCalls: [],
    mediaSelections: [],
    artifactCalls: [],
    forbiddenCalls: [],
  };
  routeGuards.set(page, guard);

  // Register the catch-all first: the exact handlers registered afterwards
  // take precedence in Playwright's LIFO route order.
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/v1/auth/session" && !url.search) {
      await route.fallback();
      return;
    }
    guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
    await route.fulfill({ status: 599, body: "blocked unapproved endpoint" });
  });

  await page.route("**/api/v1/jobs/*/result-view-v2", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const expected = `/api/v1/jobs/${TEST_JOB_ID}/result-view-v2`;
    if (request.method() !== "GET" || url.pathname !== expected || url.search) {
      guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed result-view-v2 request" });
      return;
    }
    guard.resultCalls.push(url.toString());
    if (options.resultDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, options.resultDelayMs));
    }
    const status = options.resultStatus ?? 200;
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(status === 200
        ? (options.resultPayload ?? result)
        : errorPayload(status === 404 ? "RESOURCE_NOT_READY" : "RESULT_VIEW_UNAVAILABLE")),
    });
  });

  await page.route("**/api/v1/jobs/*/result-view", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const expected = `/api/v1/jobs/${TEST_JOB_ID}/result-view`;
    if (request.method() !== "GET" || url.pathname !== expected || url.search) {
      guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed report artifact request" });
      return;
    }
    guard.reportCalls.push(url.toString());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(reportPayload),
    });
  });

  const artifactHandler = async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (
      request.method() !== "GET"
      || !/^\/api\/v1\/artifacts\/artifact_[0-9a-f]{12,64}\/download$/.test(url.pathname)
      || url.search
    ) {
      guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed artifact download" });
      return;
    }
    guard.artifactCalls.push(url.pathname);
    await route.fulfill({
      status: options.artifactStatus ?? 200,
      contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      headers: { "Content-Disposition": "attachment; filename=report.xlsx" },
      body: "PK synthetic xlsx review artifact",
    });
  };
  await page.route("**/api/v1/artifacts/*/download", artifactHandler);
  await page.context().route("**/api/v1/artifacts/*/download", artifactHandler);

  await page.route("**/api/v1/jobs/*/media-plan-v2*", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const expected = `/api/v1/jobs/${TEST_JOB_ID}/media-plan-v2`;
    const scenarioId = url.searchParams.get("scenario_id") as ScenarioId | null;
    const pageNumber = Number(url.searchParams.get("page"));
    const pageSize = Number(url.searchParams.get("page_size"));
    if (
      request.method() !== "GET"
      || url.pathname !== expected
      || !scenarioId
      || !["S01", "S02", "S03", "S04", "S05", "S06"].includes(scenarioId)
      || !Number.isInteger(pageNumber)
      || pageNumber < 1
      || !Number.isInteger(pageSize)
      || pageSize < 1
    ) {
      guard.forbiddenCalls.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({ status: 599, body: "blocked malformed media-plan-v2 request" });
      return;
    }
    guard.mediaCalls.push(url.toString());
    const status = options.mediaStatus ?? 200;
    const plan = status === 200
      ? buildScenarioMediaPlanV2(scenarioId, {
          page: pageNumber,
          pageSize,
          channel: url.searchParams.get("channel"),
          geo: url.searchParams.get("geo"),
        })
      : null;
    if (plan) {
      plan.scenario.is_selected = scenarioId === result.recommendation.scenario_id;
      guard.mediaSelections.push({ scenarioId, isSelected: plan.scenario.is_selected });
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(plan
        ? plan
        : errorPayload("MEDIA_PLAN_QUERY_INVALID")),
    });
  });

  return guard;
}

async function openResult(page: Page, search = "?tab=overview") {
  await page.goto(`/calculations/${TEST_JOB_ID}/result${search}`);
  await expect(page.getByRole("heading", { name: "Демонстрационная кампания" })).toBeVisible();
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

function buildFullConservativeResult(): JobResultViewV2 {
  const result = structuredClone(buildJobResultViewV2());
  const scenario = result.scenarios.find((item) => item.scenario_id === "S05");
  if (!scenario) throw new Error("S05 fixture is missing");
  scenario.scenario_variant = "full_conservative";
  scenario.budget.allocated_budget_rub = CONTROL_REQUESTED_BUDGET;
  scenario.budget.unallocated_budget_rub = 0;
  scenario.budget.allocation_share = 1;
  scenario.roas.allocated_budget = structuredClone(scenario.roas.requested_budget);
  scenario.roas.primary_denominator_kind = "requested_budget";
  scenario.roas.primary_denominator_budget_rub = CONTROL_REQUESTED_BUDGET;
  scenario.risk_budget = {
    within_support_budget_rub: CONTROL_REQUESTED_BUDGET,
    within_support_share: 1,
    controlled_extrapolation_budget_rub: 0,
    controlled_extrapolation_share: 0,
    high_risk_budget_rub: 0,
    high_risk_share: 0,
    within_support_cells_n: 45,
    controlled_extrapolation_cells_n: 0,
    high_risk_cells_n: 0,
  };
  scenario.limiting_constraints = [];
  scenario.reliability.display_text = "Весь бюджет находится внутри опубликованного надежного диапазона.";
  return result;
}

function buildFeasibleS6Result(): JobResultViewV2 {
  const result = structuredClone(buildJobResultViewV2());
  const source = result.scenarios.find((item) => item.scenario_id === "S04");
  const targetIndex = result.scenarios.findIndex((item) => item.scenario_id === "S06");
  if (!source || targetIndex < 0) throw new Error("S04 or S06 fixture is missing");
  result.scenarios[targetIndex] = {
    ...structuredClone(source),
    scenario_id: "S06",
    name: "План максимального эффекта",
    description: "Полный оптимизированный план сформирован в опубликованных ограничениях.",
    scenario_kind: "optimized_plan",
    scenario_variant: "feasible",
    status: "completed",
    is_recommended: false,
    decision_status: "unavailable",
    review_status: "manual_review_required",
    reliability: {
      ...structuredClone(source.reliability),
      status: "within_support",
      display_text: "Полный план находится внутри опубликованного надежного диапазона.",
      safe_rank: 6,
      raw_rank: 6,
    },
    limiting_constraints: [],
  };
  return result;
}

test.describe("Phase E.1B result semantics", () => {
  test("uses only result-view-v2 and renders S1 as the manual point of reference", async ({ page }) => {
    const guard = await installResultRoutes(page);
    await openResult(page);

    await expect(page.getByText("Исходный план", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Точка отсчета", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Требуется ручная проверка", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Сохранить исходный план", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Оборот и ROAS" })).toBeVisible();
    await expect(page.getByText("Дополнительный оборот", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Где находится распределенный бюджет" }))
      .toBeVisible();
    await expect(page.getByText("Внутри надежного диапазона", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Контролируемое расширение", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Высокий риск", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Карта географий" })).toBeVisible();
    expect(guard.resultCalls.length).toBeGreaterThan(0);
    expect(new Set(guard.resultCalls).size).toBe(1);
    expect(guard.mediaCalls).toHaveLength(0);
    await expectNoForbiddenCopy(page);
  });

  test("renders S5 safe_partial with both ROAS meanings and budget reconciliation", async ({ page }) => {
    await installResultRoutes(page);
    await openResult(page, "?tab=scenarios");

    const s5 = page.locator("#scenario-S05");
    await expect(s5).toBeVisible();
    await expect(s5.getByRole("heading", { name: "Безопасно распределяемая часть" })).toBeVisible();
    await expect(s5.getByText("Безопасно распределяемая часть", { exact: true })).toBeVisible();
    await expect(s5.getByText("ROAS распределенной части", { exact: true })).toBeVisible();
    await expect(s5.getByText("Отдача относительно всего запрошенного бюджета", { exact: true }))
      .toBeVisible();
    await expect(s5).toContainText("173,9 млн ₽");
    await expect(s5).toContainText("93,9 млн ₽");
    await expect(s5).toContainText("64,9 %");
    await expect(s5).toContainText("1,98");
    await expect(s5).toContainText("1,29");
    await expectNoForbiddenCopy(page);
  });

  test("renders S5 full_conservative as a full cautious plan without partial-only copy", async ({ page }) => {
    await installResultRoutes(page, { resultPayload: buildFullConservativeResult() });
    await openResult(page, "?tab=scenarios");

    const s5 = page.locator("#scenario-S05");
    await expect(s5.getByRole("heading", { name: "Полный осторожный план" })).toBeVisible();
    await expect(s5.getByText("Полный осторожный план", { exact: true })).toBeVisible();
    await expect(s5.getByText("Весь бюджет распределен", { exact: true })).toBeVisible();
    await expect(s5.getByText("ROAS", { exact: true })).toBeVisible();
    await expect(s5.getByText("ROAS распределенной части", { exact: true })).toHaveCount(0);
    await expect(s5.getByText("Отдача относительно всего запрошенного бюджета", { exact: true }))
      .toHaveCount(0);
    await expect(s5).toContainText("267,8 млн ₽");
    await expect(s5).toContainText("100 %");
    await expectNoForbiddenCopy(page);
  });

  test("renders S6 infeasible as controlled unavailable without fake KPI", async ({ page }) => {
    const guard = await installResultRoutes(page);
    await openResult(page, "?tab=scenarios");

    const s6 = page.locator("#scenario-S06");
    await expect(s6.getByRole("heading", { name: "План максимального эффекта", exact: true }))
      .toBeVisible();
    await expect(s6.getByText("Недоступно при текущих ограничениях", { exact: true })).toBeVisible();
    await expect(s6.getByRole("heading", { name: "Полный план максимального эффекта недоступен" }))
      .toBeVisible();
    await expect(s6.getByText("Дополнительный оборот", { exact: false })).toHaveCount(0);
    await expect(s6.getByText(/ROAS/)).toHaveCount(0);
    await expect(s6.getByText("Распределено", { exact: true })).toHaveCount(0);
    expect(guard.mediaCalls.some((call) => call.includes("scenario_id=S06"))).toBe(false);
    await expectNoForbiddenCopy(page);
  });

  test("renders an explicitly feasible S6 with only backend-published KPI", async ({ page }) => {
    await installResultRoutes(page, { resultPayload: buildFeasibleS6Result() });
    await openResult(page, "?tab=scenarios");

    const s6 = page.locator("#scenario-S06");
    await expect(s6.getByRole("heading", { name: "План максимального эффекта", exact: true }))
      .toBeVisible();
    await expect(s6.getByText("Рассчитан", { exact: true })).toBeVisible();
    await expect(s6.getByText("Дополнительный оборот · P50", { exact: true })).toBeVisible();
    await expect(s6.getByText("ROAS", { exact: true })).toBeVisible();
    await expect(s6.getByText("Недоступно при текущих ограничениях", { exact: true })).toHaveCount(0);
    await expectNoForbiddenCopy(page);
  });

  test("media selector changes only the viewed plan and excludes infeasible S6", async ({ page }) => {
    const guard = await installResultRoutes(page);
    await openResult(page, "?tab=media-plan&scenario=S01");

    const scenario = page.getByLabel("Сценарий");
    await expect(scenario).toHaveValue("S01");
    await expect(scenario.locator('option[value="S06"]')).toHaveCount(0);
    await scenario.selectOption("S05");
    await expect(page).toHaveURL(/tab=media-plan&scenario=S05/);
    await expect(page.getByRole("heading", { name: "План согласован с результатом" })).toBeVisible();
    await expect(page.getByText("Частичное распределение", { exact: true })).toBeVisible();
    await expect(page.getByText("173,9 млн ₽", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("93,9 млн ₽", { exact: true }).first()).toBeVisible();
    const channelBudget = page.getByRole("heading", { name: "Бюджет по каналам" })
      .locator("xpath=ancestor::section[1]");
    await expect(channelBudget.getByText("Цифровая реклама", { exact: true })).toBeVisible();
    await expect(channelBudget.getByText("Наружная реклама", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Карта географий" })).toBeVisible();
    expect(guard.mediaCalls.some((call) => call.includes("scenario_id=S05"))).toBe(true);
    expect(guard.mediaSelections.some((item) => item.scenarioId === "S05" && !item.isSelected))
      .toBe(true);
    await expect(page.getByText("Сохранить исходный план", { exact: true }).first()).toBeVisible();
    await expectNoForbiddenCopy(page);
  });

  test("four tabs restore through URL and the report metadata is loaded only on demand", async ({ page }) => {
    const guard = await installResultRoutes(page);
    await openResult(page);
    expect(guard.reportCalls).toHaveLength(0);

    for (const [name, query, heading] of [
      ["Обзор", "overview", "Оборот и ROAS"],
      ["Сценарии и надежность", "scenarios", "Сценарии и надежность"],
      ["Медиаплан", "media-plan", "Исходный план → просматриваемый сценарий"],
      ["Отчет", "report", "Выгрузка результата"],
    ] as const) {
      await page.getByRole("tab", { name }).click();
      await expect(page).toHaveURL(new RegExp(`tab=${query}`));
      await expect(page.getByRole("heading", { name: heading, exact: true }).first()).toBeVisible();
    }
    await expect(page.getByRole("heading", { name: "Отчет готов" })).toBeVisible();
    expect(guard.reportCalls).toHaveLength(1);
  });

  test("downloads the ready final Excel report through its canonical artifact path", async ({ page }) => {
    await installResultRoutes(page);
    await openResult(page, "?tab=report");

    await expect(page.getByRole("heading", { name: "mmm_campaign_result.xlsx" })).toBeVisible();
    const link = page.getByRole("link", { name: "Скачать отчет" });
    await expect(link).toHaveAttribute(
      "href",
      /\/api\/v1\/artifacts\/artifact_1234567890abcdef\/download$/,
    );
    const downloadEvent = page.waitForEvent("download");
    await link.click();
    const download = await downloadEvent;
    expect(await download.failure()).toBeNull();
    expect(new URL(download.url()).pathname).toBe(
      "/api/v1/artifacts/artifact_1234567890abcdef/download",
    );
    // Chromium does not pass an anchor download navigation through Playwright
    // route interception. The download event URL is the browser-level source
    // of truth here; the live acceptance below verifies the returned XLSX body.
    await expect(page.getByRole("heading", { name: "Демонстрационная кампания" })).toBeVisible();
    await expect(page.getByText("267,8 млн ₽", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("КОНФЛИКТУЮЩАЯ КАМПАНИЯ ИЗ V1", { exact: true })).toHaveCount(0);
    await expect(page.getByText("999 999 999 999", { exact: true })).toHaveCount(0);
    await page.getByRole("tab", { name: "Обзор" }).click();
    await expect(page.getByText("345 млн ₽", { exact: true }).first()).toBeVisible();
  });

  for (const [status, title, displayText] of [
    ["unavailable", "Отчет недоступен", "Отчет пока не опубликован."],
    ["failed", "Не удалось сформировать отчет", "Формирование отчета завершилось ошибкой."],
  ] as const) {
    test(`renders a controlled report ${status} state`, async ({ page }) => {
      await installResultRoutes(page, {
        reportPayload: buildReportArtifactsPayload({
          status,
          display_text: displayText,
          generated_at_utc: null,
          artifact: null,
          sheets: [],
        }),
      });
      await openResult(page, "?tab=report");
      await expect(page.getByRole("heading", { name: title })).toBeVisible();
      await expect(page.getByText(displayText, { exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "Скачать отчет" })).toHaveCount(0);
    });
  }

  test("fails closed for an invalid report download path without hiding v2 result", async ({ page }) => {
    await installResultRoutes(page, {
      reportPayload: buildReportArtifactsPayload({
        artifact: {
          artifact_id: "artifact_1234567890abcdef",
          display_name: "mmm_campaign_result.xlsx",
          media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          size_bytes: 65_536,
          sha256: "a".repeat(64),
          download_path: "file:///Users/example/report.xlsx",
        },
      }),
    });
    await openResult(page, "?tab=report");
    await expect(page.getByRole("heading", { name: "Формат сведений об отчете не поддерживается" }))
      .toBeVisible();
    await expect(page.getByRole("link", { name: "Скачать отчет" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Демонстрационная кампания" })).toBeVisible();
  });

  test("does not expose report links without report.download permission", async ({ page }) => {
    await installViewerSession(page);
    await installResultRoutes(page);
    await openResult(page, "?tab=report");
    await expect(page.getByRole("heading", { name: "mmm_campaign_result.xlsx" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Скачать отчет" })).toHaveCount(0);
    await expect(page.getByText("Нет доступа к скачиванию", { exact: true })).toBeVisible();
  });

  test("downloads a backend-published working media-plan artifact", async ({ page }) => {
    await installResultRoutes(page, {
      reportPayload: buildReportArtifactsPayload({
        working_media_plan: {
          status: "ready",
          display_text: "Рабочий медиаплан готов.",
          artifact: {
            artifact_id: "artifact_fedcba0987654321",
            display_name: "working_media_plan.xlsx",
            media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes: 32_768,
            sha256: "b".repeat(64),
            download_path: "/api/v1/artifacts/artifact_fedcba0987654321/download",
          },
        },
      }),
    });
    await openResult(page, "?tab=report");
    await expect(page.getByRole("heading", { name: "working_media_plan.xlsx" })).toBeVisible();
    const downloadEvent = page.waitForEvent("download");
    await page.getByRole("link", { name: "Скачать медиаплан" }).click();
    const download = await downloadEvent;
    expect(await download.failure()).toBeNull();
    expect(new URL(download.url()).pathname).toBe(
      "/api/v1/artifacts/artifact_fedcba0987654321/download",
    );
  });

  test("fails closed for an unsupported result contract", async ({ page }) => {
    const unsupported = { ...buildJobResultViewV2(), schema_version: "3.0.0" };
    await installResultRoutes(page, { resultPayload: unsupported });
    await page.goto(`/calculations/${TEST_JOB_ID}/result`);
    await expect(page.getByRole("heading", { name: "Данные результата имеют неподдерживаемый формат" }))
      .toBeVisible();
    await expect(page.getByText("Демонстрационная кампания", { exact: true })).toHaveCount(0);
  });

  test("loading and not-ready states remain controlled", async ({ page }) => {
    await installResultRoutes(page, { resultDelayMs: 700 });
    const navigation = page.goto(`/calculations/${TEST_JOB_ID}/result`);
    await expect(page.getByText("Получаем результат расчета…", { exact: true })).toBeVisible();
    await navigation;
    await expect(page.getByRole("heading", { name: "Демонстрационная кампания" })).toBeVisible();

    await page.unroute("**/api/v1/jobs/*/result-view-v2");
    await page.route("**/api/v1/jobs/*/result-view-v2", async (route) => {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify(errorPayload("RESOURCE_NOT_READY")),
      });
    });
    await page.reload();
    await expect(page.getByRole("heading", { name: "Результат еще не опубликован" })).toBeVisible();
  });

  for (const viewport of [
    { width: 375, height: 812 },
    { width: 812, height: 375 },
    { width: 1_440, height: 900 },
  ]) {
    test(`has no document overflow at ${viewport.width}x${viewport.height}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await installResultRoutes(page);
      await openResult(page, "?tab=scenarios");
      await expectNoDocumentOverflow(page);
      await expectNoForbiddenCopy(page);
    });
  }

  for (const theme of ["dark", "light"] as const) {
    test(`small result copy meets WCAG contrast in ${theme} theme`, async ({ page }) => {
      await page.setViewportSize({ width: 1_440, height: 900 });
      await setTheme(page, theme);
      await installResultRoutes(page);
      await openResult(page, "?tab=overview");

      const samples = [
        ...await measureContentContrast(page, RESULT_CONTRAST_TARGETS),
      ];
      await page.getByRole("tab", { name: "Сценарии и надежность" }).click();
      samples.push(...await measureContentContrast(page, RESULT_CONTRAST_TARGETS));

      const coveredTargets = new Set(samples.map((sample) => sample.target));
      for (const target of RESULT_CONTRAST_TARGETS) {
        expect(coveredTargets, `${target.name} was not measured`).toContain(target.name);
      }
      const minimum = samples.reduce((current, sample) => (
        sample.ratio < current.ratio ? sample : current
      ));
      test.info().annotations.push({
        type: "contrast",
        description: `${minimum.ratio.toFixed(3)}:1 — ${minimum.text}`,
      });
      console.info(
        `[phase-e1b-result-contrast:${theme}] minimum ${minimum.ratio.toFixed(3)}:1`,
        JSON.stringify(minimum),
      );
      expect(minimum.ratio, JSON.stringify(minimum, null, 2)).toBeGreaterThanOrEqual(4.5);
    });
  }
});

test.describe("Phase E.1B result review screenshots", () => {
  for (const theme of ["dark", "light"] as const) {
    for (const screenshotCase of [
      { stem: "result-s1", search: "?tab=overview", heading: "Оборот и ROAS", resultPayload: undefined },
      { stem: "result-s5-safe-partial", search: "?tab=scenarios", heading: "Безопасно распределяемая часть", resultPayload: undefined },
      { stem: "result-s5-full-conservative", search: "?tab=scenarios", heading: "Полный осторожный план", resultPayload: buildFullConservativeResult() },
      { stem: "result-s6-infeasible", search: "?tab=scenarios", heading: "Полный план максимального эффекта недоступен", resultPayload: undefined },
      { stem: "result-s6-feasible", search: "?tab=scenarios", heading: "План максимального эффекта", resultPayload: buildFeasibleS6Result() },
      { stem: "result-media-s5", search: "?tab=media-plan&scenario=S05", heading: "План согласован с результатом", resultPayload: undefined },
      { stem: "result-report-ready", search: "?tab=report", heading: "Отчет готов", resultPayload: undefined },
    ] as const) {
      test(`${screenshotCase.stem}-${theme}`, async ({ page }) => {
        await page.setViewportSize({ width: 1_440, height: 900 });
        await setTheme(page, theme);
        await installResultRoutes(page, { resultPayload: screenshotCase.resultPayload });
        await openResult(page, screenshotCase.search);
        const focus = page.getByText(screenshotCase.heading, { exact: true }).first();
        await focus.scrollIntoViewIfNeeded();
        await expect(focus).toBeVisible();
        await expectNoDocumentOverflow(page);
        await expectNoForbiddenCopy(page);
        mkdirSync(REVIEW_DIRECTORY, { recursive: true });
        await page.screenshot({
          path: `${REVIEW_DIRECTORY}${screenshotCase.stem}-${theme}.png`,
          fullPage: false,
          animations: "disabled",
          caret: "hide",
        });
      });
    }

    test(`result-unsupported-${theme}`, async ({ page }) => {
      await page.setViewportSize({ width: 1_440, height: 900 });
      await setTheme(page, theme);
      await installResultRoutes(page, {
        resultPayload: { ...buildJobResultViewV2(), schema_version: "3.0.0" },
      });
      await page.goto(`/calculations/${TEST_JOB_ID}/result`);
      await expect(page.getByRole("heading", { name: "Данные результата имеют неподдерживаемый формат" }))
        .toBeVisible();
      mkdirSync(REVIEW_DIRECTORY, { recursive: true });
      await page.screenshot({
        path: `${REVIEW_DIRECTORY}result-unsupported-${theme}.png`,
        fullPage: false,
        animations: "disabled",
        caret: "hide",
      });
    });

    test(`result-mobile-s5-${theme}`, async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await setTheme(page, theme);
      await installResultRoutes(page);
      await openResult(page, "?tab=scenarios");
      await page.locator("#scenario-S05").scrollIntoViewIfNeeded();
      await expectNoDocumentOverflow(page);
      await expectNoForbiddenCopy(page);
      mkdirSync(REVIEW_DIRECTORY, { recursive: true });
      await page.screenshot({
        path: `${REVIEW_DIRECTORY}result-mobile-s5-${theme}.png`,
        fullPage: false,
        animations: "disabled",
        caret: "hide",
      });
    });
  }
});
