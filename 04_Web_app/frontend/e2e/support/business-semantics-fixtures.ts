import type { GeoCatalogV1 } from "../../src/shared/api/generated/geo-catalog-v1";
import type { HistoricalModelGeoBudgetV1 } from "../../src/shared/api/generated/historical-model-geo-budget-v1";
import type { ModelOverviewV2 } from "../../src/shared/api/generated/model-overview-v2";
import type { ModelPassportV2 } from "../../src/shared/api/generated/model-passport-v2";
import type { WorkspaceGeoBudgetV1 } from "../../src/shared/api/generated/workspace-geo-budget-v1";

const SYNTHETIC_CONTROL_BUDGET_RUB = 267_818_706;
const SYNTHETIC_CATALOG_VERSION = "geo_catalog_v1_2026_07_18_synthetic_fixture";
const SYNTHETIC_HISTORICAL_TOTAL_BUDGET_RUB = 8_687_024_294.654741;
const SYNTHETIC_HISTORICAL_PERIOD_START = "2025-01-01";
const SYNTHETIC_HISTORICAL_PERIOD_END = "2026-05-31";

const SYNTHETIC_HISTORICAL_TOP_GEOS = [
  { geo_id: "geo_1111111111111111", geo_display_name: "Москва", latitude: 55.7558, longitude: 37.6173, budget: 1_500_000_000 },
  { geo_id: "geo_2222222222222222", geo_display_name: "Санкт-Петербург", latitude: 59.9386, longitude: 30.3141, budget: 1_100_000_000 },
  { geo_id: "geo_3333333333333333", geo_display_name: "Московская область", latitude: 55.5794, longitude: 36.7071, budget: 800_000_000 },
  { geo_id: "geo_4444444444444444", geo_display_name: "Екатеринбург", latitude: 56.8389, longitude: 60.6057, budget: 500_000_000 },
  { geo_id: "geo_5555555555555555", geo_display_name: "Нижний Новгород", latitude: 56.2965, longitude: 43.9361, budget: 400_000_000 },
  { geo_id: "geo_6666666666666666", geo_display_name: "Казань", latitude: 55.7963, longitude: 49.1088, budget: 350_000_000 },
  { geo_id: "geo_7777777777777777", geo_display_name: "Самара", latitude: 53.1959, longitude: 50.1002, budget: 300_000_000 },
  { geo_id: "geo_8888888888888888", geo_display_name: "Новосибирск", latitude: 55.0084, longitude: 82.9357, budget: 250_000_000 },
  { geo_id: "geo_9999999999999999", geo_display_name: "Краснодар", latitude: 45.0355, longitude: 38.9753, budget: 200_000_000 },
  { geo_id: "geo_aaaaaaaaaaaaaaaa", geo_display_name: "Воронеж", latitude: 51.6608, longitude: 39.2003, budget: 150_000_000 },
] as const;

const SYNTHETIC_CONTROL_GEOS = [
  { geo_id: "geo_84e5fcec31012b88", geo_display_name: "Волгоград", latitude: 48.71378, longitude: 44.4976, region_id: "region_geonames_472755", region_display_name: "Волгоградская область" },
  { geo_id: "geo_c5bbbb417c2f21f1", geo_display_name: "Воронеж", latitude: 51.66833, longitude: 39.19204, region_id: "region_geonames_472039", region_display_name: "Воронежская область" },
  { geo_id: "geo_603847d7490bba77", geo_display_name: "Краснодар", latitude: 45.04534, longitude: 38.98178, region_id: "region_geonames_542415", region_display_name: "Краснодарский край" },
  { geo_id: "geo_93a89aa2fbcf50f7", geo_display_name: "Красноярск", latitude: 56.03742, longitude: 92.93136, region_id: "region_geonames_1502020", region_display_name: "Красноярский край" },
  { geo_id: "geo_ae4b572fa4c02f42", geo_display_name: "Новосибирск", latitude: 55.02259, longitude: 82.93175, region_id: "region_geonames_1496745", region_display_name: "Новосибирская область" },
  { geo_id: "geo_093a1766328e66ca", geo_display_name: "Омск", latitude: 54.99244, longitude: 73.36859, region_id: "region_geonames_1496152", region_display_name: "Омская область" },
  { geo_id: "geo_654946621661ed59", geo_display_name: "Ростов-на-Дону", latitude: 47.21997, longitude: 39.70769, region_id: "region_geonames_501165", region_display_name: "Ростовская область" },
  { geo_id: "geo_2a7d6797adab975f", geo_display_name: "Самара", latitude: 53.20767, longitude: 50.13553, region_id: "region_geonames_499068", region_display_name: "Самарская область" },
  { geo_id: "geo_94835d40a52e5a3a", geo_display_name: "Санкт-Петербург", latitude: 59.93863, longitude: 30.31413, region_id: "region_geonames_536203", region_display_name: "Санкт-Петербург" },
  { geo_id: "geo_5fa9084303383362", geo_display_name: "Саратов", latitude: 51.54048, longitude: 45.9901, region_id: "region_geonames_498671", region_display_name: "Саратовская область" },
  { geo_id: "geo_6de565131413b901", geo_display_name: "Тюмень", latitude: 57.15222, longitude: 65.52722, region_id: "region_geonames_1488747", region_display_name: "Тюменская область" },
  { geo_id: "geo_965336b61d1b679c", geo_display_name: "Уфа", latitude: 54.74306, longitude: 55.96779, region_id: "region_geonames_578853", region_display_name: "Республика Башкортостан" },
  { geo_id: "geo_b25fd4fb102fd0bb", geo_display_name: "Чебоксары", latitude: 56.13218, longitude: 47.246, region_id: "region_geonames_567395", region_display_name: "Чувашская Республика" },
  { geo_id: "geo_5d01870a3a173190", geo_display_name: "Челябинск", latitude: 55.1611, longitude: 61.42877, region_id: "region_geonames_1508290", region_display_name: "Челябинская область" },
  { geo_id: "geo_212302479b4c065e", geo_display_name: "Ярославль", latitude: 57.62987, longitude: 39.87368, region_id: "region_geonames_468898", region_display_name: "Ярославская область" },
] as const;

const SYNTHETIC_CONTROL_GEO_BUDGETS = [
  25_000_000,
  24_000_000,
  23_000_000,
  22_000_000,
  21_000_000,
  20_000_000,
  19_000_000,
  18_000_000,
  17_000_000,
  16_000_000,
  15_000_000,
  14_000_000,
  13_000_000,
  12_000_000,
  8_818_706,
] as const;

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
    catalog_version: SYNTHETIC_CATALOG_VERSION,
    coordinates_source: "GeoNames RU dump (WGS84) — synthetic fixture subset",
    coordinates_source_version_or_date: "2026-07-18",
    coordinates_license: "CC BY 4.0",
    status: "available",
    display_text: "Синтетическая фикстура: координаты 15 географий доступны.",
    geographies_n: SYNTHETIC_CONTROL_GEOS.length,
    coverage: {
      status: "available",
      located_geographies_n: SYNTHETIC_CONTROL_GEOS.length,
      unlocated_geographies_n: 0,
      unlocated_geographies: [],
    },
    entries: SYNTHETIC_CONTROL_GEOS.map((geo) => ({
      ...geo,
      coordinates_status: "canonical" as const,
    })),
  };
}

export function createWorkspaceGeoBudgetFixture(): WorkspaceGeoBudgetV1 {
  return {
    contract_name: "workspace_geo_budget_v1",
    schema_version: "1.0.0",
    catalog_version: SYNTHETIC_CATALOG_VERSION,
    status: "available",
    display_text: "Синтетическая фикстура: бюджет по 15 географиям доступен.",
    total_budget_rub: SYNTHETIC_CONTROL_BUDGET_RUB,
    campaigns_n: 1,
    geographies_n: SYNTHETIC_CONTROL_GEOS.length,
    coverage: {
      status: "available",
      located_geographies_n: SYNTHETIC_CONTROL_GEOS.length,
      unlocated_geographies_n: 0,
      unlocated_geographies: [],
      located_budget_rub: SYNTHETIC_CONTROL_BUDGET_RUB,
      unlocated_budget_rub: 0,
      unlocated_budget_share: 0,
    },
    rows: SYNTHETIC_CONTROL_GEOS.map((geo, index) => ({
      ...geo,
      coordinates_status: "canonical" as const,
      total_budget_rub: SYNTHETIC_CONTROL_GEO_BUDGETS[index],
      campaigns_n: 1,
      budget_share: SYNTHETIC_CONTROL_GEO_BUDGETS[index] / SYNTHETIC_CONTROL_BUDGET_RUB,
    })),
  };
}

export function createHistoricalModelGeoBudgetFixture(): HistoricalModelGeoBudgetV1 {
  const tailCount = 220 - SYNTHETIC_HISTORICAL_TOP_GEOS.length;
  const topBudget = SYNTHETIC_HISTORICAL_TOP_GEOS.reduce((sum, geo) => sum + geo.budget, 0);
  const tailBudget = (SYNTHETIC_HISTORICAL_TOTAL_BUDGET_RUB - topBudget) / tailCount;
  const tailRows = Array.from({ length: tailCount }, (_, index) => ({
    geo_id: `geo_${(index + 11).toString(16).padStart(16, "0")}`,
    geo_display_name: `Тестовая география ${String(index + 11).padStart(3, "0")}`,
    latitude: 44 + (Math.floor(index / 21) % 10) * 3,
    longitude: 32 + (index % 21) * 5.2,
    coordinates_status: "canonical" as const,
    historical_total_budget_rub: tailBudget,
    budget_share: tailBudget / SYNTHETIC_HISTORICAL_TOTAL_BUDGET_RUB,
    active_days_n: 35 + (index % 310),
    active_rows_n: 90 + (index % 310) * 2,
  }));
  const rows: HistoricalModelGeoBudgetV1["rows"] = [
    ...SYNTHETIC_HISTORICAL_TOP_GEOS.map((geo, index) => ({
      geo_id: geo.geo_id,
      geo_display_name: geo.geo_display_name,
      latitude: geo.latitude,
      longitude: geo.longitude,
      coordinates_status: "canonical" as const,
      historical_total_budget_rub: geo.budget,
      budget_share: geo.budget / SYNTHETIC_HISTORICAL_TOTAL_BUDGET_RUB,
      active_days_n: 480 - index * 18,
      active_rows_n: 1_200 - index * 25,
    })),
    ...tailRows,
  ];
  const rowBudget = rows.reduce((sum, row) => sum + row.historical_total_budget_rub, 0);
  const finalRow = rows.at(-1);
  if (!finalRow) throw new Error("Historical fixture requires rows.");
  finalRow.historical_total_budget_rub += SYNTHETIC_HISTORICAL_TOTAL_BUDGET_RUB - rowBudget;
  finalRow.budget_share = finalRow.historical_total_budget_rub
    / SYNTHETIC_HISTORICAL_TOTAL_BUDGET_RUB;

  return {
    contract_name: "historical_model_geo_budget_v1",
    schema_version: "1.0.0",
    record_origin: "verified_model_package_artifact",
    status: "available",
    title: "Исторический рекламный бюджет в данных модели",
    display_text: "Исторические расходы доступны для всех географий.",
    period_display_text: "Период данных: 01.01.2025 — 31.05.2026",
    package_id: "pkg_synthetic_historical_home_map_v1",
    model_version: "model-synthetic-e1f-v1",
    artifact_id: "artifact_111111111111111111111111",
    artifact_version: "historical_geo_budget_v1",
    catalog_version: SYNTHETIC_CATALOG_VERSION,
    period_start: SYNTHETIC_HISTORICAL_PERIOD_START,
    period_end: SYNTHETIC_HISTORICAL_PERIOD_END,
    spend_columns_version: "spend-columns-synthetic-v1",
    total_budget_rub: SYNTHETIC_HISTORICAL_TOTAL_BUDGET_RUB,
    geographies_n: rows.length,
    coverage: {
      status: "available",
      located_geographies_n: rows.length,
      unlocated_geographies_n: 0,
      unlocated_geographies: [],
      located_budget_rub: SYNTHETIC_HISTORICAL_TOTAL_BUDGET_RUB,
      unlocated_budget_rub: 0,
      unlocated_budget_share: 0,
    },
    rows,
    limitations: [
      { code: "historical_spend_only", display_text: "Показаны фактические рекламные расходы из данных активной модели." },
      { code: "activity_not_launch_count", display_text: "Активные строки и дни отражают наблюдения с расходами, а не число отдельных запусков." },
      { code: "point_coordinates", display_text: "Координаты показывают точки географий, а не их административные границы." },
    ],
    updated_at_utc: "2026-07-19T09:00:00Z",
  };
}

export function createPartialHistoricalModelGeoBudgetFixture(): HistoricalModelGeoBudgetV1 {
  const source = createHistoricalModelGeoBudgetFixture();
  const rows = source.rows.map((row, index) => index === source.rows.length - 1
    ? {
      ...row,
      latitude: null,
      longitude: null,
      coordinates_status: "unavailable" as const,
    }
    : row);
  const unlocated = rows.at(-1);
  if (!unlocated || source.total_budget_rub === null) {
    throw new Error("Historical partial fixture requires an available source.");
  }
  return {
    ...source,
    status: "partial",
    display_text: "Часть исторического бюджета не привязана к утвержденным координатам.",
    coverage: {
      status: "partial",
      located_geographies_n: rows.length - 1,
      unlocated_geographies_n: 1,
      unlocated_geographies: [{
        geo_id: unlocated.geo_id,
        geo_display_name: unlocated.geo_display_name,
      }],
      located_budget_rub: source.total_budget_rub - unlocated.historical_total_budget_rub,
      unlocated_budget_rub: unlocated.historical_total_budget_rub,
      unlocated_budget_share: unlocated.budget_share,
    },
    rows,
    limitations: [
      ...source.limitations,
      { code: "unlocated_historical_budget", display_text: "Бюджет без утвержденных координат сохранен в результате и показан отдельно." },
    ],
  };
}

export function createUnavailableHistoricalModelGeoBudgetFixture(): HistoricalModelGeoBudgetV1 {
  const source = createHistoricalModelGeoBudgetFixture();
  return {
    ...source,
    record_origin: "model_package_artifact_unavailable",
    status: "unavailable",
    display_text: "Исторические расходы активной модели временно недоступны.",
    period_display_text: "Период данных временно недоступен.",
    model_version: null,
    artifact_id: null,
    artifact_version: null,
    period_start: null,
    period_end: null,
    spend_columns_version: null,
    total_budget_rub: null,
    geographies_n: 0,
    coverage: {
      status: "unavailable",
      located_geographies_n: 0,
      unlocated_geographies_n: 0,
      unlocated_geographies: [],
      located_budget_rub: 0,
      unlocated_budget_rub: 0,
      unlocated_budget_share: null,
    },
    rows: [],
    limitations: [{
      code: "historical_artifact_unavailable",
      display_text: "Подтвержденный исторический агрегат для выбранной модели пока не опубликован.",
    }],
    updated_at_utc: null,
  };
}
