import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import type { ResultOverviewV1 } from "../src/entities/result-overview/types";

const overviewFixture = JSON.parse(
  readFileSync(
    new URL("../../tests/fixtures/result_overview_v1_real_sanitized.json", import.meta.url),
    "utf8",
  ),
) as ResultOverviewV1;

type OverviewTransform = (overview: ResultOverviewV1) => void;

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

async function mockJob(
  page: Page,
  options: {
    status?: "succeeded" | "failed" | "cancelled" | "timed_out" | "running";
    transform?: OverviewTransform;
    retryable?: boolean;
  } = {},
) {
  const overview = structuredClone(overviewFixture) as unknown as ResultOverviewV1;
  options.transform?.(overview);
  await page.route("**/api/v1/jobs/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith("/overview")) {
      await route.fulfill({ status: 200, json: overview });
      return;
    }
    if (pathname.endsWith("/errors")) {
      await route.fulfill({
        status: 200,
        json: [{ retryable: options.retryable ?? false }],
      });
      return;
    }
    await route.fulfill({
      status: 200,
      json: { status: { code: options.status ?? "succeeded", display_text: "hidden" } },
    });
  });
}

async function expectNoDocumentOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
}

async function expectNoRawNames(page: Page) {
  const text = await page.locator("body").innerText();
  for (const rawName of [
    "candidate_",
    "MISSING_OR_FAILED",
    "storage_key",
    "result_overview_v1",
    "support/model risk",
    "optimizer_policy",
    "gate_reason_codes",
  ]) {
    expect(text).not.toContain(rawName);
  }
}

for (const theme of ["dark", "light"] as const) {
  test(`Phase 2 product pages ${theme} desktop`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    await setTheme(page, theme);
    await mockJob(page);
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.goto("/calculations/demo-safe/result");
    await expect(page.getByText("Демонстрационные данные")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Demo campaign 1" })).toBeVisible();
    await expect(page.getByText("Ориентир по устойчивости", { exact: true }).first()).toBeVisible();
    await page.evaluate(() => document.fonts.ready);

    await page.screenshot({
      path: `artifacts/visual-qa/result-overview-${theme}-1440x960.png`,
      fullPage: true,
    });

    for (const tab of ["Сценарии", "Надежность", "Медиаплан", "Отчет"]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
      await expectNoDocumentOverflow(page);
      await expectNoRawNames(page);
    }

    await page.screenshot({
      path: `artifacts/visual-qa/result-report-${theme}-1440x960.png`,
      fullPage: true,
    });
    expect(consoleErrors).toEqual([]);
  });
}

test("mobile result tabs use cards without page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockJob(page);
  await page.goto("/calculations/demo-safe/result");

  await page.getByRole("tab", { name: "Сценарии" }).click();
  await expect(page.getByText("Осторожное распределение")).toBeVisible();
  await expectNoDocumentOverflow(page);
  await page.screenshot({
    path: "artifacts/visual-qa/result-scenarios-mobile-375x812.png",
    fullPage: true,
  });

  await page.getByRole("tab", { name: "Медиаплан" }).click();
  await expect(page.getByText("Было → рекомендуется")).toBeVisible();
  await expect(page.locator("table")).toBeHidden();
  await expect(page.locator("article").filter({ hasText: "Было" }).first()).toBeVisible();
  await expectNoDocumentOverflow(page);
  await page.screenshot({
    path: "artifacts/visual-qa/result-plan-mobile-375x812.png",
    fullPage: true,
  });

  await page.setViewportSize({ width: 812, height: 375 });
  await page.reload();
  await expect(page.getByText("Демонстрационные данные")).toBeVisible();
  await expectNoDocumentOverflow(page);
});

test("partial coverage is explicit and uses contract values", async ({ page }) => {
  await mockJob(page, {
    transform: (overview) => {
      const campaign = overview.campaigns[0];
      campaign.statuses.calculation_status.code = "partially_calculated";
      campaign.budget.model_coverage_share = 0.72;
      campaign.budget.unmodeled_budget_rub = 2_000_000;
      campaign.budget.unallocated_budget_rub = 500_000;
    },
  });
  await page.goto("/calculations/partial/result");
  await expect(page.getByRole("heading", { name: "Результат рассчитан частично" })).toBeVisible();
  await expect(page.getByText(/72\s*%/)).toBeVisible();
  await page.screenshot({
    path: "artifacts/visual-qa/result-partial-coverage.png",
    fullPage: true,
  });
});

test("S6 unavailable has a controlled explanation and no substituted metrics", async ({ page }) => {
  await mockJob(page, {
    transform: (overview) => {
      const campaign = overview.campaigns[0];
      const s5 = campaign.scenarios.find((scenario) => scenario.scenario_id === "S05");
      const s6 = campaign.scenarios.find((scenario) => scenario.scenario_id === "S06");
      if (!s5 || !s6) throw new Error("Sanitized fixture must contain S5 and S6");
      s6.available = false;
      s6.metrics = {
        incremental_turnover: null,
        turnover_roas: null,
        incremental_orders: null,
        incremental_orders_usage: "diagnostic_only",
        avg_basket_turnover_bridge: null,
      };
      campaign.recommendation.scenario_id = "S05";
      campaign.recommendation.metrics = s5.metrics;
      campaign.recommendation.recommendation_type.code = "keep_uploaded_plan";
      campaign.recommendation.plan_status.code = "no_automatic_plan";
      campaign.recommendation.optimizer_available = false;
      campaign.statuses.optimizer_status.code = "gate_policy_blocked";
      campaign.scenario6.audit.run_status.code = "gate_policy_blocked";
      campaign.scenario6.best_raw = null;
      campaign.scenario6.best_safe = null;
      campaign.scenario6.raw_differs_from_safe = false;
    },
  });
  await page.goto("/calculations/gate-blocked/result");
  await page.getByRole("tab", { name: "Сценарии" }).click();
  await expect(page.getByText("Адаптивный поиск недоступен")).toBeVisible();
  await expect(page.getByText("Нет данных").first()).toBeVisible();
  await expectNoRawNames(page);
});

test("failed, invalid, empty and loading states remain controlled", async ({ page }) => {
  await mockJob(page, { status: "failed", retryable: true });
  await page.goto("/calculations/failed/result");
  await expect(page.getByRole("heading", { name: "Расчет завершился с ошибкой" })).toBeVisible();

  await page.goto("/calculations/invalid/result?state=invalid");
  await expect(page.getByRole("heading", { name: "Результат имеет неизвестный формат" })).toBeVisible();

  await page.goto("/calculations/empty/result?state=empty");
  await expect(page.getByRole("heading", { name: "Нет данных" })).toBeVisible();

  await page.goto("/calculations/loading/result?state=loading");
  await expect(page.getByRole("status").filter({ hasText: "Загрузка результата" })).toBeVisible();
});

test("tabs support keyboard navigation", async ({ page }) => {
  await mockJob(page);
  await page.goto("/calculations/demo-safe/result");
  const overviewTab = page.getByRole("tab", { name: "Обзор" });
  await overviewTab.focus();
  await overviewTab.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Сценарии" })).toHaveAttribute("aria-selected", "true");
});
