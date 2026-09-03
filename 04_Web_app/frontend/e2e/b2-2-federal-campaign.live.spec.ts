import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createServer, type ViteDevServer } from "vite";
import type { ValidationResultV2 } from "../src/shared/api/generated/validation-result-v2";
import {
  analyzeValidationTrace,
  responseValidationId,
  type ValidationTraceEvidence,
  type ValidationTraceRuntime,
} from "../src/test/validationAcceptanceTrace";

const LIVE_ENABLED = process.env.B2_2_LIVE === "true";
const EMAIL = process.env.B2_2_LIVE_EMAIL ?? "";
const PASSWORD = process.env.B2_2_LIVE_PASSWORD ?? "";

const FEDERAL_BUDGET_RUB = 100_000_000;
const SUPPORTED_FLIGHT_DATE = "2026-09-01";
const LIVE_BUSINESS_DIRECTION = "ТС5/Онлайн";
const DECLARED_GEO_COUNT = 211;
const EXPECTED_GEO_COUNT = 175;
const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

interface CapturedValidation {
  validation: ValidationResultV2;
  evidence: ValidationTraceEvidence & { network: Record<string, unknown> };
}

interface BrowserDiagnostic {
  kind: "console" | "pageerror";
  type: string;
  text: string;
  location?: { url: string; lineNumber: number; columnNumber: number };
  stack?: string | null;
}

const diagnosticsByPage = new WeakMap<Page, BrowserDiagnostic[]>();
let parserServer: ViteDevServer | null = null;
let traceRuntime: ValidationTraceRuntime | null = null;

async function loadTraceRuntime(): Promise<void> {
  parserServer = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    logLevel: "silent",
  });
  const parserModule = await parserServer.ssrLoadModule("/src/shared/api/business-semantics-client.ts") as {
    parseValidationViewV2: ValidationTraceRuntime["parseValidationViewV2"];
  };
  const projectionModule = await parserServer.ssrLoadModule("/src/features/geo-budget-map/geoBudgetMapModel.ts") as {
    adaptValidationGeoBudget: ValidationTraceRuntime["adaptValidationGeoBudget"];
  };
  traceRuntime = {
    parseValidationViewV2: parserModule.parseValidationViewV2,
    adaptValidationGeoBudget: projectionModule.adaptValidationGeoBudget,
  };
}

function attachmentSlug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "validation";
}

function responseHeadersForEvidence(headers: Record<string, string>): Record<string, string | null> {
  const selected = [
    "content-type",
    "cache-control",
    "etag",
    "last-modified",
    "age",
    "via",
    "x-cache",
    "server",
  ];
  return Object.fromEntries(selected.map((name) => [name, headers[name] ?? null]));
}

async function attachJson(name: string, value: unknown): Promise<void> {
  await test.info().attach(name, {
    body: Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf-8"),
    contentType: "application/json",
  });
}

async function captureValidationReview(page: Page, scenario: string): Promise<CapturedValidation> {
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === "GET"
    && /\/api\/v1\/validations\/validation_[a-z0-9]+\/view-v2$/.test(new URL(response.url()).pathname)
  ), { timeout: 120_000 });

  await page.getByRole("button", { name: "Продолжить к проверке" }).click();
  const response = await responsePromise;
  const responseId = responseValidationId(response.url());
  if (responseId) {
    await page.waitForURL((url) => url.searchParams.get("validationId") === responseId, {
      timeout: 10_000,
    }).catch(() => undefined);
  }

  const rawBody = await response.text();
  const rawBodyBytes = Buffer.byteLength(rawBody, "utf-8");
  const rawBodySha256 = createHash("sha256").update(rawBody, "utf-8").digest("hex");
  if (!traceRuntime) throw new Error("Validation trace runtime is not initialized.");
  const analysis = analyzeValidationTrace({
    scenario,
    capturedAtUtc: new Date().toISOString(),
    method: response.request().method(),
    responseUrl: response.url(),
    httpStatus: response.status(),
    rawBody,
    rawBodySha256,
    rawBodyBytes,
    browserRouteUrl: page.url(),
  }, traceRuntime);
  const evidence = {
    ...analysis.evidence,
    network: {
      resource_type: response.request().resourceType(),
      from_service_worker: response.fromServiceWorker(),
      headers: responseHeadersForEvidence(response.headers()),
    },
  };
  const slug = attachmentSlug(scenario);
  await attachJson(`${slug}-network-contract-trace.json`, {
    ...evidence,
    dom_assertion: { status: "pending", assertions: [] },
  });

  if (!analysis.ok) {
    await test.info().attach(`${slug}-failure.png`, {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
    throw new Error(`Validation acceptance trace failed: ${JSON.stringify(analysis.evidence.failure)}`);
  }
  return { validation: analysis.validation, evidence };
}

async function attachDomPass(
  scenario: string,
  captured: CapturedValidation,
  assertions: readonly string[],
): Promise<void> {
  await attachJson(`${attachmentSlug(scenario)}-complete-trace.json`, {
    ...captured.evidence,
    dom_assertion: { status: "pass", assertions },
  });
}

async function validateLivePlan(
  page: Page,
  scenario: string,
  filename: string,
  rows: readonly string[],
): Promise<CapturedValidation> {
  await page.goto("/calculations/new");
  const content = [
    "campaign_name,segment,geo,channel,start_date,end_date,budget_rub",
    ...rows,
    "",
  ].join("\n");
  await page.locator('input[type="file"]').setInputFiles({
    name: filename,
    mimeType: "text/csv",
    buffer: Buffer.from(content, "utf-8"),
  });
  await page.getByRole("button", { name: "Загрузить файл" }).click();
  await expect(page.getByText("Файл успешно прочитан", { exact: true })).toBeVisible({
    timeout: 30_000,
  });
  return captureValidationReview(page, scenario);
}

async function runValidatedPlanToResult(page: Page) {
  const continueButton = page.getByRole("button", { name: /Продолжить (к сценариям|с ограничениями)/ });
  await continueButton.click();
  await expect(page.getByRole("button", { name: "Запустить расчет" })).toBeVisible();
  await page.getByRole("button", { name: "Запустить расчет" }).click();
  await expect(page).toHaveURL(/\/calculations\/job_[a-z0-9]+\/progress/);
  const jobId = new URL(page.url()).pathname.split("/")[2];
  expect(jobId).toMatch(/^job_[a-z0-9]+$/);
  const resultLink = page.getByRole("link", { name: "Открыть результат" });
  await expect(resultLink).toBeVisible({ timeout: 2_100_000 });
  await resultLink.click();
  await expect(page).toHaveURL(new RegExp(`/calculations/${jobId}/result`));
  await expect(page.getByRole("heading", { name: "Оборот и ROAS" })).toBeVisible({
    timeout: 120_000,
  });
  return jobId;
}

test.use({ trace: "retain-on-failure", screenshot: "only-on-failure", video: "off" });

test.describe("B2.2 live federal campaign acceptance", () => {
  test.skip(!LIVE_ENABLED, "Set B2_2_LIVE=true and provide B2_2_LIVE_EMAIL/PASSWORD.");

  test.beforeAll(async () => {
    await loadTraceRuntime();
  });

  test.afterAll(async () => {
    traceRuntime = null;
    await parserServer?.close();
    parserServer = null;
  });

  test.beforeEach(async ({ page }) => {
    const diagnostics: BrowserDiagnostic[] = [];
    diagnosticsByPage.set(page, diagnostics);
    page.on("console", (message) => diagnostics.push({
      kind: "console",
      type: message.type(),
      text: message.text(),
      location: message.location(),
    }));
    page.on("pageerror", (error) => diagnostics.push({
      kind: "pageerror",
      type: error.name,
      text: error.message,
      stack: error.stack ?? null,
    }));
  });

  test.afterEach(async ({ page }, testInfo) => {
    await testInfo.attach("browser-diagnostics.json", {
      body: Buffer.from(`${JSON.stringify({
        final_url: page.url(),
        diagnostics: diagnosticsByPage.get(page) ?? [],
      }, null, 2)}\n`, "utf-8"),
      contentType: "application/json",
    });
  });

  test("runs upload through result and report without route interception", async ({ page }) => {
    test.setTimeout(2_400_000);
    expect(EMAIL).not.toBe("");
    expect(PASSWORD).not.toBe("");

    await page.goto("/login");
    if (new URL(page.url()).pathname === "/login") {
      await page.getByLabel("Email").fill(EMAIL);
      await page.getByLabel("Пароль").fill(PASSWORD);
      await page.getByRole("button", { name: "Войти" }).click();
      await expect(page).not.toHaveURL(/\/login/);
    }

    await page.goto("/calculations/new");
    await expect(page.getByRole("heading", { name: "Новый расчет", exact: true })).toBeVisible();

    for (const name of ["Скачать шаблон", "Скачать словарь"] as const) {
      const downloadEvent = page.waitForEvent("download");
      await page.getByRole("link", { name, exact: true }).click();
      const download = await downloadEvent;
      expect(await download.failure()).toBeNull();
      expect(download.suggestedFilename()).toMatch(/\.xlsx$/i);
      const path = await download.path();
      expect(path).not.toBeNull();
      const bytes = await readFile(path!);
      expect(bytes.byteLength).toBeGreaterThan(0);
      expect([...bytes.subarray(0, 2)]).toEqual([0x50, 0x4b]);
    }

    const content = [
      "campaign_name,segment,geo,channel,start_date,end_date,budget_rub",
      `B2.2 federal live,${LIVE_BUSINESS_DIRECTION},РФ,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},${FEDERAL_BUDGET_RUB}`,
      "",
    ].join("\n");
    await page.locator('input[type="file"]').setInputFiles({
      name: "b2-2-federal-live.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(content, "utf-8"),
    });
    await page.getByRole("button", { name: "Загрузить файл" }).click();
    await expect(page.getByText("Файл успешно прочитан", { exact: true })).toBeVisible({
      timeout: 30_000,
    });
    const federalCaptured = await captureValidationReview(page, "federal-ts5-full");
    const validation = federalCaptured.validation;
    expect(validation.federal_allocation).toMatchObject({
      status: "available",
      source_rows_count: 1,
      source_budget_rub: FEDERAL_BUDGET_RUB,
      geo_count: EXPECTED_GEO_COUNT,
      declared_geo_count: DECLARED_GEO_COUNT,
      ready_geo_count: EXPECTED_GEO_COUNT,
      excluded_geo_count: DECLARED_GEO_COUNT - EXPECTED_GEO_COUNT,
      lmax: 14,
      required_period_start: "2026-09-01",
      required_period_end: "2026-09-15",
      mixed_local_overlap: false,
    });
    expect(
      Math.abs(validation.federal_allocation.allocated_budget_rub - FEDERAL_BUDGET_RUB),
    ).toBeLessThanOrEqual(0.01);
    expect(Math.abs(validation.federal_allocation.difference_rub)).toBeLessThanOrEqual(0.01);
    expect(validation.map_coverage).toMatchObject({
      status: "available",
      located_geographies_n: EXPECTED_GEO_COUNT,
      unlocated_geographies_n: 0,
      unlocated_budget_rub: 0,
    });
    expect(validation.geo_points).toHaveLength(EXPECTED_GEO_COUNT);

    const federal = page.getByRole("heading", { name: "Обнаружено федеральное размещение" })
      .locator("xpath=ancestor::section[1]");
    await expect(federal).toBeVisible();
    await expect(federal).toContainText("Распределено полностью · 0 ₽");
    await expect(federal).toContainText(String(EXPECTED_GEO_COUNT));
    const map = page.getByRole("group", { name: "Карта рекламного бюджета текущей кампании" });
    await expect(map.locator("[data-map-marker]")).toHaveCount(EXPECTED_GEO_COUNT);
    await expect(page.getByText("Данные результата имеют неподдерживаемый формат.", { exact: true })).toHaveCount(0);
    await attachDomPass("federal-ts5-full", federalCaptured, [
      "federal summary visible",
      "175 map markers visible",
      "unsupported-format message absent",
    ]);

    const continueButton = page.getByRole("button", { name: /Продолжить (к сценариям|с ограничениями)/ });
    await continueButton.click();
    await expect(page.getByRole("button", { name: "Запустить расчет" })).toBeVisible();
    await page.getByRole("button", { name: "Запустить расчет" }).click();
    await expect(page).toHaveURL(/\/calculations\/job_[a-z0-9]+\/progress/);
    const jobId = new URL(page.url()).pathname.split("/")[2];
    expect(jobId).toMatch(/^job_[a-z0-9]+$/);

    const resultLink = page.getByRole("link", { name: "Открыть результат" });
    await expect(resultLink).toBeVisible({ timeout: 2_100_000 });
    await resultLink.click();
    await expect(page).toHaveURL(new RegExp(`/calculations/${jobId}/result`));
    await expect(page.getByRole("heading", { name: "Оборот и ROAS" })).toBeVisible({
      timeout: 120_000,
    });

    await page.getByRole("tab", { name: "Медиаплан" }).click();
    await page.getByLabel("Сценарий").selectOption("S01");
    await expect(page.getByRole("heading", { name: "План согласован с результатом" })).toBeVisible({
      timeout: 120_000,
    });
    const mediaRows = page.locator("tbody tr");
    expect(await mediaRows.count()).toBeGreaterThan(0);
    await expect(page.locator("body")).not.toContainText("РФ");

    await page.getByRole("tab", { name: "Отчет" }).click();
    const reportLink = page.getByRole("link", { name: "Скачать отчет" });
    await expect(reportLink).toBeVisible({ timeout: 120_000 });
    const reportDownloadEvent = page.waitForEvent("download");
    await reportLink.click();
    const reportDownload = await reportDownloadEvent;
    expect(await reportDownload.failure()).toBeNull();
    expect(reportDownload.suggestedFilename()).toMatch(/\.xlsx$/i);
    const reportPath = await reportDownload.path();
    expect(reportPath).not.toBeNull();
    const reportBytes = await readFile(reportPath!);
    expect([...reportBytes.subarray(0, 2)]).toEqual([0x50, 0x4b]);
    const verified = await page.request.get(reportDownload.url());
    expect(verified.status()).toBe(200);
    expect(verified.headers()["content-type"]).toContain(XLSX_MIME);

    await page.goto("/calculations/new");
    const tsxContent = [
      "campaign_name,segment,geo,channel,start_date,end_date,budget_rub",
      `B2.2 TSX federal live,ТСХ/Онлайн,РФ,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},${FEDERAL_BUDGET_RUB}`,
      "",
    ].join("\n");
    await page.locator('input[type="file"]').setInputFiles({
      name: "b2-2-tsx-federal-live.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(tsxContent, "utf-8"),
    });
    await page.getByRole("button", { name: "Загрузить файл" }).click();
    await expect(page.getByText("Файл успешно прочитан", { exact: true })).toBeVisible({
      timeout: 30_000,
    });
    const tsxCaptured = await captureValidationReview(page, "federal-tsx-validation");
    const tsxValidation = tsxCaptured.validation;
    expect(tsxValidation.federal_allocation).toMatchObject({
      status: "available",
      declared_geo_count: 114,
      ready_geo_count: 103,
      excluded_geo_count: 11,
      allocated_budget_rub: FEDERAL_BUDGET_RUB,
    });
    expect(tsxValidation.geo_points).toHaveLength(103);
    expect(tsxValidation.map_coverage.unlocated_geographies_n).toBe(0);
    await expect(page.getByText("Данные результата имеют неподдерживаемый формат.", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Карта рекламного бюджета текущей кампании" })
      .locator("[data-map-marker]")).toHaveCount(103);
    await attachDomPass("federal-tsx-validation", tsxCaptured, [
      "103 map markers visible",
      "unsupported-format message absent",
    ]);

    const yakutskCaptured = await validateLivePlan(
      page,
      "ordinary-yakutsk-blocking",
      "b2-2-yakutsk-local-live.csv",
      [`B2.2 Yakutsk local live,${LIVE_BUSINESS_DIRECTION},Якутск,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},1000000`],
    );
    const yakutskValidation = yakutskCaptured.validation;
    expect(yakutskValidation.job_creation_allowed).toBe(false);
    expect(yakutskValidation.model_limitations).toEqual(expect.arrayContaining([
      expect.objectContaining({
        limitation_type: "geo_not_forecast_ready_for_period",
        blocks_calculation: true,
      }),
    ]));
    await expect(page.getByText(/не может надежно рассчитать географию «Якутск»/)).toBeVisible();
    await expect(page.getByRole("button", { name: /Продолжить/ })).toHaveCount(0);
    await attachDomPass("ordinary-yakutsk-blocking", yakutskCaptured, [
      "blocking limitation visible",
      "continue button absent",
    ]);

    const moscowCaptured = await validateLivePlan(
      page,
      "ordinary-moscow-full",
      "b2-2-moscow-local-live.csv",
      [`B2.2 Moscow local live,${LIVE_BUSINESS_DIRECTION},Москва,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},1000000`],
    );
    const moscowValidation = moscowCaptured.validation;
    expect(moscowValidation.job_creation_allowed).toBe(true);
    expect(moscowValidation.geo_points).toHaveLength(1);
    expect(moscowValidation.geo_points[0].geo_display_name).toBe("Москва");
    await runValidatedPlanToResult(page);
    await attachDomPass("ordinary-moscow-full", moscowCaptured, [
      "ordinary validation ready",
      "job completed",
      "result opened",
    ]);

    const mixedCases = [
      { slug: "mixed-rf-moscow", geos: [["Москва", 1_000_000]] },
      { slug: "mixed-rf-kazan", geos: [["Казань", 2_000_000]] },
      { slug: "mixed-rf-moscow-oblast", geos: [["Московская область", 3_000_000]] },
      { slug: "mixed-rf-moscow-kazan", geos: [["Москва", 10_000_000], ["Казань", 5_000_000]] },
    ] as const;
    for (const mixedCase of mixedCases) {
      const mixedCaptured = await validateLivePlan(
        page,
        mixedCase.slug,
        `b2-2-${mixedCase.slug}-live.csv`,
        [
          `B2.2 ${mixedCase.slug} live,${LIVE_BUSINESS_DIRECTION},РФ,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},${FEDERAL_BUDGET_RUB}`,
          ...mixedCase.geos.map(([geo, budget]) => (
            `B2.2 ${mixedCase.slug} live,${LIVE_BUSINESS_DIRECTION},${geo},Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},${budget}`
          )),
        ],
      );
      const mixedValidation = mixedCaptured.validation;
      expect(mixedValidation.job_creation_allowed).toBe(true);
      expect(mixedValidation.federal_allocation).toMatchObject({
        status: "available",
        ready_geo_count: EXPECTED_GEO_COUNT,
        allocated_budget_rub: FEDERAL_BUDGET_RUB,
        mixed_local_overlap: true,
      });
      expect(mixedValidation.federal_allocation.warnings).toEqual([
        expect.objectContaining({ code: "FEDERAL_AND_LOCAL_GEO_OVERLAP" }),
      ]);
      await expect(page.getByText("Данные результата имеют неподдерживаемый формат.", { exact: true })).toHaveCount(0);
      await expect(page.getByText(/Локальные суммы будут добавлены поверх федерального распределения\./, { exact: true })).toHaveCount(1);
      await expect(page.getByRole("button", { name: "Продолжить с ограничениями" })).toBeVisible();
      await attachDomPass(mixedCase.slug, mixedCaptured, [
        "unsupported-format message absent",
        "exactly one grouped warning visible",
        "job creation control visible",
      ]);
    }

    const mixedYakutskCaptured = await validateLivePlan(
      page,
      "mixed-rf-yakutsk-blocking",
      "b2-2-federal-yakutsk-live.csv",
      [
        `B2.2 federal Yakutsk live,${LIVE_BUSINESS_DIRECTION},РФ,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},${FEDERAL_BUDGET_RUB}`,
        `B2.2 federal Yakutsk live,${LIVE_BUSINESS_DIRECTION},Якутск,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},1000000`,
      ],
    );
    const mixedYakutskValidation = mixedYakutskCaptured.validation;
    expect(mixedYakutskValidation.job_creation_allowed).toBe(false);
    expect(mixedYakutskValidation.federal_allocation).toMatchObject({
      status: "available",
      ready_geo_count: EXPECTED_GEO_COUNT,
      allocated_budget_rub: FEDERAL_BUDGET_RUB,
      difference_rub: 0,
      mixed_local_overlap: true,
    });
    expect(mixedYakutskValidation.model_limitations).toEqual(expect.arrayContaining([
      expect.objectContaining({
        limitation_type: "geo_not_forecast_ready_for_period",
        blocks_calculation: true,
      }),
    ]));
    await expect(page.getByText("Данные результата имеют неподдерживаемый формат.", { exact: true })).toHaveCount(0);
    await expect(page.getByText(/не может надежно рассчитать географию «Якутск»/)).toBeVisible();
    await expect(page.getByRole("button", { name: /Продолжить/ })).toHaveCount(0);
    await attachDomPass("mixed-rf-yakutsk-blocking", mixedYakutskCaptured, [
      "unsupported-format message absent",
      "blocking limitation visible",
      "continue button absent",
    ]);
  });
});
