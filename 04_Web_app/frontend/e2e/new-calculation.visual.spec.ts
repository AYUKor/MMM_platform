import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type {
  CampaignUpload,
  DecisionJob,
  ValidationIssue,
  ValidationResult,
} from "../src/entities/lifecycle/types";

const UPLOAD_ID = "upload_000000000001";
const VALIDATION_ID = "validation_000000000002";
const JOB_ID = "job_000000000003";
const CAMPAIGN_ID = "campaign_000000000004";
const REVIEW_DIRECTORY = fileURLToPath(
  new URL("../../docs/ui-review/calculations-new-v2/", import.meta.url),
);

const sourceArtifact: CampaignUpload["original_file"] = {
  artifact_id: "artifact_synthetic_source_0001",
  kind: "campaign_upload_source",
  display_name: "synthetic-media-plan.xlsx",
  media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  sha256: "a".repeat(64),
  size_bytes: 2_048,
  storage_key: "synthetic-review/source.xlsx",
};

const parsedArtifact: NonNullable<CampaignUpload["parsed_payload"]> = {
  artifact_id: "artifact_synthetic_parsed_0001",
  kind: "campaign_upload_parsed",
  display_name: "synthetic-parsed.json",
  media_type: "application/json",
  sha256: "b".repeat(64),
  size_bytes: 1_024,
  storage_key: "synthetic-review/parsed.json",
};

const normalizedArtifact: NonNullable<ValidationResult["normalized_plan"]> = {
  artifact_id: "artifact_synthetic_normalized_0001",
  kind: "campaign_plan_normalized",
  display_name: "synthetic-normalized.csv",
  media_type: "text/csv",
  sha256: "c".repeat(64),
  size_bytes: 1_536,
  storage_key: "synthetic-review/normalized.csv",
};

const flightingArtifact: NonNullable<ValidationResult["daily_flighting"]> = {
  artifact_id: "artifact_synthetic_flighting_0001",
  kind: "campaign_flighting_daily",
  display_name: "synthetic-flighting.csv",
  media_type: "text/csv",
  sha256: "d".repeat(64),
  size_bytes: 4_096,
  storage_key: "synthetic-review/flighting.csv",
};

const modelValidationArtifact: NonNullable<ValidationResult["model_validation"]> = {
  artifact_id: "artifact_synthetic_model_validation_0001",
  kind: "campaign_model_validation",
  display_name: "synthetic-model-validation.csv",
  media_type: "text/csv",
  sha256: "e".repeat(64),
  size_bytes: 768,
  storage_key: "synthetic-review/model-validation.csv",
};

const workflowArtifact: DecisionJob["workflow_config"] = {
  artifact_id: "artifact_synthetic_workflow_0001",
  kind: "workflow_config",
  display_name: "synthetic-workflow.yaml",
  media_type: "application/yaml",
  sha256: "f".repeat(64),
  size_bytes: 512,
  storage_key: "synthetic-review/workflow.yaml",
};

const parsedUpload: CampaignUpload = {
  contract_name: "campaign_upload_v1",
  schema_version: "1.0.0",
  record_origin: "synthetic_fixture",
  upload_id: UPLOAD_ID,
  actor_id: "actor_synthetic_0001",
  status: { code: "parsed", display_text: "Синтетический файл прочитан" },
  received_at_utc: "2026-01-10T10:00:00Z",
  parsed_at_utc: "2026-01-10T10:00:01Z",
  rejected_at_utc: null,
  original_file: sourceArtifact,
  parser_name: "synthetic_parser",
  parser_version: "1.0.0",
  parsed_payload: parsedArtifact,
  source_rows_n: 12,
  detected_campaigns_n: 1,
  rejection_error_id: null,
};

const receivedUpload: CampaignUpload = {
  ...parsedUpload,
  status: { code: "received", display_text: "Синтетический файл принят" },
  parsed_at_utc: null,
  parser_name: null,
  parser_version: null,
  parsed_payload: null,
  source_rows_n: null,
  detected_campaigns_n: null,
};

const campaign: ValidationResult["campaigns"][number] = {
  campaign_id: CAMPAIGN_ID,
  campaign_name: "Синтетическая кампания А",
  segments: ["Синтетический сегмент"],
  start_date: "2026-02-01",
  end_date: "2026-02-28",
  active_days: 28,
  channels: ["Синтетический канал А", "Синтетический канал Б"],
  geographies: ["Синтетический город А", "Синтетический город Б"],
  creatives: ["Синтетический креатив"],
  source_rows_n: 12,
  normalized_rows_n: 12,
  daily_rows_n: 336,
  uploaded_budget_rub: 12_345_600,
  model_input_budget_rub: 12_000_000,
  unmodeled_budget_rub: 345_600,
  daily_budget_rub: 12_000_000,
};

const syntheticWarning: ValidationIssue = {
  code: "SYNTHETIC_LIMITED_HISTORY",
  severity: "warning",
  display_text: "Для синтетического канала доступна ограниченная история расходов.",
  scope: "cell",
  recoverable: true,
  source_row_ids: [4],
  affected_cells: [
    {
      campaign_id: CAMPAIGN_ID,
      segment: "Синтетический сегмент",
      geo: "Синтетический город А",
      channel: "Синтетический канал Б",
      target: "synthetic_target",
    },
  ],
};

const syntheticBlockingIssue: ValidationIssue = {
  code: "SYNTHETIC_UNKNOWN_CHANNEL",
  severity: "blocking",
  display_text: "Синтетический канал не распознан и должен быть исправлен.",
  scope: "cell",
  recoverable: true,
  source_row_ids: [7],
  affected_cells: [
    {
      campaign_id: CAMPAIGN_ID,
      segment: "Синтетический сегмент",
      geo: "Синтетический город Б",
      channel: "Синтетический неизвестный канал",
      target: "synthetic_target",
    },
  ],
};

const validValidation: ValidationResult = {
  contract_name: "validation_result_v1",
  schema_version: "1.0.0",
  record_origin: "synthetic_fixture",
  validation_id: VALIDATION_ID,
  upload_id: UPLOAD_ID,
  status: { code: "valid", display_text: "Синтетическая кампания проверена" },
  validator_name: "synthetic_validator",
  validator_version: "1.0.0",
  started_at_utc: "2026-01-10T10:00:02Z",
  finished_at_utc: "2026-01-10T10:00:03Z",
  source_payload: parsedArtifact,
  model: {
    registry_channel: "synthetic_channel",
    registry_event_id: "event_synthetic_0001",
    package_id: "package_synthetic_0001",
    package_fingerprint: "1".repeat(64),
    package_manifest_sha256: "2".repeat(64),
    activation_status: "synthetic_restricted",
    production_blockers: ["SYNTHETIC_BLOCKER"],
  },
  normalized_plan: normalizedArtifact,
  daily_flighting: flightingArtifact,
  model_validation: modelValidationArtifact,
  campaigns: [campaign],
  totals: {
    source_rows_n: 12,
    normalized_rows_n: 12,
    daily_rows_n: 336,
    uploaded_budget_rub: 12_345_600,
    model_input_budget_rub: 12_000_000,
    unmodeled_budget_rub: 345_600,
    daily_budget_rub: 12_000_000,
    raw_to_normalized_abs_diff_rub: 0,
    normalized_to_daily_abs_diff_rub: 0,
  },
  blocking_errors: [],
  warnings: [],
  job_creation_allowed: true,
};

const runningValidation: ValidationResult = {
  ...validValidation,
  status: { code: "running", display_text: "Синтетическая проверка выполняется" },
  finished_at_utc: null,
  model: null,
  normalized_plan: null,
  daily_flighting: null,
  model_validation: null,
  campaigns: [],
  totals: null,
  warnings: [],
  blocking_errors: [],
  job_creation_allowed: false,
};

const warningValidation: ValidationResult = {
  ...validValidation,
  warnings: [syntheticWarning],
};

const invalidValidation: ValidationResult = {
  ...validValidation,
  status: { code: "invalid", display_text: "Синтетическая кампания требует исправления" },
  blocking_errors: [syntheticBlockingIssue],
  warnings: [],
  job_creation_allowed: false,
};

const queuedJob: DecisionJob = {
  contract_name: "decision_job_v1",
  schema_version: "1.0.0",
  record_origin: "synthetic_fixture",
  job_id: JOB_ID,
  idempotency_key: "job:synthetic-review-0001",
  job_type: "forecast_optimizer_report",
  created_by_actor_id: "actor_synthetic_0001",
  upload_id: UPLOAD_ID,
  validation_id: VALIDATION_ID,
  normalized_plan: normalizedArtifact,
  daily_flighting: flightingArtifact,
  workflow_config: workflowArtifact,
  model_selector: {
    mode: "registry_channel",
    registry_channel: "synthetic_channel",
    package_id: "package_synthetic_0001",
    expected_package_fingerprint: "1".repeat(64),
  },
  policies: {
    optimizer_policy_id: "synthetic_optimizer_policy",
    optimizer_policy_sha256: "3".repeat(64),
    gate_policy_version: "synthetic_gate_policy",
    business_policy_id: "synthetic_business_policy",
    business_policy_sha256: "4".repeat(64),
    business_decision_mode: "allocation_only",
  },
  sampling: {
    scenario6_attempt_budget: 2_048,
    search_posterior_draws: 32,
    final_posterior_draws: 64,
    search_seed: 11,
    final_seed: 22,
  },
  code_reference: "synthetic:review",
  status: { code: "queued", display_text: "Синтетический расчет поставлен в очередь" },
  created_at_utc: "2026-01-10T10:00:04Z",
  queued_at_utc: "2026-01-10T10:00:04Z",
  started_at_utc: null,
  cancel_requested_at_utc: null,
  finished_at_utc: null,
  attempt_number: 0,
  result_id: null,
  terminal_error_id: null,
};

interface MockApiOptions {
  parsed?: CampaignUpload;
  validation?: ValidationResult;
  uploadFailuresBeforeSuccess?: number;
  uploadPollsBeforeParsed?: number;
  uploadGetError?: boolean;
  validationFailuresBeforeSuccess?: number;
  jobFailuresBeforeSuccess?: number;
  jobResponseGate?: Promise<void>;
}

interface MockApiCalls {
  uploadPosts: number;
  uploadGets: number;
  uploadIdempotencyKeys: string[];
  validationPosts: number;
  validationGets: number;
  validationIdempotencyKeys: string[];
  jobPosts: number;
  jobBodies: unknown[];
  jobIdempotencyKeys: string[];
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

async function fulfillJson(route: Route, status: number, json: unknown) {
  await route.fulfill({ status, json });
}

async function mockNewCalculationApi(
  page: Page,
  options: MockApiOptions = {},
): Promise<MockApiCalls> {
  const calls: MockApiCalls = {
    uploadPosts: 0,
    uploadGets: 0,
    uploadIdempotencyKeys: [],
    validationPosts: 0,
    validationGets: 0,
    validationIdempotencyKeys: [],
    jobPosts: 0,
    jobBodies: [],
    jobIdempotencyKeys: [],
  };
  const parsed = clone(options.parsed ?? parsedUpload);
  const validation = clone(options.validation ?? validValidation);

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const pathname = new URL(request.url()).pathname;

    if (method === "POST" && pathname === "/api/v1/uploads") {
      calls.uploadPosts += 1;
      calls.uploadIdempotencyKeys.push(request.headers()["idempotency-key"] ?? "");
      if (calls.uploadPosts <= (options.uploadFailuresBeforeSuccess ?? 0)) {
        await fulfillJson(route, 503, {
          error: {
            code: "SYNTHETIC_UPLOAD_RESPONSE_LOST",
            display_text: "Не удалось подтвердить загрузку файла.",
          },
        });
        return;
      }
      await fulfillJson(route, 202, receivedUpload);
      return;
    }

    if (method === "GET" && pathname === `/api/v1/uploads/${UPLOAD_ID}`) {
      calls.uploadGets += 1;
      if (options.uploadGetError) {
        await fulfillJson(route, 503, {
          error: {
            code: "SYNTHETIC_UPLOAD_UNAVAILABLE",
            display_text: "Не удалось получить результат обработки файла.",
          },
        });
        return;
      }
      if (calls.uploadGets <= (options.uploadPollsBeforeParsed ?? 0)) {
        await fulfillJson(route, 200, receivedUpload);
        return;
      }
      await fulfillJson(route, 200, parsed);
      return;
    }

    if (
      method === "POST" &&
      pathname === `/api/v1/uploads/${UPLOAD_ID}/validations`
    ) {
      calls.validationPosts += 1;
      calls.validationIdempotencyKeys.push(request.headers()["idempotency-key"] ?? "");
      if (calls.validationPosts <= (options.validationFailuresBeforeSuccess ?? 0)) {
        await fulfillJson(route, 503, {
          error: {
            code: "SYNTHETIC_VALIDATION_RESPONSE_LOST",
            display_text: "Не удалось подтвердить начало проверки.",
          },
        });
        return;
      }
      await fulfillJson(route, 202, runningValidation);
      return;
    }

    if (method === "GET" && pathname === `/api/v1/validations/${VALIDATION_ID}`) {
      calls.validationGets += 1;
      await fulfillJson(route, 200, validation);
      return;
    }

    if (
      method === "POST" &&
      pathname === `/api/v1/validations/${VALIDATION_ID}/jobs`
    ) {
      calls.jobPosts += 1;
      calls.jobBodies.push(JSON.parse(request.postData() ?? "{}") as unknown);
      calls.jobIdempotencyKeys.push(request.headers()["idempotency-key"] ?? "");
      await options.jobResponseGate;
      if (calls.jobPosts <= (options.jobFailuresBeforeSuccess ?? 0)) {
        await fulfillJson(route, 503, {
          error: {
            code: "SYNTHETIC_RESPONSE_LOST",
            display_text: "Не удалось подтвердить запуск расчета.",
          },
        });
        return;
      }
      await fulfillJson(route, 202, queuedJob);
      return;
    }

    await fulfillJson(route, 404, {
      error: {
        code: "SYNTHETIC_UNEXPECTED_ROUTE",
        display_text: "Synthetic test route was not configured.",
      },
    });
  });

  return calls;
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

async function selectSyntheticFile(
  page: Page,
  name = "synthetic-media-plan.xlsx",
  sizeBytes = 2_048,
) {
  const mimeType = name.toLowerCase().endsWith(".csv")
    ? "text/csv"
    : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  await page.locator('input[type="file"]').setInputFiles({
    name,
    mimeType,
    buffer: Buffer.alloc(sizeBytes, "synthetic-review"),
  });
}

async function dropSyntheticFile(
  page: Page,
  name = "synthetic-dropped-media-plan.csv",
) {
  await page.locator('input[type="file"]').evaluate((input, fileName) => {
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(new File(["synthetic-review"], fileName, { type: "text/csv" }));
    input.closest("label")?.dispatchEvent(new DragEvent("drop", {
      bubbles: true,
      cancelable: true,
      dataTransfer,
    }));
  }, name);
}

async function expectQueryStep(page: Page, step: string) {
  await expect.poll(() => new URL(page.url()).searchParams.get("step")).toBe(step);
}

async function expectNoInternalNames(page: Page) {
  const text = await page.locator("body").innerText();
  expect(text).not.toMatch(/\bAPI\b/i);
  for (const internalName of [
    "backend",
    "Validation preview",
    "support",
    "candidate_id",
    "attempt_id",
    "posterior",
    "campaign_upload_v1",
    "validation_result_v1",
    "storage_key",
    "SYNTHETIC_LIMITED_HISTORY",
    "SYNTHETIC_UNKNOWN_CHANNEL",
    "synthetic_target",
    "/Users/",
  ]) {
    expect(text.toLowerCase()).not.toContain(internalName.toLowerCase());
  }
}

async function expectNoDocumentOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    ),
  ).toBe(false);
}

async function expectDisabledTemplateAction(page: Page) {
  const label = page.getByText("Скачать шаблон медиаплана", { exact: true }).first();
  await expect(label).toBeVisible();
  expect(
    await label.evaluate((element) => {
      const action = element.closest("button, a, [aria-disabled]");
      if (!action) return false;
      if (action instanceof HTMLButtonElement) return action.disabled;
      return action.getAttribute("aria-disabled") === "true" && !action.hasAttribute("href");
    }),
  ).toBe(true);
}

async function reachParsedUpload(page: Page) {
  await page.goto("/calculations/new");
  await selectSyntheticFile(page);
  await page.getByRole("button", { name: "Загрузить файл", exact: true }).click();
  await expect(page.getByText("Файл успешно прочитан", { exact: true })).toBeVisible();
  await expectQueryStep(page, "upload-result");
}

async function reachReview(
  page: Page,
  expectedStatus: string,
) {
  await reachParsedUpload(page);
  await page.getByRole("button", { name: "Продолжить к проверке", exact: true }).click();
  await expect(page.getByRole("heading", { name: expectedStatus, exact: true })).toBeVisible();
  await expectQueryStep(page, "review");
}

const scenarioTitles = [
  "Как загружено",
  "Равномерно по всем связкам",
  "Гео выровнены внутри каналов",
  "Каналы выровнены внутри гео",
  "Самый устойчивый план",
  "Адаптивный поиск",
] as const;

async function expectScenarioScreen(page: Page) {
  for (const title of scenarioTitles) {
    await expect(
      page.getByRole("heading", { name: new RegExp(`${title}$`) }),
    ).toBeVisible();
  }
  await expect(page.getByText("S5 — сначала устойчивость", { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      "S6 — поиск эффективности с обязательной проверкой устойчивости",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByText("Общий бюджет", { exact: true })).toBeVisible();
  await expect(page.getByText("Даты", { exact: true })).toBeVisible();
  await expect(page.getByText("Исходные каналы", { exact: true })).toBeVisible();
  await expect(page.getByText("Исходные гео", { exact: true })).toBeVisible();
  await expect(page.getByText("Исходные связки гео × канал", { exact: true })).toBeVisible();

  const text = await page.locator("body").innerText();
  expect(text).not.toContain("150");
  expect(text).not.toContain("2048");
  expect(text).not.toContain("2 048");
}

async function captureExactViewport(page: Page, fileName: string) {
  mkdirSync(REVIEW_DIRECTORY, { recursive: true });
  await page.evaluate(() => document.fonts.ready);
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

test("1. empty upload screen is controlled", async ({ page }) => {
  const calls = await mockNewCalculationApi(page);
  await page.goto("/calculations/new");

  await expect(page.getByRole("heading", { name: "Новый расчет", exact: true })).toBeVisible();
  await expect(page.getByText("Один файл = одна кампания", { exact: true })).toBeVisible();
  await expect(page.getByText("XLSX или CSV", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Загрузить файл", exact: true })).toBeDisabled();
  await expectDisabledTemplateAction(page);
  await expect(page.locator('nav a[aria-current="page"]')).toHaveCount(1);
  await expect(page.getByRole("link", { name: "Новый расчёт", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(calls.uploadPosts).toBe(0);
  expect(calls.validationPosts).toBe(0);
  expect(calls.jobPosts).toBe(0);
  await expectNoInternalNames(page);
});

test("2. selected valid file is parsed before validation", async ({ page }) => {
  const calls = await mockNewCalculationApi(page);
  await page.goto("/calculations/new");
  await selectSyntheticFile(page);

  await expect(page.getByText("synthetic-media-plan.xlsx", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Заменить файл", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Удалить", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Загрузить файл", exact: true }).click();

  await expect(page.getByText("Файл успешно прочитан", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Строк", { exact: true }).locator("..").getByText("12", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Кампаний", { exact: true }).locator("..").getByText("1", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Продолжить к проверке", exact: true })).toBeVisible();
  expect(calls.uploadPosts).toBe(1);
  expect(calls.validationPosts).toBe(0);
  expect(calls.jobPosts).toBe(0);
  await expectQueryStep(page, "upload-result");

  await page.reload();
  await expect(page.getByText("Файл успешно прочитан", { exact: true })).toBeVisible();
  await expectQueryStep(page, "upload-result");
  expect(calls.uploadPosts).toBe(1);
  await expectNoInternalNames(page);
});

test("2a. drag and drop selects a valid campaign file", async ({ page }) => {
  const calls = await mockNewCalculationApi(page);
  await page.goto("/calculations/new");

  await dropSyntheticFile(page);

  await expect(page.getByText("synthetic-dropped-media-plan.csv", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Загрузить файл", exact: true })).toBeEnabled();
  expect(calls.uploadPosts).toBe(0);
});

test("2b. received upload stays in a controlled loading state until parsed", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, { uploadPollsBeforeParsed: 1 });
  await page.goto("/calculations/new");
  await selectSyntheticFile(page);
  await page.getByRole("button", { name: "Загрузить файл", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Читаем файл", exact: true })).toBeVisible();
  await expect(page.getByText("Файл успешно прочитан", { exact: true })).toBeVisible();
  expect(calls.uploadGets).toBeGreaterThanOrEqual(2);
});

test("2c. upload polling error replaces loading with a recovery action", async ({ page }) => {
  await mockNewCalculationApi(page, { uploadGetError: true });
  await page.goto(`/calculations/new?uploadId=${UPLOAD_ID}&step=upload-result`);

  await expect(page.getByRole("alert")).toContainText("Не удалось получить результат обработки файла.");
  await expect(page.getByRole("heading", { name: "Читаем файл", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Загрузить другой файл", exact: true })).toBeVisible();
});

test("2d. replacing a file resets the native picker for the same file name", async ({ page }) => {
  await mockNewCalculationApi(page);
  await page.goto("/calculations/new");
  await selectSyntheticFile(page, "same-name-plan.xlsx", 2_048);
  await expect(page.getByText("2 КБ", { exact: true })).toBeVisible();

  const chooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Заменить файл", exact: true }).click();
  const chooser = await chooserPromise;
  await expect(page.locator('input[type="file"]')).toHaveValue("");
  await chooser.setFiles({
    name: "same-name-plan.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.alloc(4_096, "synthetic-review-replacement"),
  });

  await expect(page.getByText("same-name-plan.xlsx", { exact: true })).toBeVisible();
  await expect(page.getByText("4 КБ", { exact: true })).toBeVisible();
});

test("2e. retrying upload reuses the selected file idempotency key", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, { uploadFailuresBeforeSuccess: 1 });
  await page.goto("/calculations/new");
  await selectSyntheticFile(page);
  const uploadButton = page.getByRole("button", { name: "Загрузить файл", exact: true });

  await uploadButton.click();
  await expect(page.getByRole("alert")).toContainText("Не удалось подтвердить загрузку файла.");
  await uploadButton.click();
  await expect(page.getByText("Файл успешно прочитан", { exact: true })).toBeVisible();

  expect(calls.uploadPosts).toBe(2);
  expect(calls.uploadIdempotencyKeys[0]).not.toBe("");
  expect(calls.uploadIdempotencyKeys[1]).toBe(calls.uploadIdempotencyKeys[0]);
});

test("3. multiple campaigns are blocked before validation", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, {
    parsed: { ...parsedUpload, detected_campaigns_n: 2 },
  });
  await page.goto("/calculations/new");
  await selectSyntheticFile(page);
  await page.getByRole("button", { name: "Загрузить файл", exact: true }).click();

  await expect(
    page.getByRole("heading", { name: "В файле обнаружено несколько кампаний", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/каждую кампанию.*отдельн/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Загрузить другой файл", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Продолжить к проверке", exact: true })).toHaveCount(0);
  expect(calls.validationPosts).toBe(0);
  expect(calls.jobPosts).toBe(0);
  await expectNoInternalNames(page);
});

test("3a. a parsed file without a campaign has accurate blocked copy", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, {
    parsed: { ...parsedUpload, detected_campaigns_n: 0 },
  });
  await page.goto("/calculations/new");
  await selectSyntheticFile(page);
  await page.getByRole("button", { name: "Загрузить файл", exact: true }).click();

  await expect(
    page.getByRole("heading", { name: "Кампания в файле не обнаружена", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/проверьте обязательные поля/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Продолжить к проверке", exact: true })).toHaveCount(0);
  expect(calls.validationPosts).toBe(0);
});

test("4. valid campaign without warnings reaches ready review", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, { validation: validValidation });
  await reachReview(page, "Кампания готова к расчету");

  await expect(page.getByText("Синтетическая кампания А", { exact: true })).toBeVisible();
  await expect(page.getByText("Синтетический сегмент", { exact: true })).toBeVisible();
  await expect(page.getByText(/12,3[\s\u00a0]*млн[\s\u00a0]*₽/)).toBeVisible();
  await expect(page.getByText("Бюджет по каналам", { exact: true })).toBeVisible();
  await expect(page.getByText("Бюджет по географии", { exact: true })).toBeVisible();
  await expect(page.getByText("Активность каналов", { exact: true })).toBeVisible();
  await expect(page.getByText("География кампании", { exact: true })).toBeVisible();
  await expect(page.getByText(/после подключения/i).first()).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Продолжить к сценариям", exact: true }),
  ).toBeVisible();
  expect(calls.validationPosts).toBe(1);
  expect(calls.jobPosts).toBe(0);
  await expectNoInternalNames(page);
});

test("4a. retrying validation reuses the upload-scoped idempotency key", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, { validationFailuresBeforeSuccess: 1 });
  await reachParsedUpload(page);
  const validationButton = page.getByRole("button", {
    name: "Продолжить к проверке",
    exact: true,
  });

  await validationButton.click();
  await expect(page.getByRole("alert")).toContainText("Не удалось подтвердить начало проверки.");
  await validationButton.click();
  await expect(
    page.getByRole("heading", { name: "Кампания готова к расчету", exact: true }),
  ).toBeVisible();

  expect(calls.validationPosts).toBe(2);
  expect(calls.validationIdempotencyKeys).toEqual([
    `validation:${UPLOAD_ID}`,
    `validation:${UPLOAD_ID}`,
  ]);
});

test("5. valid campaign with warnings stays calculable", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, { validation: warningValidation });
  await reachReview(page, "Кампанию можно рассчитать, но есть замечания");

  await expect(page.getByText("Что обнаружено", { exact: true })).toBeVisible();
  await expect(page.getByText(syntheticWarning.display_text, { exact: true })).toBeVisible();
  await expect(page.getByText(/Гео: Синтетический город А/)).toBeVisible();
  await expect(page.getByText(/Канал: Синтетический канал Б/)).toBeVisible();
  await expect(
    page.getByText(/Связка гео × канал: Синтетический город А × Синтетический канал Б/),
  ).toBeVisible();
  await expect(page.getByText(/Расчет разрешен:\s*да/i)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Продолжить с замечаниями", exact: true }),
  ).toBeVisible();
  expect(calls.jobPosts).toBe(0);
  await expectNoInternalNames(page);
});

test("6. invalid campaign is blocked", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, { validation: invalidValidation });
  await reachReview(page, "Кампанию нужно исправить");

  await expect(page.getByText(syntheticBlockingIssue.display_text, { exact: true })).toBeVisible();
  await expect(page.getByText(/Расчет разрешен:\s*нет/i)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Загрузить исправленный файл", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Продолжить.*сценар/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Запустить расчет", exact: true })).toHaveCount(0);
  expect(calls.jobPosts).toBe(0);
  await expectNoInternalNames(page);
});

test("7. scenario screen contains all six approved scenarios", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, { validation: validValidation });
  await page.goto(
    `/calculations/new?validationId=${VALIDATION_ID}&step=scenarios`,
  );

  await expectQueryStep(page, "scenarios");
  await expectScenarioScreen(page);
  await expect(
    page.getByRole("button", { name: "Назад к проверке", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Запустить расчет", exact: true })).toBeVisible();
  expect(calls.jobPosts).toBe(0);
  await expectNoInternalNames(page);
});

test("8. a job can only be created from the scenario screen", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, { validation: validValidation });
  await page.goto(
    `/calculations/new?validationId=${VALIDATION_ID}&step=review`,
  );
  await expect(
    page.getByRole("heading", { name: "Кампания готова к расчету", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Запустить расчет", exact: true })).toHaveCount(0);
  expect(calls.jobPosts).toBe(0);

  await page.getByRole("button", { name: "Продолжить к сценариям", exact: true }).click();
  await expectQueryStep(page, "scenarios");
  expect(calls.jobPosts).toBe(0);
  await page.getByRole("button", { name: "Запустить расчет", exact: true }).click();

  await expect(page).toHaveURL(`/calculations/${JOB_ID}/progress`);
  expect(calls.jobPosts).toBe(1);
  expect(calls.jobBodies).toEqual([{}]);
  expect(calls.jobIdempotencyKeys).toEqual([`job:${VALIDATION_ID}`]);
});

test("8a. retrying an ambiguous job response reuses the same idempotency key", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, {
    validation: validValidation,
    jobFailuresBeforeSuccess: 1,
  });
  await page.goto(`/calculations/new?validationId=${VALIDATION_ID}&step=scenarios`);
  const start = page.getByRole("button", { name: "Запустить расчет", exact: true });
  await expect(start).toBeVisible();

  await start.click();
  await expect(page.getByRole("alert")).toContainText("Не удалось подтвердить запуск расчета.");
  await expect(start).toBeEnabled();
  await start.click();

  await expect(page).toHaveURL(`/calculations/${JOB_ID}/progress`);
  expect(calls.jobPosts).toBe(2);
  expect(calls.jobIdempotencyKeys).toEqual([
    `job:${VALIDATION_ID}`,
    `job:${VALIDATION_ID}`,
  ]);
});

test("8b. a late action response does not pull the user back into an old flow", async ({ page }) => {
  let releaseJobResponse: () => void = () => undefined;
  const jobResponseGate = new Promise<void>((resolve) => {
    releaseJobResponse = resolve;
  });
  const calls = await mockNewCalculationApi(page, {
    validation: validValidation,
    jobResponseGate,
  });
  await page.goto(`/calculations/new?validationId=${VALIDATION_ID}&step=scenarios`);
  await page.getByRole("button", { name: "Запустить расчет", exact: true }).click();
  await expect.poll(() => calls.jobPosts).toBe(1);

  await page.getByRole("link", { name: "Новый расчёт", exact: true }).click();
  await expect(page).toHaveURL("/calculations/new");
  await expect(page.getByRole("heading", { name: "Загрузите медиаплан", exact: true })).toBeVisible();
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname === `/api/v1/validations/${VALIDATION_ID}/jobs`
  ));
  releaseJobResponse();
  await responsePromise;
  await page.waitForTimeout(50);

  await expect(page).toHaveURL("/calculations/new");
  await page.evaluate((nextUrl) => {
    window.history.pushState({}, "", nextUrl);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, `/calculations/new?validationId=${VALIDATION_ID}&step=scenarios`);
  await expect(
    page.getByRole("button", { name: "Запустить расчет", exact: true }),
  ).toBeEnabled();
});

test("9. refresh restores review and scenario state", async ({ page }) => {
  const calls = await mockNewCalculationApi(page, { validation: validValidation });
  await page.goto(
    `/calculations/new?validationId=${VALIDATION_ID}&step=review`,
  );
  await expect(
    page.getByRole("heading", { name: "Кампания готова к расчету", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Кампания готова к расчету", exact: true }),
  ).toBeVisible();
  await expectQueryStep(page, "review");

  await page.getByRole("button", { name: "Продолжить к сценариям", exact: true }).click();
  await expectQueryStep(page, "scenarios");
  await page.reload();
  await expectScenarioScreen(page);
  await expectQueryStep(page, "scenarios");

  expect(calls.validationGets).toBeGreaterThanOrEqual(3);
  expect(calls.uploadPosts).toBe(0);
  expect(calls.validationPosts).toBe(0);
  expect(calls.jobPosts).toBe(0);
  await expectNoInternalNames(page);
});

test("9a. URL navigation never exposes or submits a stale validation", async ({ page }) => {
  const alternateValidationId = "validation_00000000000a";
  const alternateJobId = "job_00000000000b";
  const alternateValidation: ValidationResult = {
    ...validValidation,
    validation_id: alternateValidationId,
  };
  const alternateJob: DecisionJob = {
    ...queuedJob,
    job_id: alternateJobId,
    validation_id: alternateValidationId,
  };
  let releaseAlternateValidation: () => void = () => undefined;
  const alternateValidationGate = new Promise<void>((resolve) => {
    releaseAlternateValidation = resolve;
  });
  const submittedValidationPaths: string[] = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const pathname = new URL(request.url()).pathname;

    if (method === "GET" && pathname === `/api/v1/validations/${VALIDATION_ID}`) {
      await fulfillJson(route, 200, validValidation);
      return;
    }
    if (method === "GET" && pathname === `/api/v1/validations/${alternateValidationId}`) {
      await alternateValidationGate;
      await fulfillJson(route, 200, alternateValidation);
      return;
    }
    if (method === "GET" && pathname === `/api/v1/uploads/${UPLOAD_ID}`) {
      await fulfillJson(route, 200, parsedUpload);
      return;
    }
    if (method === "POST" && pathname === `/api/v1/validations/${alternateValidationId}/jobs`) {
      submittedValidationPaths.push(pathname);
      await fulfillJson(route, 202, alternateJob);
      return;
    }
    await fulfillJson(route, 404, {
      error: { code: "SYNTHETIC_UNEXPECTED_ROUTE", display_text: "Маршрут теста не настроен." },
    });
  });

  await page.goto(`/calculations/new?validationId=${VALIDATION_ID}&step=scenarios`);
  await expect(page.getByRole("button", { name: "Запустить расчет", exact: true })).toBeVisible();

  await page.evaluate((nextUrl) => {
    window.history.pushState({}, "", nextUrl);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, `/calculations/new?validationId=${alternateValidationId}&step=scenarios`);
  await expect.poll(() => new URL(page.url()).searchParams.get("validationId"))
    .toBe(alternateValidationId);
  await expect(page.getByRole("button", { name: "Запустить расчет", exact: true })).toHaveCount(0);

  releaseAlternateValidation();
  const start = page.getByRole("button", { name: "Запустить расчет", exact: true });
  await expect(start).toBeVisible();
  await start.click();

  await expect(page).toHaveURL(`/calculations/${alternateJobId}/progress`);
  expect(submittedValidationPaths).toEqual([
    `/api/v1/validations/${alternateValidationId}/jobs`,
  ]);
});

test("10. XLS and TSV files are rejected before upload", async ({ page }) => {
  const calls = await mockNewCalculationApi(page);

  for (const fileName of ["synthetic-media-plan.xls", "synthetic-media-plan.tsv"]) {
    await page.goto("/calculations/new");
    const input = page.locator('input[type="file"]');
    await expect(input).toHaveAttribute("accept", /\.xlsx.*\.csv|\.csv.*\.xlsx/i);
    await selectSyntheticFile(page, fileName);
    await expect(page.getByRole("alert")).toContainText(/только.*XLSX.*CSV/i);
    await expect(page.getByRole("button", { name: "Загрузить файл", exact: true })).toBeDisabled();
  }

  expect(calls.uploadPosts).toBe(0);
  expect(calls.validationPosts).toBe(0);
  expect(calls.jobPosts).toBe(0);
  await expectNoInternalNames(page);
});

test("11. desktop, mobile and landscape layouts do not overflow", async ({ page }) => {
  const longUnbrokenValue = "СинтетическоеЗначениеБезПробеловДляПроверкиПереноса".repeat(5);
  const longCampaign: ValidationResult["campaigns"][number] = {
    ...campaign,
    campaign_name: longUnbrokenValue,
    segments: [longUnbrokenValue],
    channels: [longUnbrokenValue],
    geographies: [longUnbrokenValue],
  };
  const longWarning: ValidationIssue = {
    ...syntheticWarning,
    affected_cells: [{
      ...syntheticWarning.affected_cells[0],
      segment: longUnbrokenValue,
      geo: longUnbrokenValue,
      channel: longUnbrokenValue,
    }],
  };
  const longStringValidation: ValidationResult = {
    ...warningValidation,
    campaigns: [longCampaign],
    warnings: [longWarning],
  };
  await mockNewCalculationApi(page, { validation: longStringValidation });
  await page.emulateMedia({ reducedMotion: "reduce" });

  for (const viewport of [
    { width: 375, height: 812 },
    { width: 812, height: 375 },
    { width: 1_024, height: 768 },
    { width: 1_440, height: 900 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/calculations/new");
    await expect(page.getByRole("heading", { name: "Новый расчет", exact: true })).toBeVisible();
    await expectNoDocumentOverflow(page);

    await page.goto(`/calculations/new?validationId=${VALIDATION_ID}&step=review`);
    await expect(
      page.getByRole("heading", { name: "Кампанию можно рассчитать, но есть замечания", exact: true }),
    ).toBeVisible();
    await expectNoDocumentOverflow(page);

    await page.goto(`/calculations/new?validationId=${VALIDATION_ID}&step=scenarios`);
    await expectScenarioScreen(page);
    await expectNoDocumentOverflow(page);
    await expect(page.getByRole("button", { name: "Запустить расчет", exact: true })).toBeVisible();
  }
});

for (const theme of ["dark", "light"] as const) {
  test(`visual review is exact 1440x900 in ${theme} theme`, async ({ page }) => {
    await page.setViewportSize({ width: 1_440, height: 900 });
    await setTheme(page, theme);
    await mockNewCalculationApi(page, { validation: warningValidation });
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.goto("/calculations/new");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expectNoDocumentOverflow(page);
    await expectNoInternalNames(page);
    await captureExactViewport(page, `01-upload-empty-${theme}.png`);

    await selectSyntheticFile(page);
    await expect(page.getByText("synthetic-media-plan.xlsx", { exact: true })).toBeVisible();
    await expectNoDocumentOverflow(page);
    await captureExactViewport(page, `02-upload-selected-${theme}.png`);

    await page.goto(
      `/calculations/new?validationId=${VALIDATION_ID}&step=review`,
    );
    await expect(
      page.getByRole("heading", {
        name: "Кампанию можно рассчитать, но есть замечания",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByText("Демонстрационные данные", { exact: true }).first()).toBeVisible();
    await expectNoDocumentOverflow(page);
    await expectNoInternalNames(page);
    await captureExactViewport(page, `03-validation-warning-${theme}.png`);

    await page.goto(
      `/calculations/new?validationId=${VALIDATION_ID}&step=scenarios`,
    );
    await expectScenarioScreen(page);
    await expect(page.getByText("Демонстрационные данные", { exact: true }).first()).toBeVisible();
    await expectNoDocumentOverflow(page);
    await expectNoInternalNames(page);
    await captureExactViewport(page, `04-scenarios-${theme}.png`);

    expect(consoleErrors).toEqual([]);
  });
}
