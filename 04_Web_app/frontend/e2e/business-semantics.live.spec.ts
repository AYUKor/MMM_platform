import { expect, test, type Page, type Response } from "@playwright/test";
import type { JobResultViewV2 } from "../src/shared/api/generated/job-result-view-v2";
import type { ModelOverviewV2 } from "../src/shared/api/generated/model-overview-v2";
import type { ModelPassportV2 } from "../src/shared/api/generated/model-passport-v2";
import type { ScenarioMediaPlanV2 } from "../src/shared/api/generated/scenario-media-plan-v2";
import type { ValidationResultV2 } from "../src/shared/api/generated/validation-result-v2";
import type { WorkspaceGeoBudgetV1 } from "../src/shared/api/generated/workspace-geo-budget-v1";

const LIVE_ENABLED = process.env.PHASE_E1B_LIVE === "true";
const EMAIL = process.env.PHASE_E1B_LIVE_EMAIL ?? "";
const PASSWORD = process.env.PHASE_E1B_LIVE_PASSWORD ?? "";
const JOB_ID = process.env.PHASE_E1B_LIVE_JOB_ID ?? "";
const VALIDATION_ID = process.env.PHASE_E1B_LIVE_VALIDATION_ID ?? "";

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

test.describe("Phase E.1B live backend acceptance", () => {
  test.skip(
    !LIVE_ENABLED,
    "Set PHASE_E1B_LIVE=true and provide credentials, job and validation IDs.",
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

    const geoBudgetResponse = page.waitForResponse((response) => (
      pathname(response) === "/api/v1/workspace/geo-budget" && response.status() === 200
    ));
    const geoCatalogResponse = page.waitForResponse((response) => (
      pathname(response) === "/api/v1/meta/geo-catalog" && response.status() === 200
    ));
    await page.goto("/");
    const geoBudget = await (await geoBudgetResponse).json() as WorkspaceGeoBudgetV1;
    await geoCatalogResponse;
    expect(geoBudget.geographies_n).toBeGreaterThanOrEqual(0);
    await expect(page.getByRole("heading", { name: "Бюджет проверенных кампаний по географиям" }))
      .toBeVisible();
    await expect(page.getByText("Карта пока недоступна", { exact: true })).toBeVisible();
    await expectTurnoverOnlyPage(page);

    expect(consoleIssues).toEqual([]);
  });
});
