import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { JobProgressViewV1 } from "../src/shared/api/generated/job-progress-view-v1";

const JOB_ID = "job_000000000001";
const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/job-progress-v1/", import.meta.url),
);

mkdirSync(REVIEW_DIRECTORY, { recursive: true });

const titles = [
  "Расчет ожидает запуска",
  "Подготавливаем медиаплан",
  "Рассчитываем исходный медиаплан",
  "Рассчитываем контрольные сценарии",
  "Ищем устойчивый вариант",
  "Перебираем варианты распределения",
  "Проверяем результаты",
  "Формируем отчет",
  "Расчет завершен",
] as const;

type StageStatus = JobProgressViewV1["stages"][number]["status"];

function stageTime(index: number, finish = false): string {
  const minute = index * 3 + (finish ? 2 : 0);
  return `2026-07-16T10:${String(minute).padStart(2, "0")}:00Z`;
}

function makeStages(options: {
  completedThrough: number;
  activeIndex?: number;
  failedIndex?: number;
  warningIndexes?: number[];
  terminal?: boolean;
}): JobProgressViewV1["stages"] {
  const warnings = new Set(options.warningIndexes ?? []);
  return titles.map((title, index) => {
    let status: StageStatus;
    if (index === options.failedIndex) status = "failed";
    else if (index === options.activeIndex) status = "active";
    else if (index <= options.completedThrough) status = warnings.has(index) ? "warning" : "completed";
    else status = options.terminal ? "skipped" : "pending";
    const started = ["active", "completed", "warning", "failed"].includes(status);
    const finished = ["completed", "warning", "failed"].includes(status);
    const progress = status === "active" && index === 5
      ? { current: 1_536, total: 2_048, unit: "вариантов" }
      : status === "active" && index === 7
        ? { current: 1, total: null, unit: "отчет" }
        : null;
    return {
      stage_id: `P${String(index + 1).padStart(2, "0")}` as JobProgressViewV1["current_stage_id"],
      order: index + 1,
      title,
      status,
      started_at_utc: started ? stageTime(index) : null,
      finished_at_utc: finished ? stageTime(index, true) : null,
      display_text: status === "pending"
        ? "Этап начнется после завершения предыдущих шагов."
        : status === "skipped"
          ? "Этап не выполнялся после завершения расчета."
          : `${title}. Сведения обновлены по состоянию задачи.`,
      progress,
    };
  }) as JobProgressViewV1["stages"];
}

function baseView(overrides: Partial<JobProgressViewV1> = {}): JobProgressViewV1 {
  return {
    contract_name: "job_progress_view_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    job_id: JOB_ID,
    job_status: { code: "running", display_text: "Расчет выполняется" },
    queue: { position: null, queued_jobs_total: 1, display_text: "Расчет уже запущен." },
    campaign: {
      campaign_id: "campaign_000000000002",
      campaign_name: "Летняя кампания: Москва и регионы",
      segment: ["ТС5/Онлайн", "ТС5/Оффлайн"],
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      total_budget_rub: 52_400_000,
      channels_n: 4,
      geographies_n: 12,
    },
    current_stage_id: "P02",
    stages: makeStages({ completedThrough: 0, activeIndex: 1 }),
    scenario6: {
      status: "pending",
      attempt_budget: 2_048,
      attempts_checked: null,
      safe_candidates: null,
      blocked_candidates: null,
      finalists_scored: null,
      finalists_total: 600,
    },
    report: {
      status: "pending",
      display_text: "Отчет будет сформирован после проверки результатов.",
      retryable: false,
    },
    errors: [],
    can_cancel: true,
    result_available: false,
    updated_at_utc: "2026-07-16T11:00:00Z",
    ...overrides,
  };
}

function queuedView(position: number | null = 3): JobProgressViewV1 {
  return baseView({
    job_status: { code: "queued", display_text: "Расчет ожидает запуска" },
    queue: {
      position,
      queued_jobs_total: 8,
      display_text: "Расчет поставлен в очередь и запустится автоматически.",
    },
    current_stage_id: "P01",
    stages: makeStages({ completedThrough: -1, activeIndex: 0 }),
  });
}

function prepareView(): JobProgressViewV1 {
  return baseView();
}

function scenario6View(): JobProgressViewV1 {
  return baseView({
    current_stage_id: "P06",
    stages: makeStages({ completedThrough: 4, activeIndex: 5, warningIndexes: [4] }),
    scenario6: {
      status: "running",
      attempt_budget: 2_048,
      attempts_checked: 1_536,
      safe_candidates: null,
      blocked_candidates: null,
      finalists_scored: 11,
      finalists_total: 600,
    },
  });
}

function reportView(): JobProgressViewV1 {
  return baseView({
    current_stage_id: "P08",
    stages: makeStages({ completedThrough: 6, activeIndex: 7, warningIndexes: [4] }),
    scenario6: {
      status: "completed",
      attempt_budget: 2_048,
      attempts_checked: 1_706,
      safe_candidates: null,
      blocked_candidates: null,
      finalists_scored: 11,
      finalists_total: 600,
    },
    report: { status: "running", display_text: "Проверяем и публикуем Excel-отчет.", retryable: false },
  });
}

function succeededView(scenario6Unavailable = false): JobProgressViewV1 {
  return baseView({
    job_status: { code: "succeeded", display_text: "Расчет завершен" },
    current_stage_id: "P09",
    stages: makeStages({ completedThrough: 8, warningIndexes: scenario6Unavailable ? [5] : [4], terminal: true }),
    scenario6: scenario6Unavailable
      ? {
          status: "unavailable",
          attempt_budget: 2_048,
          attempts_checked: 0,
          safe_candidates: null,
          blocked_candidates: null,
          finalists_scored: null,
          finalists_total: 600,
        }
      : {
          status: "completed",
          attempt_budget: 2_048,
          attempts_checked: 1_706,
          safe_candidates: null,
          blocked_candidates: null,
          finalists_scored: 11,
          finalists_total: 600,
        },
    report: { status: "completed", display_text: "Excel-отчет готов.", retryable: false },
    can_cancel: false,
    result_available: true,
  });
}

function failedView(stageIndex = 5): JobProgressViewV1 {
  const stageId = `P${String(stageIndex + 1).padStart(2, "0")}` as JobProgressViewV1["current_stage_id"];
  const isReport = stageIndex === 7;
  const isScenario6 = stageIndex === 5;
  return baseView({
    job_status: { code: "failed", display_text: "Расчет завершился с ошибкой" },
    current_stage_id: stageId,
    stages: makeStages({ completedThrough: stageIndex - 1, failedIndex: stageIndex, terminal: true }),
    scenario6: {
      status: isScenario6 ? "failed" : stageIndex < 5 ? "pending" : "completed",
      attempt_budget: 2_048,
      attempts_checked: isScenario6 ? 780 : null,
      safe_candidates: null,
      blocked_candidates: null,
      finalists_scored: null,
      finalists_total: 600,
    },
    report: {
      status: isReport ? "failed" : "not_required",
      display_text: isReport
        ? "Не удалось опубликовать обязательный Excel-отчет."
        : "Отчет не требовался после остановки расчета.",
      retryable: isReport,
    },
    errors: [
      {
        error_id: "error_000000000003",
        stage_id: stageId,
        severity: "error",
        blocking: true,
        retryable: true,
        display_text: "Расчет остановлен: полученные данные не удалось безопасно обработать. Подробности скрыты, чтобы не показывать внутренние сведения системы.",
        recommended_action: "Проверьте исходный медиаплан и запустите новый расчет после исправления.",
      },
      {
        error_id: "error_000000000004",
        stage_id: "P05",
        severity: "warning",
        blocking: false,
        retryable: false,
        display_text: "Один из предыдущих этапов завершился с замечанием.",
        recommended_action: "Учитывайте замечание при проверке нового расчета.",
      },
    ],
    can_cancel: false,
    result_available: false,
  });
}

function cancelRequestedView(): JobProgressViewV1 {
  return {
    ...scenario6View(),
    job_status: { code: "cancel_requested", display_text: "Расчет останавливается" },
    can_cancel: false,
  };
}

function cancelledView(): JobProgressViewV1 {
  return baseView({
    job_status: { code: "cancelled", display_text: "Расчет отменен" },
    current_stage_id: "P06",
    stages: makeStages({ completedThrough: 4, terminal: true }),
    scenario6: {
      status: "unavailable",
      attempt_budget: 2_048,
      attempts_checked: null,
      safe_candidates: null,
      blocked_candidates: null,
      finalists_scored: null,
      finalists_total: 600,
    },
    report: { status: "not_required", display_text: "Отчет не требовался после отмены.", retryable: false },
    can_cancel: false,
  });
}

function timedOutView(): JobProgressViewV1 {
  const payload = failedView(5);
  payload.job_status = { code: "timed_out", display_text: "Расчет не завершен вовремя" };
  payload.errors[0].display_text = "Расчет превысил допустимое время и был безопасно остановлен.";
  payload.errors[0].recommended_action = "Повторите расчет позже или обратитесь к ответственному аналитику.";
  return payload;
}

function factCatalog() {
  return {
    contract_name: "mmm_fact_catalog_v1",
    schema_version: "1.0.0",
    facts: Array.from({ length: 20 }, (_, index) => ({
      fact_id: `fact_review_${String(index).padStart(2, "0")}`,
      category: "forecast",
      text: index === 0
        ? "MMM оценивает дополнительный эффект рекламы, а не весь оборот бизнеса."
        : `Проверенный факт о маркетинговом моделировании ${index + 1}.`,
      source_label: "Методическая памятка MMM",
    })),
  };
}

interface MockOptions {
  progressStatus?: number;
  factsStatus?: number;
  progressSequence?: Array<{ status: number; payload?: unknown }>;
  onCancel?: () => void;
}

async function mockProductEndpoints(
  page: Page,
  payload: unknown,
  options: MockOptions = {},
) {
  let progressCalls = 0;
  let rawProgressCalls = 0;
  let cancelCalls = 0;

  await page.route("**/api/v1/jobs/*/progress", async (route) => {
    rawProgressCalls += 1;
    await route.abort("failed");
  });
  await page.route("**/api/v1/jobs/*/progress-view", async (route) => {
    const sequenceEntry = options.progressSequence?.[
      Math.min(progressCalls, (options.progressSequence?.length ?? 1) - 1)
    ];
    progressCalls += 1;
    await route.fulfill({
      status: sequenceEntry?.status ?? options.progressStatus ?? 200,
      contentType: "application/json",
      body: JSON.stringify(sequenceEntry?.payload ?? payload),
    });
  });
  await page.route("**/api/v1/meta/mmm-facts", async (route) => {
    await route.fulfill({
      status: options.factsStatus ?? 200,
      contentType: "application/json",
      body: JSON.stringify(options.factsStatus && options.factsStatus >= 400 ? { error: {} } : factCatalog()),
    });
  });
  await page.route("**/api/v1/jobs/*/cancel", async (route: Route) => {
    cancelCalls += 1;
    options.onCancel?.();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job_id: JOB_ID, cancellation_requested: true }),
    });
  });

  return {
    progressCalls: () => progressCalls,
    rawProgressCalls: () => rawProgressCalls,
    cancelCalls: () => cancelCalls,
  };
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

async function openProgress(page: Page, payload: JobProgressViewV1) {
  await page.goto(`/calculations/${payload.job_id}/progress`);
  await expect(page.getByRole("heading", { name: payload.campaign.campaign_name })).toBeVisible();
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
}

async function assertNoDocumentOverflow(page: Page) {
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

const screenshotCases = [
  ["01-queued", queuedView()],
  ["02-running-prepare", prepareView()],
  ["03-running-scenario6", scenario6View()],
  ["04-running-report", reportView()],
  ["05-succeeded", succeededView()],
  ["06-failed", failedView()],
] as const;

test.describe("job progress review screenshots", () => {
  for (const [name, payload] of screenshotCases) {
    for (const theme of ["dark", "light"] as const) {
      test(`${name}-${theme}`, async ({ page }) => {
        await page.setViewportSize({ width: 1_440, height: 900 });
        await setTheme(page, theme);
        const calls = await mockProductEndpoints(page, payload);
        await openProgress(page, payload);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await assertNoDocumentOverflow(page);
        expect(calls.rawProgressCalls()).toBe(0);
        await page.screenshot({
          path: `${REVIEW_DIRECTORY}${name}-${theme}.png`,
          fullPage: false,
          animations: "disabled",
        });
      });
    }
  }
});

test.describe("job progress product states", () => {
  test("queued unknown position is not displayed as zero", async ({ page }) => {
    const payload = queuedView(null);
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    await expect(page.getByText("Положение в очереди уточняется")).toBeVisible();
    await expect(page.getByText(/Позиция в очереди: 0/)).toHaveCount(0);
  });

  test("running Scenario 6 uses only backend counters", async ({ page }) => {
    const payload = scenario6View();
    const calls = await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    await expect(page.getByText("Проверено вариантов").locator("..")).toContainText("1 536 / 2 048");
    await expect(page.getByText("Пересчитано финалистов").locator("..")).toContainText("11 / 600");
    await expect(page.getByText("Прошли проверку")).toHaveCount(0);
    await expect(page.getByText("Требуют проверки")).toHaveCount(0);
    expect(calls.rawProgressCalls()).toBe(0);
  });

  test("safe_candidates null hides its row", async ({ page }) => {
    const payload = scenario6View();
    payload.scenario6.safe_candidates = null;
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    await expect(page.getByText("Прошли проверку", { exact: true })).toHaveCount(0);
  });

  test("safe_candidates zero renders a known zero", async ({ page }) => {
    const payload = scenario6View();
    payload.scenario6.safe_candidates = 0;
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    await expect(
      page.getByText("Прошли проверку", { exact: true }).locator("..").locator("dd"),
    ).toHaveText("0");
  });

  test("blocked_candidates null hides its row", async ({ page }) => {
    const payload = scenario6View();
    payload.scenario6.blocked_candidates = null;
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    await expect(page.getByText("Требуют проверки", { exact: true })).toHaveCount(0);
  });

  test("blocked_candidates zero renders a known zero", async ({ page }) => {
    const payload = scenario6View();
    payload.scenario6.blocked_candidates = 0;
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    await expect(
      page.getByText("Требуют проверки", { exact: true }).locator("..").locator("dd"),
    ).toHaveText("0");
  });

  for (const [name, payload, text] of [
    ["cancel_requested", cancelRequestedView(), "Расчет останавливается"],
    ["cancelled", cancelledView(), "Расчет отменен"],
    ["timed_out", timedOutView(), "Расчет не завершен вовремя"],
    ["failed_prepare", failedView(1), "Расчет завершился с ошибкой"],
    ["failed_scenario6", failedView(5), "Не удалось завершить поиск вариантов"],
    ["failed_report", failedView(7), "Отчет не сформирован"],
    ["scenario6_unavailable", succeededView(true), "Адаптивный поиск не применялся"],
  ] as const) {
    test(`renders ${name}`, async ({ page }) => {
      await mockProductEndpoints(page, payload);
      await openProgress(page, payload);
      await expect(page.getByText(text, { exact: false }).first()).toBeVisible();
    });
  }

  test("facts failure does not block the progress page", async ({ page }) => {
    const payload = prepareView();
    await mockProductEndpoints(page, payload, { factsStatus: 503 });
    await openProgress(page, payload);
    await expect(page.getByRole("heading", { name: "Этапы расчета" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "MMM за минуту" })).toHaveCount(0);
  });
});

test.describe("job progress recovery and actions", () => {
  test("cached snapshot remains visible after a temporary network failure", async ({ page }) => {
    const payload = scenario6View();
    await mockProductEndpoints(page, payload, {
      progressSequence: [
        { status: 200, payload },
        { status: 200, payload },
        { status: 500, payload: { error: { code: "TEMPORARY" } } },
      ],
    });
    await openProgress(page, payload);
    await expect(page.getByText(/Последние полученные сведения сохранены/)).toBeVisible({ timeout: 4_000 });
    await expect(page.getByRole("heading", { name: payload.campaign.campaign_name })).toBeVisible();
  });

  test("refresh reconstructs the page from progress-view", async ({ page }) => {
    const payload = prepareView();
    const calls = await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    await page.reload();
    await expect(page.getByRole("heading", { name: payload.campaign.campaign_name })).toBeVisible();
    expect(calls.progressCalls()).toBeGreaterThanOrEqual(2);
  });

  test("terminal polling stops and result opens only by button", async ({ page }) => {
    const payload = succeededView();
    const calls = await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    const callsAfterInitialLoad = calls.progressCalls();
    await page.waitForTimeout(1_800);
    expect(calls.progressCalls()).toBe(callsAfterInitialLoad);
    await expect(page).toHaveURL(`/calculations/${JOB_ID}/progress`);
    await page.getByRole("link", { name: "Открыть результат" }).click();
    await expect(page).toHaveURL(`/calculations/${JOB_ID}/result`);
  });

  test("cancel requires confirmation and updates from a new snapshot", async ({ page }) => {
    let current = scenario6View();
    const calls = await mockProductEndpoints(page, current, {
      onCancel: () => { current = cancelRequestedView(); },
    });
    await page.unroute("**/api/v1/jobs/*/progress-view");
    await page.route("**/api/v1/jobs/*/progress-view", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
    });
    await openProgress(page, current);
    await page.getByRole("button", { name: "Отменить расчет" }).click();
    const dialog = page.getByRole("dialog", { name: "Отменить расчет?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Отменить расчет" }).click();
    await expect(page.getByRole("heading", { name: "Расчет останавливается" })).toBeVisible();
    expect(calls.cancelCalls()).toBe(1);
    await expect(page.getByText("Расчет отменен", { exact: true })).toHaveCount(0);
  });

  test("cancel dialog supports keyboard escape and restores focus", async ({ page }) => {
    const payload = scenario6View();
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    const trigger = page.getByRole("button", { name: "Отменить расчет" });
    await trigger.focus();
    await trigger.press("Enter");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
});

test.describe("job progress controlled failures", () => {
  test("404", async ({ page }) => {
    await mockProductEndpoints(page, {}, { progressStatus: 404 });
    await page.goto(`/calculations/${JOB_ID}/progress`);
    await expect(page.getByRole("heading", { name: "Расчет не найден" })).toBeVisible();
  });

  test("409", async ({ page }) => {
    await mockProductEndpoints(page, {}, { progressStatus: 409 });
    await page.goto(`/calculations/${JOB_ID}/progress`);
    await expect(page.getByRole("heading", { name: "Состояние расчета временно не согласовано" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Обновить сведения" })).toBeVisible();
  });

  test("unsupported contract", async ({ page }) => {
    const payload = { ...prepareView(), schema_version: "2.0.0" };
    await mockProductEndpoints(page, payload);
    await page.goto(`/calculations/${JOB_ID}/progress`);
    await expect(page.getByRole("heading", { name: "Формат сведений не поддерживается" })).toBeVisible();
  });

  test("route job ID mismatch", async ({ page }) => {
    const payload = { ...prepareView(), job_id: "job_ffffffffffff" };
    await mockProductEndpoints(page, payload);
    await page.goto(`/calculations/${JOB_ID}/progress`);
    await expect(page.getByRole("heading", { name: "Формат сведений не поддерживается" })).toBeVisible();
  });
});

test.describe("job progress responsive and accessibility", () => {
  test("mobile long content has no document overflow", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const payload = failedView();
    payload.campaign.campaign_name = "Очень длинное название кампании с несколькими регионами, каналами и периодами размещения";
    payload.campaign.segment = [
      "Очень длинный сегмент покупателей с повышенной частотой",
      "Еще один длинный сегмент для проверки переноса",
      "Третий сегмент",
      "Четвертый сегмент",
    ];
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    await assertNoDocumentOverflow(page);
  });

  test("landscape layout has no document overflow", async ({ page }) => {
    await page.setViewportSize({ width: 812, height: 375 });
    const payload = scenario6View();
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    await assertNoDocumentOverflow(page);
  });

  test("reduced motion disables active looping animation", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const payload = prepareView();
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    const animationName = await page.locator('[aria-live="polite"] [aria-hidden="true"] span')
      .first()
      .evaluate((element) => getComputedStyle(element).animationName);
    expect(animationName).toBe("none");
  });

  test("visible copy contains no raw implementation names", async ({ page }) => {
    const payload = scenario6View();
    await mockProductEndpoints(page, payload);
    await openProgress(page, payload);
    const visibleText = await page.locator("body").innerText();
    for (const term of [
      "backend",
      "API",
      "worker",
      "phase",
      "Progress events",
      "posterior",
      "candidate_id",
      "attempt_id",
    ]) {
      expect(visibleText.toLowerCase()).not.toContain(term.toLowerCase());
    }
  });
});
