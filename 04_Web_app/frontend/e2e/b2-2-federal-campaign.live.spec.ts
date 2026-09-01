import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";


const LIVE_ENABLED = process.env.B2_2_LIVE === "true";
const EMAIL = process.env.B2_2_LIVE_EMAIL ?? "";
const PASSWORD = process.env.B2_2_LIVE_PASSWORD ?? "";

const FEDERAL_BUDGET_RUB = 100_000_000;
const SUPPORTED_FLIGHT_DATE = "2026-09-01";
const LIVE_BUSINESS_DIRECTION = "ТС5/Онлайн";
const DECLARED_GEO_COUNT = 211;
const EXPECTED_GEO_COUNT = 175;
const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

async function validateLivePlan(page: Page, filename: string, rows: readonly string[]) {
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
  const validationResponse = page.waitForResponse((response) => (
    response.request().method() === "GET"
    && /\/api\/v1\/validations\/validation_[a-z0-9]+\/view-v2$/.test(new URL(response.url()).pathname)
    && response.status() === 200
  ), { timeout: 120_000 });
  await page.getByRole("button", { name: "Продолжить к проверке" }).click();
  return (await validationResponse).json();
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
    await page.getByRole("button", { name: "Продолжить к проверке" }).click();

    const validationResponse = await page.waitForResponse((response) => (
      response.request().method() === "GET"
      && /\/api\/v1\/validations\/validation_[a-z0-9]+\/view-v2$/.test(new URL(response.url()).pathname)
      && response.status() === 200
    ), { timeout: 120_000 });
    const validation = await validationResponse.json();
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
    await page.getByRole("button", { name: "Продолжить к проверке" }).click();
    const tsxValidationResponse = await page.waitForResponse((response) => (
      response.request().method() === "GET"
      && /\/api\/v1\/validations\/validation_[a-z0-9]+\/view-v2$/.test(new URL(response.url()).pathname)
      && response.status() === 200
    ), { timeout: 120_000 });
    const tsxValidation = await tsxValidationResponse.json();
    expect(tsxValidation.federal_allocation).toMatchObject({
      status: "available",
      declared_geo_count: 114,
      ready_geo_count: 103,
      excluded_geo_count: 11,
      allocated_budget_rub: FEDERAL_BUDGET_RUB,
    });
    expect(tsxValidation.geo_points).toHaveLength(103);
    expect(tsxValidation.map_coverage.unlocated_geographies_n).toBe(0);

    const yakutskValidation = await validateLivePlan(
      page,
      "b2-2-yakutsk-local-live.csv",
      [`B2.2 Yakutsk local live,${LIVE_BUSINESS_DIRECTION},Якутск,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},1000000`],
    );
    expect(yakutskValidation.job_creation_allowed).toBe(false);
    expect(yakutskValidation.model_limitations).toEqual(expect.arrayContaining([
      expect.objectContaining({
        limitation_type: "geo_not_forecast_ready_for_period",
        blocks_calculation: true,
      }),
    ]));
    await expect(page.getByText(/не может надежно рассчитать географию «Якутск»/)).toBeVisible();

    const moscowValidation = await validateLivePlan(
      page,
      "b2-2-moscow-local-live.csv",
      [`B2.2 Moscow local live,${LIVE_BUSINESS_DIRECTION},Москва,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},1000000`],
    );
    expect(moscowValidation.job_creation_allowed).toBe(true);
    expect(moscowValidation.geo_points).toHaveLength(1);
    expect(moscowValidation.geo_points[0].geo_display_name).toBe("Москва");
    await runValidatedPlanToResult(page);

    const mixedMoscowValidation = await validateLivePlan(
      page,
      "b2-2-federal-moscow-live.csv",
      [
        `B2.2 federal Moscow live,${LIVE_BUSINESS_DIRECTION},РФ,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},${FEDERAL_BUDGET_RUB}`,
        `B2.2 federal Moscow live,${LIVE_BUSINESS_DIRECTION},Москва,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},1000000`,
      ],
    );
    expect(mixedMoscowValidation.job_creation_allowed).toBe(true);
    expect(mixedMoscowValidation.federal_allocation).toMatchObject({
      status: "available",
      ready_geo_count: EXPECTED_GEO_COUNT,
      allocated_budget_rub: FEDERAL_BUDGET_RUB,
      mixed_local_overlap: true,
    });
    expect(mixedMoscowValidation.federal_allocation.warnings).toEqual(expect.arrayContaining([
      expect.objectContaining({ code: "FEDERAL_AND_LOCAL_GEO_OVERLAP" }),
    ]));

    const mixedYakutskValidation = await validateLivePlan(
      page,
      "b2-2-federal-yakutsk-live.csv",
      [
        `B2.2 federal Yakutsk live,${LIVE_BUSINESS_DIRECTION},РФ,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},${FEDERAL_BUDGET_RUB}`,
        `B2.2 federal Yakutsk live,${LIVE_BUSINESS_DIRECTION},Якутск,Digital_Performance,${SUPPORTED_FLIGHT_DATE},${SUPPORTED_FLIGHT_DATE},1000000`,
      ],
    );
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
  });
});
