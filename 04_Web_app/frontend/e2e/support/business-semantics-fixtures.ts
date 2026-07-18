import type { GeoCatalogV1 } from "../../src/shared/api/generated/geo-catalog-v1";
import type { ModelOverviewV2 } from "../../src/shared/api/generated/model-overview-v2";
import type { ModelPassportV2 } from "../../src/shared/api/generated/model-passport-v2";
import type { WorkspaceGeoBudgetV1 } from "../../src/shared/api/generated/workspace-geo-budget-v1";

export function createModelPassportV2Fixture(): ModelPassportV2 {
  return {
    contract_name: "model_passport_v2",
    schema_version: "2.0.0",
    record_origin: "synthetic_fixture",
    serving: {
      serving_policy_version: "turnover_serving_v1",
      target_id: "turnover",
      core_target: "turnover_per_user",
      serving_targets_n: 1,
      active_serving_models_n: 4,
      research_models_in_package_n: 12,
      calculation_allowed: true,
      production_claim_allowed: false,
    },
    package: {
      registry_channel: "preprod",
      registry_event_id: "registry_event_synthetic",
      package_id: "pkg_1111111111111111_2222222222222222",
      package_fingerprint: "a".repeat(64),
      model_run_id: "run_synthetic",
      package_stage: "posterior_ready",
      activation_status: "preprod_restricted",
      package_schema_version: "1.0.0",
      gate_policy_version: "gate-v1",
    },
    data: {
      grain: "daily",
      training_period: { start_date: "2023-01-01", end_date: "2025-12-31" },
      development_shadow_period: {
        start_date: "2026-01-01",
        end_date: "2026-03-31",
        purpose: "development_shadow_not_sealed_oot",
      },
    },
    coverage: {
      segments: ["ТС5/Онлайн"],
      channels: [
        { channel_id: "Digital_Performance", channel_display_name: "Цифровая реклама" },
        { channel_id: "OOH_Total", channel_display_name: "Наружная реклама" },
        { channel_id: "Радио", channel_display_name: "Радио" },
        { channel_id: "Indoor", channel_display_name: "Indoor" },
      ],
      targets: [{ target_id: "turnover", core_target: "turnover_per_user" }],
      geographies_n: 15,
      capability_cells_n: 4,
    },
    validation: {
      historical_replay: {
        status: "passed",
        generated_at_utc: "2026-07-17T10:00:00Z",
        reason_code: null,
        display_text: "Historical replay пройден.",
      },
      sealed_oot: {
        status: "unavailable",
        generated_at_utc: null,
        reason_code: "not_available",
        display_text: "Sealed OOT пока недоступен.",
      },
      production_blockers: [{
        code: "research_preprod",
        display_text: "Модель не утверждена для production-использования.",
      }],
    },
    channel_policies: [
      {
        segment: "ТС5/Онлайн",
        channel_id: "Digital_Performance",
        channel_display_name: "Цифровая реклама",
        target: "turnover",
        allowed_use: "primary",
        forecast_action: "forecast",
        optimizer_action: "optimize",
        display_text: "Канал доступен в подтвержденной зоне.",
      },
      {
        segment: "ТС5/Онлайн",
        channel_id: "OOH_Total",
        channel_display_name: "Наружная реклама",
        target: "turnover",
        allowed_use: "caution",
        forecast_action: "forecast",
        optimizer_action: "review",
        display_text: "Канал требует ручной проверки границ.",
      },
    ],
    caveats: [{
      code: "allocation_only",
      display_text: "Рекомендация относится только к распределению бюджета.",
    }],
  };
}

export function createModelOverviewV2Fixture(
  passport = createModelPassportV2Fixture(),
): ModelOverviewV2 {
  return {
    contract_name: "model_overview_v2",
    schema_version: "2.0.0",
    serving: { ...passport.serving },
    summary: {
      training_period: { ...passport.data.training_period },
      package_status: passport.package.package_stage,
      activation_status: passport.package.activation_status,
      calculation_allowed: passport.serving.calculation_allowed,
      historical_replay: { ...passport.validation.historical_replay },
      sealed_oot: { ...passport.validation.sealed_oot },
    },
    channel_policies: passport.channel_policies.map((item) => ({ ...item })),
    limitations: [{
      code: "allocation_only",
      status: "active",
      title: "Рекомендация только по распределению",
      display_text: "Система не принимает решение о запуске кампании.",
      recommended_action: "Сопоставьте результат с бизнес-целями.",
    }],
  };
}

export function createGeoCatalogFixture(): GeoCatalogV1 {
  return {
    contract_name: "geo_catalog_v1",
    schema_version: "1.0.0",
    catalog_version: "catalog-synthetic-v1",
    status: "unavailable",
    display_text: "Координаты пока не опубликованы.",
    geographies_n: 2,
    entries: [
      {
        geo_id: "geo_1111111111111111",
        geo_display_name: "Москва",
        latitude: null,
        longitude: null,
        coordinates_status: "unavailable",
        region_id: null,
        region_display_name: null,
      },
      {
        geo_id: "geo_2222222222222222",
        geo_display_name: "Казань",
        latitude: null,
        longitude: null,
        coordinates_status: "unavailable",
        region_id: null,
        region_display_name: null,
      },
    ],
  };
}

export function createWorkspaceGeoBudgetFixture(): WorkspaceGeoBudgetV1 {
  return {
    contract_name: "workspace_geo_budget_v1",
    schema_version: "1.0.0",
    catalog_version: "catalog-synthetic-v1",
    status: "unavailable",
    display_text: "Сводка готова без координат.",
    total_budget_rub: 12_000_000,
    campaigns_n: 2,
    geographies_n: 2,
    rows: [
      {
        geo_id: "geo_1111111111111111",
        geo_display_name: "Москва",
        latitude: null,
        longitude: null,
        coordinates_status: "unavailable",
        total_budget_rub: 7_000_000,
        campaigns_n: 2,
        budget_share: 7 / 12,
      },
      {
        geo_id: "geo_2222222222222222",
        geo_display_name: "Казань",
        latitude: null,
        longitude: null,
        coordinates_status: "unavailable",
        total_budget_rub: 5_000_000,
        campaigns_n: 1,
        budget_share: 5 / 12,
      },
    ],
  };
}
