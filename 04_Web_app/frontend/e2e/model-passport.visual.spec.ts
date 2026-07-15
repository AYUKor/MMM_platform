import { expect, test, type Page, type Route } from "@playwright/test";
import type { ModelPassportV1 } from "../src/entities/model-passport/types";

const syntheticPassport: ModelPassportV1 = {
  contract_name: "model_passport_v1",
  schema_version: "1.0.0",
  record_origin: "synthetic_fixture",
  serving: {
    deployment_profile: "research_pilot",
    display_name: "Синтетическая исследовательская MMM-модель",
    calculation_allowed: true,
    decision_scope: "forecast_and_allocation_only",
    production_claim_allowed: false,
  },
  package: {
    registry_channel: "RAW_CHANNEL",
    registry_event_id: "RAW_EVENT",
    package_id: "pkg_aaaaaaaaaaaaaaaa_bbbbbbbbbbbbbbbb",
    package_fingerprint: "c".repeat(64),
    model_run_id: "RAW_RUN",
    package_stage: "posterior_ready",
    activation_status: "preprod_restricted",
    package_schema_version: "1.0.0",
    gate_policy_version: "gate-policy-v1",
  },
  data: {
    grain: "daily",
    training_period: { start_date: "2024-01-01", end_date: "2025-03-31" },
    development_shadow_period: {
      start_date: "2025-04-01",
      end_date: "2025-06-30",
      purpose: "development_shadow_not_sealed_oot",
    },
  },
  coverage: {
    segments: ["Программа лояльности", "Онлайн"],
    channels: ["Видео", "Поиск"],
    targets: [
      { target: "turnover_per_user", allowed_use_counts: { primary: 1, caution: 1 }, objective_roles: ["RAW_OBJECTIVE"] },
      { target: "orders_per_user", allowed_use_counts: { diagnostic: 1 }, objective_roles: ["RAW_SIDE_METRIC"] },
      { target: "avg_basket", allowed_use_counts: { unavailable: 1 }, objective_roles: ["RAW_FORBIDDEN"] },
    ],
    geographies_n: 18,
    capability_cells_n: 4,
    allowed_use_counts: { primary: 1, caution: 1, diagnostic: 1, unavailable: 1 },
    channel_policies: [
      {
        segment: "Программа лояльности",
        channel: "Видео",
        target: "turnover_per_user",
        allowed_use: "primary",
        forecast_action: "RAW_FORECAST",
        optimizer_action: "RAW_OPTIMIZE",
        display_text: "Канал можно использовать для прогноза и разрешенной оптимизации.",
      },
      {
        segment: "Онлайн",
        channel: "Поиск",
        target: "turnover_per_user",
        allowed_use: "caution",
        forecast_action: "RAW_FORECAST",
        optimizer_action: "RAW_LIMITED",
        display_text: "Прогноз доступен, но увеличение бюджета требует осторожности.",
      },
      {
        segment: "Программа лояльности",
        channel: "Видео",
        target: "orders_per_user",
        allowed_use: "diagnostic",
        forecast_action: "RAW_DIAGNOSTIC",
        optimizer_action: "RAW_FIXED",
        display_text: "Заказы показываются только как диагностический показатель.",
      },
      {
        segment: "Онлайн",
        channel: "Поиск",
        target: "avg_basket",
        allowed_use: "unavailable",
        forecast_action: "RAW_BLOCKED",
        optimizer_action: "RAW_BLOCKED",
        display_text: "Средний чек недоступен для автоматического использования.",
      },
    ],
  },
  validation: {
    historical_replay: {
      status: "passed",
      generated_at_utc: "2026-07-15T10:00:00Z",
      reason_code: null,
      display_text: "Независимый historical replay пройден.",
    },
    sealed_oot: {
      status: "unavailable",
      generated_at_utc: null,
      reason_code: "RAW_OOT_REASON",
      display_text: "Новые полные данные для sealed OOT пока недоступны.",
    },
    production_blockers: [
      { code: "RAW_PRODUCTION_BLOCKER", display_text: "Sealed OOT пока недоступен из-за отсутствия полного нового периода." },
    ],
  },
  caveats: [
    { code: "RAW_RESEARCH", display_text: "Результаты предназначены для исследовательского прогнозирования." },
    { code: "RAW_ALLOCATION", display_text: "Рекомендация относится к распределению бюджета, а не к запуску кампании." },
  ],
};

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.addInitScript((value) => {
    window.localStorage.setItem("mmm-frontend-theme", value);
  }, theme);
}

async function expectNoDocumentOverflow(page: Page) {
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  )).toBe(false);
}

async function expectNoRawPassportNames(page: Page) {
  const text = await page.locator("body").innerText();
  for (const rawName of [
    "RAW_",
    "model_passport_v1",
    "forecast_and_allocation_only",
    "development_shadow_not_sealed_oot",
    "posterior_ready",
    "preprod_restricted",
    "turnover_per_user",
    "orders_per_user",
    "avg_basket",
  ]) {
    expect(text).not.toContain(rawName);
  }
}

async function mockReady(page: Page) {
  await page.route("**/api/v1/models/active", (route) => route.fulfill({ status: 200, json: syntheticPassport }));
}

for (const theme of ["dark", "light"] as const) {
  test(`Model Passport ready ${theme} desktop`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    await setTheme(page, theme);
    await mockReady(page);
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.goto("/model");
    await expect(page.getByRole("heading", { name: "Исследовательская / preprod модель" })).toBeVisible();
    await expect(page.getByText("Демонстрационные данные", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Replay и независимая OOT-проверка" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Правила использования каналов" })).toBeVisible();
    await expect(page.getByText(/не является решением\s+запускать/)).toBeVisible();
    await expectNoRawPassportNames(page);
    await expectNoDocumentOverflow(page);
    await page.screenshot({
      path: `artifacts/visual-qa/model-passport-${theme}-1440x960.png`,
      fullPage: true,
    });
    expect(consoleErrors).toEqual([]);
  });
}

test("Model Passport mobile uses policy cards without page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mockReady(page);
  await page.goto("/model");

  await expect(page.locator("table")).toBeHidden();
  await expect(page.locator("article").filter({ hasText: "Основное применение" }).first()).toBeVisible();
  await expectNoDocumentOverflow(page);
  await page.screenshot({
    path: "artifacts/visual-qa/model-passport-mobile-375x812.png",
    fullPage: true,
  });

  await page.setViewportSize({ width: 812, height: 375 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Исследовательская / preprod модель" })).toBeVisible();
  await expectNoDocumentOverflow(page);
});

test("Model Passport unavailable state is explicit and retryable", async ({ page }) => {
  await page.route("**/api/v1/models/active", (route) => route.fulfill({
    status: 503,
    json: {
      error: {
        code: "MODEL_PASSPORT_UNAVAILABLE",
        display_text: "RAW_BACKEND_UNAVAILABLE_TEXT",
        retryable: true,
        user_action: "RAW_BACKEND_ACTION",
      },
    },
  }));
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Паспорт модели временно недоступен" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Повторить запрос" })).toBeVisible();
  await expectNoRawPassportNames(page);
});

test("Model Passport rejects an unsupported contract", async ({ page }) => {
  await page.route("**/api/v1/models/active", (route) => route.fulfill({
    status: 200,
    json: { ...syntheticPassport, schema_version: "2.0.0", raw_value: "RAW_CONTRACT_VALUE" },
  }));
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Контракт паспорта не поддерживается" })).toBeVisible();
  await expect(page.getByText(/строгую проверку/)).toBeVisible();
  await expectNoRawPassportNames(page);
});

test("Model Passport error state hides backend details", async ({ page }) => {
  await page.route("**/api/v1/models/active", (route) => route.fulfill({
    status: 500,
    json: { error: { code: "RAW_INTERNAL_ERROR", display_text: "RAW_BACKEND_STACK" } },
  }));
  await page.goto("/model");
  await expect(page.getByRole("heading", { name: "Не удалось загрузить паспорт модели" })).toBeVisible();
  await expectNoRawPassportNames(page);
});

test("Model Passport loading state is announced", async ({ page }) => {
  await page.route("**/api/v1/models/active", async (route: Route) => {
    await new Promise((resolve) => setTimeout(resolve, 1_500));
    await route.fulfill({ status: 200, json: syntheticPassport });
  });
  await page.goto("/model");
  await expect(page.getByRole("status").filter({ hasText: "Загрузка паспорта модели" })).toBeVisible();
});
