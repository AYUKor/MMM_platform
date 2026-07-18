import { expect, test, type Locator, type Page, type Response } from "@playwright/test";
import { readFile } from "node:fs/promises";
import type { HistoricalModelGeoBudgetV1 } from "../src/shared/api/generated/historical-model-geo-budget-v1";
import type { JobResultViewV2 } from "../src/shared/api/generated/job-result-view-v2";
import type { ModelOverviewV2 } from "../src/shared/api/generated/model-overview-v2";
import type { ModelPassportV2 } from "../src/shared/api/generated/model-passport-v2";
import type { ScenarioMediaPlanV2 } from "../src/shared/api/generated/scenario-media-plan-v2";
import type { ValidationResultV2 } from "../src/shared/api/generated/validation-result-v2";
import { formatInteger, formatPercent, formatRub } from "../src/shared/formatters/metrics";

interface LiveReportArtifact {
  artifact_id: string;
  display_name: string;
  size_bytes: number;
  download_path: string;
}

interface LiveReportEnvelope {
  job_id: string;
  result_id: string;
  report: {
    status: string;
    artifact: LiveReportArtifact | null;
    working_media_plan: {
      status: string;
    };
  };
}

const E1F_LIVE_ENABLED = process.env.PHASE_E1F_LIVE === "true";
const LEGACY_LIVE_ENABLED = process.env.PHASE_E1D_LIVE === "true"
  || process.env.PHASE_E1B_LIVE === "true";
const EMAIL = process.env.PHASE_E1F_LIVE_EMAIL
  ?? process.env.PHASE_E1D_LIVE_EMAIL
  ?? process.env.PHASE_E1B_LIVE_EMAIL
  ?? "";
const PASSWORD = process.env.PHASE_E1F_LIVE_PASSWORD
  ?? process.env.PHASE_E1D_LIVE_PASSWORD
  ?? process.env.PHASE_E1B_LIVE_PASSWORD
  ?? "";
const JOB_ID = process.env.PHASE_E1F_LIVE_JOB_ID
  ?? process.env.PHASE_E1D_LIVE_JOB_ID
  ?? process.env.PHASE_E1B_LIVE_JOB_ID
  ?? "";
const VALIDATION_ID = process.env.PHASE_E1F_LIVE_VALIDATION_ID
  ?? process.env.PHASE_E1D_LIVE_VALIDATION_ID
  ?? process.env.PHASE_E1B_LIVE_VALIDATION_ID
  ?? "";

const CONTROL_REQUESTED_BUDGET = 267_818_706;
const CONTROL_S5_ALLOCATED_BUDGET = 173_912_510.63;
const CONTROL_S5_UNALLOCATED_BUDGET = 93_906_195.37;

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

function pathname(response: Response): string {
  return new URL(response.url()).pathname;
}

async function expectTurnoverOnlyPage(page: Page) {
  const text = await page.locator("body").innerText();
  for (const forbidden of FORBIDDEN_COPY) expect(text).not.toContain(forbidden);
}

async function expectDefinitionValue(
  scope: Locator,
  term: string,
  expectedValue: string,
) {
  const definition = scope.locator("dt").filter({ hasText: term }).first();
  await expect(definition).toHaveText(term);
  await expect(definition.locator("xpath=following-sibling::dd[1]")).toHaveText(expectedValue);
}

async function expectUnlocatedBudgetPreserved(
  scope: Locator,
  unlocatedGeographiesN: number,
  unlocatedBudgetRub: number,
  unlocatedBudgetShare: number | null,
) {
  await expect(scope).toContainText(
    `Без координат: ${formatInteger(unlocatedGeographiesN)} географий`,
  );
  await expect(scope).toContainText(`Бюджет сохранен: ${formatRub(unlocatedBudgetRub)}`);
  await expect(scope).toContainText(`доля: ${formatPercent(unlocatedBudgetShare)}`);
}

test.use({ trace: "off", screenshot: "off", video: "off" });

test.describe("Phase E.1F historical Home live acceptance", () => {
  test.skip(
    !E1F_LIVE_ENABLED,
    "Set PHASE_E1F_LIVE=true and provide PHASE_E1F_LIVE_EMAIL/PASSWORD.",
  );

  test("uses the real historical model artifact without workspace fallback", async ({ page }) => {
    test.setTimeout(60_000);
    expect(EMAIL).not.toBe("");
    expect(PASSWORD).not.toBe("");

    await page.goto("/login");
    if (new URL(page.url()).pathname === "/login") {
      await page.getByLabel("Email").fill(EMAIL);
      await page.getByLabel("Пароль").fill(PASSWORD);
      await page.getByRole("button", { name: "Войти" }).click();
      await expect(page).not.toHaveURL(/\/login/);
    }

    const consoleIssues: string[] = [];
    const requestedPaths: string[] = [];
    page.on("console", (message) => {
      if (["warning", "error"].includes(message.type())) {
        consoleIssues.push(`${message.type()}: ${message.text()}`);
      }
    });
    page.on("pageerror", (error) => consoleIssues.push(`pageerror: ${error.message}`));
    page.on("request", (request) => requestedPaths.push(new URL(request.url()).pathname));
    const responsePromise = page.waitForResponse((response) => (
      pathname(response) === "/api/v1/model/historical-geo-budget"
      && response.status() === 200
    ));

    await page.goto("/");
    const payload = await (await responsePromise).json() as HistoricalModelGeoBudgetV1;
    expect(requestedPaths.filter((path) => path === "/api/v1/model/historical-geo-budget"))
      .toHaveLength(1);
    expect(requestedPaths).not.toContain("/api/v1/workspace/geo-budget");
    expect(payload.record_origin).toBe("verified_model_package_artifact");
    expect(payload.status).toBe("available");
    expect(payload.period_start).toBe("2025-01-01");
    expect(payload.period_end).toBe("2026-05-31");
    expect(payload.total_budget_rub).toBeCloseTo(8_687_024_294.654741, 5);
    expect(payload.geographies_n).toBe(220);
    expect(payload.rows).toHaveLength(220);
    expect(payload.coverage).toMatchObject({
      status: "available",
      located_geographies_n: 220,
      unlocated_geographies_n: 0,
      unlocated_budget_rub: 0,
    });
    expect([...payload.rows]
      .sort((left, right) => right.historical_total_budget_rub - left.historical_total_budget_rub)
      .slice(0, 3)
      .map((row) => row.geo_display_name)).toEqual([
      "Москва",
      "Санкт-Петербург",
      "Московская область",
    ]);

    const section = page.getByRole("heading", {
      name: "Исторический рекламный бюджет в данных модели",
    }).locator("xpath=ancestor::section[1]");
    await expect(section).toBeVisible();
    const map = section.locator('[data-map-mode="historical-model"]');
    await expect(map.locator("[data-map-marker]")).toHaveCount(220);
    await expect(map.locator("[data-map-label]")).toHaveCount(10);
    await expect(section.getByText("Кампании", { exact: true })).toHaveCount(0);
    const moscow = payload.rows.find((row) => row.geo_display_name === "Москва");
    expect(moscow).toBeDefined();
    await map.locator(`[data-map-marker="${moscow?.geo_id}"]`).focus();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toContainText("Исторический рекламный бюджет");
    await expect(tooltip).toContainText("Дней с рекламной активностью");
    await expect(tooltip).toContainText(
      payload.period_display_text.replace(/^Период данных:\s*/u, ""),
    );
    await expect(tooltip).not.toContainText("Кампаний");
    await expectTurnoverOnlyPage(page);
    expect(consoleIssues).toEqual([]);
  });
});

test.describe("Phase E.1D live backend acceptance", () => {
  test.skip(
    !LEGACY_LIVE_ENABLED,
    "Set PHASE_E1D_LIVE=true and provide credentials, job and validation IDs. "
      + "PHASE_E1B_LIVE variables remain supported as aliases.",
  );

  test("uses real turnover-only projections without route interception", async ({ page }) => {
    test.setTimeout(120_000);
    expect(EMAIL).not.toBe("");
    expect(PASSWORD).not.toBe("");
    expect(JOB_ID).not.toBe("");
    expect(VALIDATION_ID).not.toBe("");

    // Authenticate first. Console collection starts afterwards so the expected
    // anonymous session bootstrap does not hide product-page regressions.
    await page.goto("/login");
    if (new URL(page.url()).pathname === "/login") {
      await page.getByLabel("Email").fill(EMAIL);
      await page.getByLabel("Пароль").fill(PASSWORD);
      await page.getByRole("button", { name: "Войти" }).click();
      await expect(page).not.toHaveURL(/\/login/);
    }

    const consoleIssues: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "warning" || message.type() === "error") {
        consoleIssues.push(`${message.type()}: ${message.text()}`);
      }
    });
    page.on("pageerror", (error) => consoleIssues.push(`pageerror: ${error.message}`));

    const resultPath = `/api/v1/jobs/${JOB_ID}/result-view-v2`;
    const resultResponse = page.waitForResponse((response) => (
      response.request().method() === "GET"
      && pathname(response) === resultPath
      && response.status() === 200
    ));
    await page.goto(`/calculations/${encodeURIComponent(JOB_ID)}/result`);
    const result = await (await resultResponse).json() as JobResultViewV2;

    expect(result.campaign.requested_budget_rub).toBeCloseTo(CONTROL_REQUESTED_BUDGET, 2);
    expect(result.campaign.channels).toHaveLength(3);
    expect(result.campaign.geographies_n).toBe(15);
    const s1 = result.scenarios.find((scenario) => scenario.scenario_id === "S01");
    const s5 = result.scenarios.find((scenario) => scenario.scenario_id === "S05");
    const s6 = result.scenarios.find((scenario) => scenario.scenario_id === "S06");
    expect(s1).toMatchObject({
      scenario_variant: "uploaded_plan",
      decision_status: "keep_uploaded_plan",
      review_status: "manual_review_required",
    });
    expect(s5).toMatchObject({
      scenario_variant: "safe_partial",
      status: "completed",
    });
    expect(s5?.budget.allocated_budget_rub).toBeCloseTo(CONTROL_S5_ALLOCATED_BUDGET, 2);
    expect(s5?.budget.unallocated_budget_rub).toBeCloseTo(CONTROL_S5_UNALLOCATED_BUDGET, 2);
    expect(s5?.risk_budget.high_risk_budget_rub).toBe(0);
    expect(s5?.roas.allocated_budget.status).toBe("available");
    expect(s5?.roas.requested_budget.status).toBe("available");
    expect(s6).toMatchObject({ status: "infeasible", scenario_variant: "infeasible" });
    expect(s6?.incremental_turnover.status).toBe("unavailable");
    expect(s6?.roas.allocated_budget.status).toBe("unavailable");

    await expect(page.getByRole("heading", { name: "Оборот и ROAS" })).toBeVisible();
    await expectTurnoverOnlyPage(page);
    await page.getByRole("tab", { name: "Сценарии и надежность" }).click();
    await expect(page.locator("#scenario-S01")).toContainText("Точка отсчета");
    await expect(page.locator("#scenario-S01")).toContainText("Требуется ручная проверка");
    await expect(page.locator("#scenario-S05")).toContainText("Безопасно распределяемая часть");
    await expect(page.locator("#scenario-S05")).toContainText("ROAS распределенной части");
    await expect(page.locator("#scenario-S05")).toContainText("Отдача относительно всего запрошенного бюджета");
    await expect(page.locator("#scenario-S06")).toContainText("Недоступно при текущих ограничениях");
    await expect(page.locator("#scenario-S06").getByText(/ROAS/)).toHaveCount(0);
    await expectTurnoverOnlyPage(page);

    await page.getByRole("tab", { name: "Медиаплан" }).click();
    const s5MediaResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "GET"
        && url.pathname === `/api/v1/jobs/${JOB_ID}/media-plan-v2`
        && url.searchParams.get("scenario_id") === "S05"
        && response.status() === 200;
    });
    await page.getByLabel("Сценарий").selectOption("S05");
    const mediaPlan = await (await s5MediaResponse).json() as ScenarioMediaPlanV2;
    expect(mediaPlan.scenario.scenario_id).toBe("S05");
    expect(mediaPlan.scenario.is_selected).toBe(false);
    expect(mediaPlan.pagination.total_rows).toBe(45);
    expect(mediaPlan.aggregates.by_channel).toHaveLength(3);
    expect(mediaPlan.aggregates.by_geo).toHaveLength(15);
    expect(mediaPlan.totals.requested_budget_rub).toBeCloseTo(CONTROL_REQUESTED_BUDGET, 2);
    expect(mediaPlan.totals.selected_budget_rub).toBeCloseTo(CONTROL_S5_ALLOCATED_BUDGET, 2);
    expect(mediaPlan.totals.unallocated_budget_rub).toBeCloseTo(CONTROL_S5_UNALLOCATED_BUDGET, 2);
    await expect(page.getByRole("heading", { name: "План согласован с результатом" })).toBeVisible();
    await expectTurnoverOnlyPage(page);

    const reportMetadataResponse = page.waitForResponse((response) => (
      response.request().method() === "GET"
      && pathname(response) === `/api/v1/jobs/${JOB_ID}/result-view`
      && response.status() === 200
    ));
    await page.getByRole("tab", { name: "Отчет" }).click();
    const reportEnvelope = await (await reportMetadataResponse).json() as LiveReportEnvelope;
    expect(reportEnvelope.job_id).toBe(JOB_ID);
    expect(reportEnvelope.result_id).toBe(result.result_id);
    expect(reportEnvelope.report.status).toBe("ready");
    expect(reportEnvelope.report.artifact).not.toBeNull();
    const reportArtifact = reportEnvelope.report.artifact!;
    await expect(page.getByRole("heading", { name: reportArtifact.display_name })).toBeVisible();

    const downloadEvent = page.waitForEvent("download");
    await page.getByRole("link", { name: "Скачать отчет" }).click();
    const download = await downloadEvent;
    expect(await download.failure()).toBeNull();
    const suggestedFilename = download.suggestedFilename();
    expect(suggestedFilename).toMatch(/\.xlsx$/i);
    expect(suggestedFilename).not.toContain("/");
    expect(suggestedFilename).not.toContain("\\");
    expect([...suggestedFilename].some((character) => {
      const code = character.charCodeAt(0);
      return code <= 31 || code === 127;
    })).toBe(false);
    const actualDownloadUrl = download.url();
    expect(new URL(actualDownloadUrl).pathname).toBe(reportArtifact.download_path);
    const downloadedPath = await download.path();
    expect(downloadedPath).not.toBeNull();
    const downloadedBytes = await readFile(downloadedPath!);
    expect(downloadedBytes.byteLength).toBe(reportArtifact.size_bytes);
    expect([...downloadedBytes.subarray(0, 2)]).toEqual([0x50, 0x4b]);

    const verifiedDownload = await page.request.get(actualDownloadUrl);
    expect(verifiedDownload.status()).toBe(200);
    expect(verifiedDownload.headers()["content-type"]).toContain(
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    );
    expect(verifiedDownload.headers()["content-disposition"]).toContain("attachment");
    const verifiedBytes = await verifiedDownload.body();
    expect(verifiedBytes.byteLength).toBe(reportArtifact.size_bytes);
    expect([...verifiedBytes.subarray(0, 2)]).toEqual([0x50, 0x4b]);

    if (reportEnvelope.report.working_media_plan.status === "ready") {
      await expect(page.getByRole("link", { name: "Скачать медиаплан" })).toBeVisible();
    } else {
      await expect(page.getByRole("heading", { name: "Рабочий Excel-медиаплан" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Скачать медиаплан" })).toHaveCount(0);
    }
    await expectTurnoverOnlyPage(page);

    const validationPath = `/api/v1/validations/${VALIDATION_ID}/view-v2`;
    const validationResponse = page.waitForResponse((response) => (
      response.request().method() === "GET"
      && pathname(response) === validationPath
      && response.status() === 200
    ));
    await page.goto(`/calculations/new?validationId=${encodeURIComponent(VALIDATION_ID)}&step=review`);
    const validation = await (await validationResponse).json() as ValidationResultV2;
    expect(validation.file_validation.rows_n).toBe(45);
    expect(validation.file_validation.geographies_n).toBe(15);
    expect(validation.file_validation.channels_n).toBe(3);
    expect(validation.file_validation.requested_budget_rub).toBe(CONTROL_REQUESTED_BUDGET);
    await expect(page.getByRole("heading", { name: "Проверка файла" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Ограничения модели" })).toBeVisible();
    const validationSection = page.getByRole("heading", { name: "Проверка файла" })
      .locator("xpath=ancestor::section[1]");
    await expectDefinitionValue(
      validationSection,
      "Запрошенный бюджет",
      formatRub(validation.file_validation.requested_budget_rub),
    );

    expect(validation.geo_points).toHaveLength(15);
    const canonicalValidationPoints = validation.geo_points.filter((point) => (
      point.coordinates_status === "canonical"
    ));
    const validationMapCoverage = validation.map_coverage;
    expect(canonicalValidationPoints).toHaveLength(validationMapCoverage.located_geographies_n);
    expect(validation.geo_points.length - canonicalValidationPoints.length).toBe(
      validationMapCoverage.unlocated_geographies_n,
    );
    const validationGeoSection = page.getByRole("heading", {
      name: `${validation.geo_points.length} географий сохранены`,
    }).locator("xpath=ancestor::section[1]");

    if (validationMapCoverage.status === "available") {
      expect(canonicalValidationPoints).toHaveLength(15);
      expect(validationMapCoverage.located_geographies_n).toBe(15);
      expect(validationMapCoverage.unlocated_geographies_n).toBe(0);
      expect(validationMapCoverage.located_budget_rub).toBe(CONTROL_REQUESTED_BUDGET);
      expect(validationMapCoverage.unlocated_budget_rub).toBe(0);

      const campaignMap = validationGeoSection.locator('[data-map-mode="campaign"]');
      await expect(campaignMap).toBeVisible();
      await expect(campaignMap.locator("[data-map-marker]")).toHaveCount(15);
      await expect(campaignMap.locator("[data-map-label]")).toHaveCount(15);
      await expect(campaignMap).toContainText("Координаты городов: GeoNames, CC BY 4.0.");
      await expect(campaignMap).toContainText("Контур карты: Natural Earth, public domain.");
      const markerIds = await campaignMap.locator("[data-map-marker]").evaluateAll((markers) => (
        markers.map((marker) => marker.getAttribute("data-map-marker")).sort()
      ));
      const labelIds = await campaignMap.locator("[data-map-label]").evaluateAll((labels) => (
        labels.map((label) => label.getAttribute("data-map-label")).sort()
      ));
      const canonicalIds = canonicalValidationPoints.map((point) => point.geo_id).sort();
      expect(markerIds).toEqual(canonicalIds);
      expect(labelIds).toEqual(canonicalIds);

      const humanChannelNames = [...new Set(canonicalValidationPoints.flatMap((point) => (
        point.channels.map((channel) => channel.channel_display_name)
      )))];
      const rawChannelNames = [...new Set(canonicalValidationPoints.flatMap((point) => (
        point.channels
          .filter((channel) => channel.channel_id !== channel.channel_display_name)
          .map((channel) => channel.channel_id)
      )))];
      const validationText = await validationGeoSection.innerText();
      for (const channelName of humanChannelNames) expect(validationText).toContain(channelName);
      for (const rawChannelName of rawChannelNames) expect(validationText).not.toContain(rawChannelName);

      const firstCampaignMarker = campaignMap.locator("[data-map-marker]").first();
      const firstCampaignGeoId = await firstCampaignMarker.getAttribute("data-map-marker");
      const firstCampaignPoint = canonicalValidationPoints.find((point) => (
        point.geo_id === firstCampaignGeoId
      ));
      expect(firstCampaignPoint).toBeDefined();
      await firstCampaignMarker.focus();
      const campaignTooltip = campaignMap.locator("[data-map-tooltip]");
      await expect(campaignTooltip).toBeVisible();
      await expect(campaignTooltip).toHaveAttribute("data-map-tooltip", firstCampaignGeoId!);
      await expect(campaignTooltip).toContainText(formatRub(firstCampaignPoint!.budget_rub));
      for (const channel of firstCampaignPoint!.channels) {
        await expect(campaignTooltip).toContainText(channel.channel_display_name);
      }
      await page.keyboard.press("Escape");
      await expect(campaignTooltip).toHaveCount(0);
    } else if (validationMapCoverage.status === "partial") {
      expect(canonicalValidationPoints.length).toBeGreaterThan(0);
      const campaignMap = validationGeoSection.locator('[data-map-mode="campaign"]');
      await expect(campaignMap).toBeVisible();
      await expect(campaignMap).toHaveAttribute("data-coverage-status", "partial");
      await expect(campaignMap.locator("[data-map-marker]")).toHaveCount(
        canonicalValidationPoints.filter((point) => point.budget_rub > 0).length,
      );
      await expect(campaignMap.locator("[data-map-label]")).toHaveCount(
        canonicalValidationPoints.filter((point) => point.budget_rub > 0).length,
      );
      await expect(campaignMap).toContainText(
        `Неразмещенный бюджет: ${formatRub(validationMapCoverage.unlocated_budget_rub)}`,
      );
      await expect(campaignMap).toContainText(
        `доля: ${formatPercent(validationMapCoverage.unlocated_budget_share)}`,
      );
    } else {
      expect(canonicalValidationPoints).toHaveLength(0);
      await expect(validationGeoSection.getByText("Карта пока недоступна", { exact: true }))
        .toBeVisible();
      await expectUnlocatedBudgetPreserved(
        validationGeoSection,
        validationMapCoverage.unlocated_geographies_n,
        validationMapCoverage.unlocated_budget_rub,
        validationMapCoverage.unlocated_budget_share,
      );
    }
    await expectTurnoverOnlyPage(page);

    const passportResponse = page.waitForResponse((response) => (
      pathname(response) === "/api/v1/models/active-v2" && response.status() === 200
    ));
    const overviewResponse = page.waitForResponse((response) => (
      pathname(response) === "/api/v1/model/overview-v2" && response.status() === 200
    ));
    await page.goto("/model");
    const [passport, overview] = await Promise.all([
      passportResponse.then((response) => response.json() as Promise<ModelPassportV2>),
      overviewResponse.then((response) => response.json() as Promise<ModelOverviewV2>),
    ]);
    expect(passport.serving.serving_targets_n).toBe(1);
    expect(passport.serving.active_serving_models_n).toBe(4);
    expect(passport.serving.research_models_in_package_n).toBe(12);
    expect(overview.serving.target_id).toBe("turnover");
    await expect(page.getByRole("heading", { name: "Дополнительный оборот" })).toBeVisible();
    await expectTurnoverOnlyPage(page);

    const homeGeoRequests: string[] = [];
    const recordHomeGeoRequest = (request: { url(): string }) => {
      const requestPath = new URL(request.url()).pathname;
      if ([
        "/api/v1/model/historical-geo-budget",
        "/api/v1/workspace/geo-budget",
        "/api/v1/meta/geo-catalog",
      ].includes(requestPath)) homeGeoRequests.push(requestPath);
    };
    page.on("request", recordHomeGeoRequest);
    const geoBudgetResponse = page.waitForResponse((response) => (
      pathname(response) === "/api/v1/model/historical-geo-budget" && response.status() === 200
    ));
    await page.goto("/");
    const geoBudget = await (await geoBudgetResponse).json() as HistoricalModelGeoBudgetV1;
    page.off("request", recordHomeGeoRequest);
    expect(homeGeoRequests.filter((path) => path === "/api/v1/model/historical-geo-budget"))
      .toHaveLength(1);
    expect(homeGeoRequests).not.toContain("/api/v1/workspace/geo-budget");
    expect(homeGeoRequests).not.toContain("/api/v1/meta/geo-catalog");
    expect(geoBudget.record_origin).toBe("verified_model_package_artifact");
    expect(geoBudget.status).toBe("available");
    expect(geoBudget.total_budget_rub).toBeCloseTo(8_687_024_294.654741, 5);
    expect(geoBudget.period_start).toBe("2025-01-01");
    expect(geoBudget.period_end).toBe("2026-05-31");
    expect(geoBudget.geographies_n).toBe(220);
    expect(geoBudget.rows).toHaveLength(220);
    expect(geoBudget.coverage.located_geographies_n).toBe(220);
    expect(geoBudget.coverage.unlocated_geographies_n).toBe(0);
    expect(geoBudget.coverage.unlocated_budget_rub).toBe(0);
    expect([...geoBudget.rows]
      .sort((left, right) => right.historical_total_budget_rub - left.historical_total_budget_rub)
      .slice(0, 3)
      .map((row) => row.geo_display_name)).toEqual([
      "Москва",
      "Санкт-Петербург",
      "Московская область",
    ]);

    const historicalGeoSection = page.getByRole("heading", {
      name: "Исторический рекламный бюджет в данных модели",
    }).locator("xpath=ancestor::section[1]");
    await expect(historicalGeoSection).toBeVisible();
    await expectDefinitionValue(
      historicalGeoSection,
      "Общий рекламный бюджет",
      formatRub(geoBudget.total_budget_rub),
    );
    await expectDefinitionValue(
      historicalGeoSection,
      "Географий",
      formatInteger(geoBudget.geographies_n),
    );
    await expectDefinitionValue(
      historicalGeoSection,
      "Период данных",
      "01.01.2025 — 31.05.2026",
    );
    await expectDefinitionValue(
      historicalGeoSection,
      "Покрытие карты",
      "220 из 220",
    );
    await expect(historicalGeoSection.getByText("Кампании", { exact: true })).toHaveCount(0);

    const historicalMap = historicalGeoSection.locator('[data-map-mode="historical-model"]');
    await expect(historicalMap).toBeVisible();
    await expect(historicalMap).toHaveAttribute("data-coverage-status", "available");
    await expect(historicalMap).toContainText("Координаты городов: GeoNames, CC BY 4.0.");
    await expect(historicalMap).toContainText("Контур карты: Natural Earth, public domain.");
    await expect(historicalMap.locator("[data-map-marker]")).toHaveCount(220);
    await expect(historicalMap.locator("[data-map-label]")).toHaveCount(10);

    const expectedTopTenIds = [...geoBudget.rows]
      .sort((left, right) => (
        right.historical_total_budget_rub - left.historical_total_budget_rub
        || new Intl.Collator("ru", { sensitivity: "base" }).compare(
          left.geo_display_name,
          right.geo_display_name,
        )
        || left.geo_id.localeCompare(right.geo_id)
      ))
      .slice(0, 10)
      .map((row) => row.geo_id)
      .sort();
    const labelIds = await historicalMap.locator("[data-map-label]")
      .evaluateAll((labels) => labels.map((label) => label.getAttribute("data-map-label")).sort());
    expect(labelIds).toEqual(expectedTopTenIds);

    const largestRow = [...geoBudget.rows]
      .sort((left, right) => right.historical_total_budget_rub - left.historical_total_budget_rub)[0];
    const largestMarker = historicalMap.locator(`[data-map-marker="${largestRow.geo_id}"]`);
    await largestMarker.focus();
    const tooltip = page.getByRole("tooltip");
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText(largestRow.geo_display_name);
    await expect(tooltip).toContainText("Исторический рекламный бюджет");
    await expect(tooltip).toContainText(formatRub(largestRow.historical_total_budget_rub));
    await expect(tooltip).toContainText("Дней с рекламной активностью");
    await expect(tooltip).toContainText(formatInteger(largestRow.active_days_n));
    await expect(tooltip).toContainText(
      geoBudget.period_display_text.replace(/^Период данных:\s*/u, ""),
    );
    await expect(tooltip).not.toContainText("Кампаний");
    await expectTurnoverOnlyPage(page);

    expect(consoleIssues).toEqual([]);
  });
});
