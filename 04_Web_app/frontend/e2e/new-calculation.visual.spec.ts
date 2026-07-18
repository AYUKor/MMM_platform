import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type {
  ArtifactIdentity,
  CampaignUpload,
  DecisionJob,
  ValidationResult,
} from "../src/shared/api/generated/application-lifecycle-v1";
import type { ValidationResultV2 } from "../src/shared/api/generated/validation-result-v2";
import {
  buildValidationResultV2,
  CONTROL_REQUESTED_BUDGET,
  TEST_GEOS,
  TEST_VALIDATION_ID,
} from "../src/test/businessSemanticsV2Fixtures";
import { installAuthenticatedAdminSession } from "./support/auth";
import { measureContentContrast, type ContrastTarget } from "./support/contrast";

const UPLOAD_ID = "upload_eeeeeeeeeeeeeeeeeeee";
const JOB_ID = "job_dddddddddddddddddddd";
const CAMPAIGN_ID = "campaign_dddddddddddddddddddd";
const SCENARIO6_ATTEMPTS = 3_217;
const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/phase-e1b-business-semantics-v1/", import.meta.url),
);
const GEO_REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/phase-e1d-interactive-geo-maps-v1/", import.meta.url),
);

const FORBIDDEN_COPY = [
  "Дополнительные заказы",
  "Заказы на 100 000 ₽",
  "Механизм среднего чека",
  "Часть дополнительного оборота",
  "Digital_Performance",
  "OOH_Total",
  "orders_per_user",
  "avg_basket",
  "... ещё",
] as const;

const VALIDATION_CONTRAST_TARGETS = [
  { name: "validation facts", selector: '[class*="validationFacts"] dt' },
  { name: "validation checks", selector: '[class*="compactChecks"] p' },
  { name: "limitation metadata", selector: '[class*="limitationList"] header span:first-child' },
  { name: "limitation labels", selector: '[class*="limitationList"] dt' },
  { name: "limitation guidance", selector: '[class*="limitationList"] dd' },
  { name: "map attribution", selector: '[class*="attribution"] span' },
] as const satisfies readonly ContrastTarget[];

const artifact = (kind: string, suffix: string): ArtifactIdentity => ({
  artifact_id: `artifact_${suffix.padEnd(20, suffix)}`,
  kind,
  display_name: `${kind}.json`,
  media_type: "application/json",
  sha256: suffix.repeat(64).slice(0, 64),
  size_bytes: 2_048,
  storage_key: `synthetic/${kind}`,
});

const sourceArtifact = artifact("campaign_upload_source", "a");
const parsedArtifact = artifact("campaign_upload_parsed", "b");
const normalizedArtifact = artifact("campaign_plan_normalized", "c");
const flightingArtifact = artifact("campaign_flighting_daily", "d");
const modelValidationArtifact = artifact("campaign_model_validation", "e");
const workflowArtifact = artifact("workflow_config", "f");

const parsedUpload: CampaignUpload = {
  contract_name: "campaign_upload_v1",
  schema_version: "1.0.0",
  record_origin: "synthetic_fixture",
  upload_id: UPLOAD_ID,
  actor_id: "actor_eeeeeeeeeeeeeeeeeeee",
  status: { code: "parsed", display_text: "Файл прочитан" },
  received_at_utc: "2026-07-18T10:00:00Z",
  parsed_at_utc: "2026-07-18T10:00:01Z",
  rejected_at_utc: null,
  original_file: { ...sourceArtifact, display_name: "synthetic-media-plan.xlsx" },
  parser_name: "campaign_plan_parser",
  parser_version: "1.0.0",
  parsed_payload: parsedArtifact,
  source_rows_n: 45,
  detected_campaigns_n: 1,
  rejection_error_id: null,
};

const receivedUpload: CampaignUpload = {
  ...parsedUpload,
  status: { code: "received", display_text: "Файл принят" },
  parsed_at_utc: null,
  parser_name: null,
  parser_version: null,
  parsed_payload: null,
  source_rows_n: null,
  detected_campaigns_n: null,
};

const validationV1: ValidationResult = {
  contract_name: "validation_result_v1",
  schema_version: "1.0.0",
  record_origin: "synthetic_fixture",
  validation_id: TEST_VALIDATION_ID,
  upload_id: UPLOAD_ID,
  status: { code: "valid", display_text: "Кампания проверена" },
  validator_name: "campaign_validator",
  validator_version: "1.0.0",
  started_at_utc: "2026-07-18T10:00:02Z",
  finished_at_utc: "2026-07-18T10:00:03Z",
  source_payload: parsedArtifact,
  model: {
    registry_channel: "preprod",
    registry_event_id: "registry_event_synthetic",
    package_id: "pkg_1111111111111111_2222222222222222",
    package_fingerprint: "1".repeat(64),
    package_manifest_sha256: "2".repeat(64),
    activation_status: "preprod_restricted",
    production_blockers: ["research_preprod"],
  },
  normalized_plan: normalizedArtifact,
  daily_flighting: flightingArtifact,
  model_validation: modelValidationArtifact,
  campaigns: [{
    campaign_id: CAMPAIGN_ID,
    campaign_name: "Демонстрационная кампания",
    segments: ["Сегмент A"],
    start_date: "2026-08-01",
    end_date: "2026-08-15",
    active_days: 15,
    // Lifecycle v1 may carry model-facing identifiers. User-facing channel
    // names must therefore come from validation view-v2, not this array.
    channels: ["Digital_Performance", "OOH_Total", "Радио"],
    geographies: TEST_GEOS.map((geo) => geo.geo_display_name),
    creatives: [],
    source_rows_n: 45,
    normalized_rows_n: 45,
    daily_rows_n: 675,
    uploaded_budget_rub: CONTROL_REQUESTED_BUDGET,
    model_input_budget_rub: CONTROL_REQUESTED_BUDGET,
    unmodeled_budget_rub: 0,
    daily_budget_rub: CONTROL_REQUESTED_BUDGET,
  }],
  totals: {
    source_rows_n: 45,
    normalized_rows_n: 45,
    daily_rows_n: 675,
    uploaded_budget_rub: CONTROL_REQUESTED_BUDGET,
    model_input_budget_rub: CONTROL_REQUESTED_BUDGET,
    unmodeled_budget_rub: 0,
    daily_budget_rub: CONTROL_REQUESTED_BUDGET,
    raw_to_normalized_abs_diff_rub: 0,
    normalized_to_daily_abs_diff_rub: 0,
  },
  blocking_errors: [],
  warnings: [],
  job_creation_allowed: true,
};

const runningValidationV1: ValidationResult = {
  ...validationV1,
  status: { code: "running", display_text: "Проверяем кампанию" },
  finished_at_utc: null,
  campaigns: [],
  totals: null,
  model: null,
  normalized_plan: null,
  daily_flighting: null,
  model_validation: null,
  job_creation_allowed: false,
};

const queuedJob: DecisionJob = {
  contract_name: "decision_job_v1",
  schema_version: "1.0.0",
  record_origin: "synthetic_fixture",
  job_id: JOB_ID,
  idempotency_key: `job:${TEST_VALIDATION_ID}`,
  job_type: "forecast_optimizer_report",
  created_by_actor_id: "actor_eeeeeeeeeeeeeeeeeeee",
  upload_id: UPLOAD_ID,
  validation_id: TEST_VALIDATION_ID,
  normalized_plan: normalizedArtifact,
  daily_flighting: flightingArtifact,
  workflow_config: workflowArtifact,
  model_selector: {
    mode: "registry_channel",
    registry_channel: "preprod",
    package_id: null,
    expected_package_fingerprint: null,
  },
  policies: {
    optimizer_policy_id: "optimizer-v1",
    optimizer_policy_sha256: "3".repeat(64),
    gate_policy_version: "gate-v1",
    business_policy_id: "business-v1",
    business_policy_sha256: "4".repeat(64),
    business_decision_mode: "manual_review",
  },
  sampling: {
    scenario6_attempt_budget: SCENARIO6_ATTEMPTS,
    search_posterior_draws: 100,
    final_posterior_draws: 500,
    search_seed: 42,
    final_seed: 43,
  },
  code_reference: "synthetic-test",
  status: { code: "queued", display_text: "Расчет поставлен в очередь" },
  created_at_utc: "2026-07-18T10:00:04Z",
  queued_at_utc: "2026-07-18T10:00:04Z",
  started_at_utc: null,
  cancel_requested_at_utc: null,
  finished_at_utc: null,
  attempt_number: 1,
  result_id: null,
  terminal_error_id: null,
};

interface ApiOptions {
  upload?: CampaignUpload;
  validationV1?: ValidationResult;
  validationV2?: unknown;
  validationViewStatus?: number;
  profileStatus?: number;
}

interface ApiCalls {
  templateGets: number;
  uploadPosts: number;
  validationPosts: number;
  validationV1Gets: number;
  validationV2Gets: number;
  profileGets: number;
  jobPosts: number;
  forbidden: string[];
}

const routeCalls = new WeakMap<Page, ApiCalls>();

test.beforeEach(async ({ page }) => {
  await installAuthenticatedAdminSession(page);
});

test.afterEach(async ({ page }) => {
  const calls = routeCalls.get(page);
  if (calls) expect(calls.forbidden, "unapproved new-calculation requests").toEqual([]);
});

function errorPayload(code: string, displayText: string) {
  return { error: { code, display_text: displayText, retryable: true, user_action: "Повторите запрос." } };
}

async function fulfill(route: Route, status: number, payload: unknown) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
}

async function installNewCalculationRoutes(
  page: Page,
  options: ApiOptions = {},
): Promise<ApiCalls> {
  const calls: ApiCalls = {
    templateGets: 0,
    uploadPosts: 0,
    validationPosts: 0,
    validationV1Gets: 0,
    validationV2Gets: 0,
    profileGets: 0,
    jobPosts: 0,
    forbidden: [],
  };
  routeCalls.set(page, calls);
  const upload = structuredClone(options.upload ?? parsedUpload);
  const legacyValidation = structuredClone(options.validationV1 ?? validationV1);
  const businessValidation = structuredClone(options.validationV2 ?? buildValidationResultV2());

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const path = url.pathname;
    if (method === "GET" && path === "/api/v1/auth/session" && !url.search) {
      await route.fallback();
      return;
    }
    if (method === "GET" && path === "/api/v1/templates/campaign-plan.xlsx") {
      calls.templateGets += 1;
      await route.fulfill({
        status: 200,
        body: Buffer.from("PK\u0003\u0004synthetic-template", "utf8"),
        headers: {
          "content-disposition": 'attachment; filename="campaign-plan-template.xlsx"',
          "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
      });
      return;
    }
    if (method === "POST" && path === "/api/v1/uploads") {
      calls.uploadPosts += 1;
      await fulfill(route, 202, receivedUpload);
      return;
    }
    if (method === "GET" && path === `/api/v1/uploads/${UPLOAD_ID}`) {
      await fulfill(route, 200, upload);
      return;
    }
    if (method === "POST" && path === `/api/v1/uploads/${UPLOAD_ID}/validations`) {
      calls.validationPosts += 1;
      await fulfill(route, 202, runningValidationV1);
      return;
    }
    if (method === "GET" && path === `/api/v1/validations/${TEST_VALIDATION_ID}`) {
      calls.validationV1Gets += 1;
      await fulfill(route, 200, legacyValidation);
      return;
    }
    if (method === "GET" && path === `/api/v1/validations/${TEST_VALIDATION_ID}/view-v2`) {
      calls.validationV2Gets += 1;
      const status = options.validationViewStatus ?? 200;
      await fulfill(
        route,
        status,
        status === 200
          ? businessValidation
          : errorPayload("VALIDATION_VIEW_UNAVAILABLE", "Результат проверки временно недоступен."),
      );
      return;
    }
    if (method === "GET" && path === "/api/v1/calculation-profile") {
      calls.profileGets += 1;
      const status = options.profileStatus ?? 200;
      await fulfill(route, status, status === 200 ? {
        contract_name: "calculation_profile_v1",
        schema_version: "1.0.0",
        scenario6_attempt_budget: SCENARIO6_ATTEMPTS,
        profile_label: "Профиль поиска",
        model_version_label: "Версия модели",
      } : errorPayload("PROFILE_UNAVAILABLE", "Параметры поиска временно недоступны."));
      return;
    }
    if (method === "POST" && path === `/api/v1/validations/${TEST_VALIDATION_ID}/jobs`) {
      calls.jobPosts += 1;
      await fulfill(route, 202, queuedJob);
      return;
    }
    if (
      method === "GET"
      && (path === `/api/v1/jobs/${JOB_ID}/progress-view` || path === "/api/v1/meta/mmm-facts")
    ) {
      await fulfill(
        route,
        503,
        errorPayload("POST_START_VIEW_UNAVAILABLE", "Экран процесса не входит в этот тест."),
      );
      return;
    }
    calls.forbidden.push(`${method} ${path}${url.search}`);
    await fulfill(route, 599, errorPayload("UNEXPECTED_ROUTE", "Маршрут теста не настроен."));
  });

  return calls;
}

async function selectFile(page: Page, name = "synthetic-media-plan.xlsx") {
  await page.locator('input[type="file"]').setInputFiles({
    name,
    mimeType: name.endsWith(".csv")
      ? "text/csv"
      : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.alloc(2_048, "synthetic-review"),
  });
}

async function expectNoForbiddenCopy(page: Page) {
  const text = await page.locator("body").innerText();
  for (const forbidden of FORBIDDEN_COPY) expect(text).not.toContain(forbidden);
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

function buildPassedValidation(): ValidationResultV2 {
  const validation = structuredClone(buildValidationResultV2());
  validation.status = "passed";
  validation.model_limitations = [];
  validation.geo_points = validation.geo_points.map((point) => ({
    ...point,
    has_model_limitations: false,
    model_limitations_n: 0,
  }));
  return validation;
}

function asUnavailableGeoPoint(
  point: ValidationResultV2["geo_points"][number],
): Extract<ValidationResultV2["geo_points"][number], { coordinates_status: "unavailable" }> {
  return {
    geo_id: point.geo_id,
    geo_display_name: point.geo_display_name,
    input_geo_name: point.input_geo_name,
    canonical_geo_id: null,
    canonical_geo_display_name: null,
    normalization_status: "unknown",
    normalization_rule: "no_registered_alias",
    latitude: null,
    longitude: null,
    coordinates_status: "unavailable",
    region_id: null,
    region_display_name: null,
    budget_rub: point.budget_rub,
    budget_share: point.budget_share,
    channels: point.channels,
    has_model_limitations: point.has_model_limitations,
    model_limitations_n: point.model_limitations_n,
  };
}

function buildPartialMapValidation(): ValidationResultV2 {
  const validation = structuredClone(buildValidationResultV2());
  const unlocatedIndex = validation.geo_points.length - 1;
  const unlocated = asUnavailableGeoPoint(validation.geo_points[unlocatedIndex]);
  validation.geo_points[unlocatedIndex] = unlocated;
  validation.map_coverage = {
    status: "partial",
    located_geographies_n: validation.geo_points.length - 1,
    unlocated_geographies_n: 1,
    unlocated_geographies: [{
      geo_id: unlocated.geo_id,
      geo_display_name: unlocated.geo_display_name,
    }],
    located_budget_rub: CONTROL_REQUESTED_BUDGET - unlocated.budget_rub,
    unlocated_budget_rub: unlocated.budget_rub,
    unlocated_budget_share: unlocated.budget_rub / CONTROL_REQUESTED_BUDGET,
  };
  return validation;
}

function buildUnavailableMapValidation(): ValidationResultV2 {
  const validation = structuredClone(buildValidationResultV2());
  validation.geo_points = validation.geo_points.map(asUnavailableGeoPoint);
  validation.map_coverage = {
    status: "unavailable",
    located_geographies_n: 0,
    unlocated_geographies_n: validation.geo_points.length,
    unlocated_geographies: validation.geo_points.map((point) => ({
      geo_id: point.geo_id,
      geo_display_name: point.geo_display_name,
    })),
    located_budget_rub: 0,
    unlocated_budget_rub: CONTROL_REQUESTED_BUDGET,
    unlocated_budget_share: 1,
  };
  return validation;
}

function mapMarkers(page: Page) {
  return page.locator("[data-map-marker]");
}

function mapLabels(page: Page) {
  return page.locator("[data-map-label]");
}

test("upload screen offers the working campaign-plan template", async ({ page }) => {
  const calls = await installNewCalculationRoutes(page);
  await page.goto("/calculations/new");
  await expect(page.getByRole("heading", { name: "Новый расчет", exact: true })).toBeVisible();
  const template = page.getByRole("link", { name: "Скачать шаблон медиаплана" });
  await expect(template).toHaveAttribute("href", "/api/v1/templates/campaign-plan.xlsx");
  await expect(page.getByText(/с примером заполнения$/)).toBeVisible();
  const response = await page.evaluate(async () => {
    const value = await fetch("/api/v1/templates/campaign-plan.xlsx");
    return { ok: value.ok, type: value.headers.get("content-type") };
  });
  expect(response).toEqual({
    ok: true,
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  expect(calls.templateGets).toBe(1);
});

test("upload and lifecycle validation remain orchestration-only", async ({ page }) => {
  const calls = await installNewCalculationRoutes(page);
  await page.goto("/calculations/new");
  await selectFile(page);
  await page.getByRole("button", { name: "Загрузить файл" }).click();
  await expect(page.getByText("Файл успешно прочитан", { exact: true })).toBeVisible();
  await expect(page.getByText("45", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Продолжить к проверке" }).click();
  await expect(page.getByRole("heading", { name: "Кампания готова к расчету" })).toBeVisible();
  expect(calls.uploadPosts).toBe(1);
  expect(calls.validationPosts).toBe(1);
  expect(calls.validationV1Gets).toBeGreaterThan(0);
  expect(calls.validationV2Gets).toBeGreaterThan(0);
});

test("validation view-v2 separates file checks from grouped model limitations", async ({ page }) => {
  const calls = await installNewCalculationRoutes(page);
  await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);

  const fileValidation = page.getByRole("heading", { name: "Проверка файла" })
    .locator("xpath=ancestor::section[1]");
  await expect(fileValidation).toBeVisible();
  await expect(fileValidation.getByText("Строк", { exact: true }).locator("..")).toContainText("45");
  await expect(fileValidation.getByText("Кампаний", { exact: true }).locator("..")).toContainText("1");
  await expect(fileValidation.getByText("Географий", { exact: true }).locator("..")).toContainText("15");
  await expect(fileValidation.getByText("Каналов", { exact: true }).locator("..")).toContainText("3");
  await expect(fileValidation.getByText("Запрошенный бюджет", { exact: true }).locator("..")).toContainText("267,8 млн ₽");
  await expect(page.getByText("Структура файла корректна.", { exact: true })).toBeVisible();
  await expect(page.getByText("В файле одна кампания.", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ограничения модели" })).toBeVisible();
  await expect(page.getByRole("heading", {
    name: "Для цифровой рекламы часть прогноза требует осторожной интерпретации.",
  })).toBeVisible();
  await expect(page.getByText("Почему это важно", { exact: true }).locator("..")).toContainText(
    "историческая поддержка ограничена",
  );
  await expect(page.getByText("Что можно сделать", { exact: true }).locator("..")).toContainText(
    "Проверьте отмеченные географии",
  );
  await expect(page.getByText("Показать географии (15)", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "15 географий сохранены" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Карта рекламного бюджета текущей кампании" }))
    .toBeVisible();
  await expect(mapMarkers(page)).toHaveCount(15);
  await expect(mapLabels(page)).toHaveCount(15);
  await expect(page.getByText("Координаты городов: GeoNames, CC BY 4.0.", { exact: true }))
    .toBeVisible();
  await expect(page.getByText("Карта пока недоступна", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Продолжить с ограничениями" })).toBeVisible();
  expect(calls.validationV2Gets).toBeGreaterThan(0);
  await expectNoForbiddenCopy(page);
});

test("campaign map preserves all canonical geographies and supports pointer, keyboard, and click tooltips", async ({ page }) => {
  await installNewCalculationRoutes(page);
  await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);

  const map = page.getByRole("group", { name: "Карта рекламного бюджета текущей кампании" });
  await expect(map).toBeVisible();
  await expect(mapMarkers(page)).toHaveCount(15);
  await expect(mapLabels(page)).toHaveCount(15);
  await expect(page.getByText("Подписаны все географии кампании", { exact: true })).toBeVisible();
  await expect(page.getByText("267,8 млн ₽", { exact: true })).toBeVisible();

  const markerBudgets = await mapMarkers(page).evaluateAll((markers) => markers.map((marker) => (
    Number(marker.getAttribute("data-budget-rub"))
  )));
  expect(markerBudgets.reduce((total, budget) => total + budget, 0)).toBe(CONTROL_REQUESTED_BUDGET);

  const firstMarker = mapMarkers(page).first();
  await firstMarker.hover();
  let tooltip = page.locator('[role="tooltip"]');
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText("Цифровая реклама, Наружная реклама, Радио");
  await expect(tooltip.getByText("Ограничения модели", { exact: true }).locator("..")).toContainText("1");

  await page.mouse.move(0, 0);
  await expect(tooltip).toHaveCount(0);
  const keyboardMarker = page.locator(`[data-map-marker="${TEST_GEOS[1].geo_id}"]`);
  await keyboardMarker.focus();
  await expect(tooltip).toContainText("Воронеж");
  await page.keyboard.press("Escape");
  await expect(tooltip).toHaveCount(0);
  await expect(keyboardMarker).toBeFocused();

  const clickMarker = page.locator(`[data-map-marker="${TEST_GEOS[2].geo_id}"]`);
  await clickMarker.dispatchEvent("click");
  tooltip = page.locator('[role="tooltip"]');
  await expect(tooltip).toContainText("Краснодар");
  await expect(tooltip).toContainText("Цифровая реклама, Наружная реклама, Радио");

  await expect(page.getByText("Координаты городов: GeoNames, CC BY 4.0.", { exact: true }))
    .toBeVisible();
  await expect(page.getByText("Контур карты: Natural Earth, public domain.", { exact: true }))
    .toBeVisible();
  await expect(page.locator("body")).not.toContainText("Digital_Performance");
  await expect(page.locator("body")).not.toContainText("OOH_Total");
  await expectNoOverflow(page);
});

test("campaign map keeps unlocated budget visible in partial coverage", async ({ page }) => {
  await installNewCalculationRoutes(page, { validationV2: buildPartialMapValidation() });
  await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);

  await expect(page.getByRole("group", { name: "Карта рекламного бюджета текущей кампании" }))
    .toBeVisible();
  await expect(mapMarkers(page)).toHaveCount(14);
  await expect(mapLabels(page)).toHaveCount(14);
  await expect(page.getByText("Частичное покрытие", { exact: true })).toBeVisible();
  await expect(page.getByText("Не удалось разместить географий: 1", { exact: true })).toBeVisible();
  await expect(page.getByText(/Неразмещенный бюджет:/)).toContainText(/8,8\s+млн ₽/);
  await page.getByText("Показать географии", { exact: true }).last().click();
  await expect(page.getByText("Ярославль", { exact: true }).last()).toBeVisible();
});

test("campaign map has a controlled unavailable state without losing budget", async ({ page }) => {
  await installNewCalculationRoutes(page, { validationV2: buildUnavailableMapValidation() });
  await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);

  await expect(page.getByText("Карта пока недоступна", { exact: true })).toBeVisible();
  await expect(page.getByText(
    "Сервис не опубликовал координаты для географий этой кампании.",
    { exact: true },
  )).toBeVisible();
  await expect(page.getByText("Без координат: 15 географий", { exact: true })).toBeVisible();
  await expect(page.getByText(/Бюджет сохранен:/)).toContainText(/267,8\s+млн ₽/);
  await expect(mapMarkers(page)).toHaveCount(0);
  await expect(mapLabels(page)).toHaveCount(0);
});

test("passed validation keeps file checks separate and reports no model limitations", async ({ page }) => {
  await installNewCalculationRoutes(page, { validationV2: buildPassedValidation() });
  await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);

  await expect(page.getByRole("heading", { name: "Проверка файла" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ограничения модели" })).toBeVisible();
  await expect(page.getByText("Нет ограничений", { exact: true })).toBeVisible();
  await expect(page.getByText("Дополнительные ограничения для этой кампании не опубликованы.", { exact: true }))
    .toBeVisible();
  await expect(page.getByRole("button", { name: "Продолжить к сценариям" })).toBeVisible();
  await expectNoForbiddenCopy(page);
});

test("failed validation view-v2 blocks calculation without a crash state", async ({ page }) => {
  const failed: ValidationResultV2 = buildValidationResultV2();
  failed.status = "failed";
  failed.job_creation_allowed = false;
  failed.file_validation.status = "failed";
  failed.file_validation.blocking_errors_n = 1;
  failed.file_validation.checks[0] = {
    code: "FILE_STRUCTURE",
    status: "failed",
    display_text: "Структуру файла нужно исправить.",
  };
  await installNewCalculationRoutes(page, { validationV2: failed });
  await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);

  await expect(page.getByRole("heading", { name: "Файл нужно исправить" })).toBeVisible();
  await expect(page.getByText("Расчет недоступен", { exact: true })).toBeVisible();
  await expect(page.getByText("Структуру файла нужно исправить.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Продолжить/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Загрузить исправленный файл" })).toBeVisible();
});

test("unsupported validation view fails closed", async ({ page }) => {
  await installNewCalculationRoutes(page, {
    validationV2: { ...buildValidationResultV2(), schema_version: "3.0.0" },
  });
  await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);
  await expect(page.getByRole("alert")).toContainText(/неподдерживаем|не удалось/i);
  await expect(page.getByRole("heading", { name: "Проверка файла" })).toHaveCount(0);
});

test("scenario page keeps six pre-calculation options and backend profile count", async ({ page }) => {
  const calls = await installNewCalculationRoutes(page);
  await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=scenarios`);

  await expect(page.getByRole("heading", { name: "Шесть сценариев будут рассчитаны автоматически" }))
    .toBeVisible();
  for (const title of [
    "Как загружено",
    "Равномерно по всем связкам",
    "Гео выровнены внутри каналов",
    "Каналы выровнены внутри гео",
    "Самый устойчивый план",
    "Адаптивный поиск",
  ]) {
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
  }
  await expect(page.getByText(/3[\s\u00a0]*217 вариантов/)).toBeVisible();
  await expect(page.getByText("Цифровая реклама", { exact: false })).toBeVisible();
  await expect(page.getByText("Наружная реклама", { exact: false })).toBeVisible();
  await expect(page.getByText("Радио", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Запустить расчет" })).toBeVisible();
  expect(calls.profileGets).toBeGreaterThan(0);
  await expectNoForbiddenCopy(page);
});

test("job starts only after the scenario page", async ({ page }) => {
  const calls = await installNewCalculationRoutes(page);
  await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);
  await expect(page.getByRole("button", { name: "Запустить расчет" })).toHaveCount(0);
  await page.getByRole("button", { name: "Продолжить с ограничениями" }).click();
  await page.getByRole("button", { name: "Запустить расчет" }).click();
  await expect(page).toHaveURL(`/calculations/${JOB_ID}/progress`);
  expect(calls.jobPosts).toBe(1);
});

test("XLS and TSV are rejected before upload", async ({ page }) => {
  const calls = await installNewCalculationRoutes(page);
  for (const fileName of ["media-plan.xls", "media-plan.tsv"]) {
    await page.goto("/calculations/new");
    await selectFile(page, fileName);
    await expect(page.getByRole("alert")).toContainText(/только.*XLSX.*CSV/i);
    await expect(page.getByRole("button", { name: "Загрузить файл" })).toBeDisabled();
  }
  expect(calls.uploadPosts).toBe(0);
});

for (const viewport of [
  { width: 375, height: 812 },
  { width: 812, height: 375 },
  { width: 1_440, height: 900 },
]) {
  test(`validation has no overflow at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await installNewCalculationRoutes(page);
    await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);
    await expect(page.getByRole("heading", { name: "Проверка файла" })).toBeVisible();
    await expectNoOverflow(page);
    await expectNoForbiddenCopy(page);
  });
}

for (const theme of ["dark", "light"] as const) {
  test(`small validation copy meets WCAG contrast in ${theme} theme`, async ({ page }) => {
    await page.setViewportSize({ width: 1_440, height: 900 });
    await setTheme(page, theme);
    await installNewCalculationRoutes(page);
    await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);
    await expect(page.getByRole("heading", { name: "Проверка файла" })).toBeVisible();

    const samples = await measureContentContrast(page, VALIDATION_CONTRAST_TARGETS);
    const coveredTargets = new Set(samples.map((sample) => sample.target));
    for (const target of VALIDATION_CONTRAST_TARGETS) {
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
      `[phase-e1b-validation-contrast:${theme}] minimum ${minimum.ratio.toFixed(3)}:1`,
      JSON.stringify(minimum),
    );
    expect(minimum.ratio, JSON.stringify(minimum, null, 2)).toBeGreaterThanOrEqual(4.5);
  });
}

for (const theme of ["dark", "light"] as const) {
  test(`campaign map desktop and tooltip screenshots in ${theme} theme`, async ({ page }) => {
    await page.setViewportSize({ width: 1_440, height: 1_000 });
    await setTheme(page, theme);
    await installNewCalculationRoutes(page);
    await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const map = page.getByRole("group", { name: "Карта рекламного бюджета текущей кампании" });
    await map.scrollIntoViewIfNeeded();
    await expect(mapMarkers(page)).toHaveCount(15);
    await expect(mapLabels(page)).toHaveCount(15);
    await expectNoOverflow(page);

    mkdirSync(GEO_REVIEW_DIRECTORY, { recursive: true });
    await page.screenshot({
      path: `${GEO_REVIEW_DIRECTORY}campaign-map-${theme}.png`,
      fullPage: false,
      animations: "disabled",
      caret: "hide",
    });

    await mapMarkers(page).first().hover();
    await expect(page.locator('[role="tooltip"]')).toBeVisible();
    await page.screenshot({
      path: `${GEO_REVIEW_DIRECTORY}campaign-map-tooltip-${theme}.png`,
      fullPage: false,
      animations: "disabled",
      caret: "hide",
    });
  });

  test(`campaign map partial coverage screenshot in ${theme} theme`, async ({ page }) => {
    await page.setViewportSize({ width: 1_440, height: 1_000 });
    await setTheme(page, theme);
    await installNewCalculationRoutes(page, { validationV2: buildPartialMapValidation() });
    await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);
    const map = page.getByRole("group", { name: "Карта рекламного бюджета текущей кампании" });
    await map.scrollIntoViewIfNeeded();
    await expect(mapMarkers(page)).toHaveCount(14);
    await expect(page.getByText("Частичное покрытие", { exact: true })).toBeVisible();
    await expectNoOverflow(page);
    mkdirSync(GEO_REVIEW_DIRECTORY, { recursive: true });
    await page.screenshot({
      path: `${GEO_REVIEW_DIRECTORY}campaign-map-partial-${theme}.png`,
      fullPage: false,
      animations: "disabled",
      caret: "hide",
    });
  });

  test(`campaign map unavailable screenshot in ${theme} theme`, async ({ page }) => {
    await page.setViewportSize({ width: 1_440, height: 1_000 });
    await setTheme(page, theme);
    await installNewCalculationRoutes(page, { validationV2: buildUnavailableMapValidation() });
    await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);
    const unavailable = page.getByText("Карта пока недоступна", { exact: true });
    await unavailable.scrollIntoViewIfNeeded();
    await expect(unavailable).toBeVisible();
    await expect(page.getByText(/Бюджет сохранен:/)).toContainText(/267,8\s+млн ₽/);
    await expectNoOverflow(page);
    mkdirSync(GEO_REVIEW_DIRECTORY, { recursive: true });
    await page.screenshot({
      path: `${GEO_REVIEW_DIRECTORY}campaign-map-unavailable-${theme}.png`,
      fullPage: false,
      animations: "disabled",
      caret: "hide",
    });
  });

  test(`campaign map mobile screenshot in ${theme} theme`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await setTheme(page, theme);
    await installNewCalculationRoutes(page);
    await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);
    const map = page.getByRole("group", { name: "Карта рекламного бюджета текущей кампании" });
    await map.scrollIntoViewIfNeeded();
    await expect(mapMarkers(page)).toHaveCount(15);
    await mapMarkers(page).last().dispatchEvent("click");
    await expect(page.locator('[role="tooltip"]')).toBeVisible();
    await expectNoOverflow(page);
    mkdirSync(GEO_REVIEW_DIRECTORY, { recursive: true });
    await page.screenshot({
      path: `${GEO_REVIEW_DIRECTORY}campaign-map-mobile-${theme}.png`,
      fullPage: false,
      animations: "disabled",
      caret: "hide",
    });
  });
}

for (const theme of ["dark", "light"] as const) {
  for (const screenshotCase of [
    { stem: "validation-limitations", payload: undefined, button: "Продолжить с ограничениями" },
    { stem: "validation-passed", payload: buildPassedValidation(), button: "Продолжить к сценариям" },
  ] as const) {
    test(`${screenshotCase.stem}-${theme}`, async ({ page }) => {
      await page.setViewportSize({ width: 1_440, height: 900 });
      await setTheme(page, theme);
      await installNewCalculationRoutes(page, { validationV2: screenshotCase.payload });
      await page.goto(`/calculations/new?validationId=${TEST_VALIDATION_ID}&step=review`);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByRole("heading", { name: "Проверка файла" })).toBeVisible();
      await expect(page.getByRole("button", { name: screenshotCase.button })).toBeVisible();
      await page.getByRole("heading", { name: "Ограничения модели" }).scrollIntoViewIfNeeded();
      await expectNoOverflow(page);
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
}
