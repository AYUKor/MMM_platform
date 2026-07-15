import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ModelPassportV1 } from "../../entities/model-passport/types";
import { ModelPassport } from "./ModelPassport";

const passport: ModelPassportV1 = {
  contract_name: "model_passport_v1",
  schema_version: "1.0.0",
  record_origin: "synthetic_fixture",
  serving: {
    deployment_profile: "research_pilot",
    display_name: "Синтетическая исследовательская модель",
    calculation_allowed: true,
    decision_scope: "forecast_and_allocation_only",
    production_claim_allowed: false,
  },
  package: {
    registry_channel: "RAW_REGISTRY_CHANNEL",
    registry_event_id: "RAW_EVENT_ID",
    package_id: "pkg_aaaaaaaaaaaaaaaa_bbbbbbbbbbbbbbbb",
    package_fingerprint: "c".repeat(64),
    model_run_id: "RAW_MODEL_RUN",
    package_stage: "RAW_PACKAGE_STAGE",
    activation_status: "RAW_ACTIVATION_STATUS",
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
    segments: ["Сегмент А"],
    channels: ["Видео"],
    targets: [
      {
        target: "turnover_per_user",
        allowed_use_counts: { primary: 1 },
        objective_roles: ["RAW_PRIMARY_OBJECTIVE"],
      },
      {
        target: "orders_per_user",
        allowed_use_counts: { diagnostic: 1 },
        objective_roles: ["RAW_DIAGNOSTIC_ROLE"],
      },
    ],
    geographies_n: 8,
    capability_cells_n: 2,
    allowed_use_counts: { primary: 1, caution: 0, diagnostic: 1, unavailable: 0 },
    channel_policies: [
      {
        segment: "Сегмент А",
        channel: "Видео",
        target: "turnover_per_user",
        allowed_use: "primary",
        forecast_action: "RAW_FORECAST_ACTION",
        optimizer_action: "RAW_OPTIMIZER_ACTION",
        display_text: "Можно использовать для прогноза и распределения бюджета.",
      },
      {
        segment: "Сегмент А",
        channel: "Видео",
        target: "orders_per_user",
        allowed_use: "diagnostic",
        forecast_action: "RAW_DIAGNOSTIC_ACTION",
        optimizer_action: "RAW_FIXED_ACTION",
        display_text: "Заказы показываются только как диагностический показатель.",
      },
    ],
  },
  validation: {
    historical_replay: {
      status: "passed",
      generated_at_utc: "2026-07-15T10:00:00Z",
      reason_code: null,
      display_text: "Historical replay пройден.",
    },
    sealed_oot: {
      status: "unavailable",
      generated_at_utc: null,
      reason_code: "RAW_OOT_REASON",
      display_text: "Новые полные данные для sealed OOT пока недоступны.",
    },
    production_blockers: [
      { code: "RAW_PRODUCTION_BLOCKER", display_text: "Sealed OOT пока недоступен." },
    ],
  },
  caveats: [
    {
      code: "RAW_CAVEAT_CODE",
      display_text: "Рекомендация описывает распределение бюджета, а не запуск кампании.",
    },
  ],
};

describe("ModelPassport", () => {
  it("renders research/preprod boundaries and API-backed sections", () => {
    const { container } = render(<ModelPassport passport={passport} />);

    expect(screen.getByRole("heading", { name: "Исследовательская / preprod модель" })).toBeInTheDocument();
    expect(screen.getByText("Демонстрационные данные", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText(/не является решением\s+запускать/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Период обучения" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Replay и независимая OOT-проверка" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Правила использования каналов" })).toBeInTheDocument();
    expect(screen.getAllByText("Основное применение", { selector: "span" }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Только диагностика", { selector: "span" }).length).toBeGreaterThan(0);
    expect(container.textContent).not.toContain("RAW_");
    expect(container.textContent).not.toContain(passport.package.package_id);
    expect(container.textContent).not.toContain(passport.package.gate_policy_version);
  });

  it("filters target-specific policies without collapsing targets", () => {
    render(<ModelPassport passport={passport} />);
    fireEvent.change(screen.getByLabelText("Показатель"), {
      target: { value: "orders_per_user" },
    });

    expect(screen.getByText("Показано: 1")).toBeInTheDocument();
    expect(screen.getAllByText("Заказы на пользователя").length).toBeGreaterThan(0);
    expect(screen.queryByText("Можно использовать для прогноза и распределения бюджета.")).not.toBeInTheDocument();
    expect(screen.getAllByText("Заказы показываются только как диагностический показатель.").length).toBeGreaterThan(0);
  });
});
