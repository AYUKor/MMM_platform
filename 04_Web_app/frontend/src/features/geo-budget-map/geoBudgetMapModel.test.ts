import { describe, expect, it } from "vitest";

import type { HistoricalModelGeoBudgetV1 } from "../../shared/api/generated/historical-model-geo-budget-v1";
import type { ValidationResultV2 } from "../../shared/api/generated/validation-result-v2";
import { TEST_GEO_CATALOG } from "../../test/businessSemanticsV2Fixtures";
import {
  InvalidGeoBudgetMapDataError,
  adaptHistoricalModelGeoBudget,
  adaptValidationGeoBudget,
  bubbleBrightness,
  bubbleRadius,
  formatGeoPointAccessibleLabel,
  layoutMapLabels,
  projectGeoPoint,
  selectLabelIds,
  sortPointsForPaint,
  type GeoBudgetMapPoint,
} from "./geoBudgetMapModel";

const HISTORICAL_TOTAL_BUDGET = 8_687_024_294.654741;

const historicalCanonical = {
  geo_id: "geo_moscow",
  geo_display_name: "Москва",
  latitude: 55.7558,
  longitude: 37.6173,
  coordinates_status: "canonical",
  historical_total_budget_rub: 7_000_000_000,
  budget_share: 7_000_000_000 / HISTORICAL_TOTAL_BUDGET,
  active_days_n: 500,
  active_rows_n: 600,
} as const;

const historicalUnavailable = {
  geo_id: "geo_unknown",
  geo_display_name: "Неизвестный город",
  latitude: null,
  longitude: null,
  coordinates_status: "unavailable",
  historical_total_budget_rub: HISTORICAL_TOTAL_BUDGET - 7_000_000_000,
  budget_share: (HISTORICAL_TOTAL_BUDGET - 7_000_000_000) / HISTORICAL_TOTAL_BUDGET,
  active_days_n: 300,
  active_rows_n: 400,
} as const;

function historicalPayload(): HistoricalModelGeoBudgetV1 {
  return {
    contract_name: "historical_model_geo_budget_v1",
    schema_version: "1.0.0",
    record_origin: "verified_model_package_artifact",
    status: "partial",
    title: "Исторический рекламный бюджет в данных модели",
    display_text: "Часть исторического бюджета не привязана к карте.",
    period_display_text: "Период данных: 01.01.2025 — 31.05.2026",
    package_id: "pkg_test_historical_model",
    model_version: "model_test_v1",
    artifact_id: "artifact_0123456789abcdef01234567",
    artifact_version: "historical_geo_budget_v1",
    catalog_version: "geo_catalog_v1_test",
    period_start: "2025-01-01",
    period_end: "2026-05-31",
    spend_columns_version: "spend_columns_v1",
    total_budget_rub: HISTORICAL_TOTAL_BUDGET,
    geographies_n: 2,
    coverage: {
      status: "partial",
      located_geographies_n: 1,
      unlocated_geographies_n: 1,
      unlocated_geographies: [{ geo_id: "geo_unknown", geo_display_name: "Неизвестный город" }],
      located_budget_rub: 7_000_000_000,
      unlocated_budget_rub: HISTORICAL_TOTAL_BUDGET - 7_000_000_000,
      unlocated_budget_share: (HISTORICAL_TOTAL_BUDGET - 7_000_000_000) / HISTORICAL_TOTAL_BUDGET,
    },
    rows: [historicalCanonical, historicalUnavailable],
    limitations: [],
    updated_at_utc: "2026-07-19T10:00:00Z",
  };
}

const validationCanonical: Extract<ValidationResultV2["geo_points"][number], { coordinates_status: "canonical" }> = {
  geo_id: "geo_kazan",
  geo_display_name: "Казань",
  input_geo_name: "Казань",
  canonical_geo_id: "geo_kazan",
  canonical_geo_display_name: "Казань",
  normalization_status: "canonical",
  normalization_rule: "canonical_exact",
  latitude: 55.7963,
  longitude: 49.1088,
  coordinates_status: "canonical",
  region_id: "region_tatarstan",
  region_display_name: "Республика Татарстан",
  budget_rub: 180,
  budget_share: 0.6,
  channels: [
    { channel_id: "Digital_Performance", channel_display_name: "Цифровая реклама" },
    { channel_id: "Radio", channel_display_name: "Радио" },
  ],
  has_model_limitations: true,
  model_limitations_n: 2,
};

const validationUnavailable: Extract<ValidationResultV2["geo_points"][number], { coordinates_status: "unavailable" }> = {
  geo_id: "geo_input_unknown",
  geo_display_name: "Город из файла",
  input_geo_name: "Город из файла",
  canonical_geo_id: null,
  canonical_geo_display_name: null,
  normalization_status: "unknown",
  normalization_rule: "no_registered_alias",
  latitude: null,
  longitude: null,
  coordinates_status: "unavailable",
  region_id: null,
  region_display_name: null,
  budget_rub: 120,
  budget_share: 0.4,
  channels: [{ channel_id: "OOH_Total", channel_display_name: "Наружная реклама" }],
  has_model_limitations: false,
  model_limitations_n: 0,
};

function validationPayload(): ValidationResultV2 {
  return {
    contract_name: "validation_result_v2",
    schema_version: "2.0.0",
    validation_id: "validation_1234567890ab",
    status: "warning",
    job_creation_allowed: true,
    file_validation: {
      status: "passed",
      rows_n: 3,
      campaigns_n: 1,
      geographies_n: 2,
      channels_n: 3,
      requested_budget_rub: 300,
      blocking_errors_n: 0,
      warnings_n: 1,
      checks: [],
    },
    model_limitations: [],
    map_coverage: {
      status: "partial",
      located_geographies_n: 1,
      unlocated_geographies_n: 1,
      unlocated_geographies: [{ geo_id: "geo_input_unknown", geo_display_name: "Город из файла" }],
      located_budget_rub: 180,
      unlocated_budget_rub: 120,
      unlocated_budget_share: 0.4,
    },
    geo_points: [validationCanonical, validationUnavailable],
  };
}

function mapPoint(overrides: Partial<GeoBudgetMapPoint> = {}): GeoBudgetMapPoint {
  return {
    geoId: "geo_default",
    geoDisplayName: "Москва",
    latitude: 55.7558,
    longitude: 37.6173,
    budgetRub: 100,
    budgetShare: 0.5,
    ...overrides,
  };
}

describe("fixed geo projection", () => {
  it("keeps known cities at stable coordinates independent of campaign data", () => {
    expect(projectGeoPoint(55.7558, 37.6173)).toEqual({
      x: expect.closeTo(199.70685125277038, 8),
      y: expect.closeTo(289.4214052377923, 8),
    });
    expect(projectGeoPoint(54.7104, 20.4522)).toEqual({
      x: expect.closeTo(108.9592188691779, 8),
      y: expect.closeTo(172.8245980711422, 8),
    });
    expect(projectGeoPoint(43.1155, 131.8855)).toEqual({
      x: expect.closeTo(1006.674685359224, 8),
      y: expect.closeTo(625.7811077709276, 8),
    });
  });

  it("wraps the antimeridian and fails closed for malformed WGS84 coordinates", () => {
    expect(projectGeoPoint(65, 180)).toEqual(projectGeoPoint(65, -180));
    expect(projectGeoPoint(Number.NaN, 37)).toBeNull();
    expect(projectGeoPoint(91, 37)).toBeNull();
    expect(projectGeoPoint(55, 181)).toBeNull();
  });
});

describe("bubble presentation scale", () => {
  it("uses square-root scaling with the approved desktop and mobile limits", () => {
    expect(bubbleRadius(100, 100)).toBe(22);
    expect(bubbleRadius(25, 100)).toBe(13.5);
    expect(bubbleRadius(100, 100, true)).toBe(16);
    expect(bubbleRadius(25, 100, true)).toBe(10);
    expect(bubbleRadius(0.01, 100)).toBeGreaterThan(5);
  });

  it("does not draw zero or malformed budgets and clamps values above the presentation maximum", () => {
    expect(bubbleRadius(0, 100)).toBe(0);
    expect(bubbleRadius(-1, 100)).toBe(0);
    expect(bubbleRadius(Number.NaN, 100)).toBe(0);
    expect(bubbleRadius(10, 0)).toBe(0);
    expect(bubbleRadius(200, 100)).toBe(22);
  });

  it("derives brightness from the same square-root scale", () => {
    expect(bubbleBrightness(100, 100)).toBe(1);
    expect(bubbleBrightness(25, 100)).toBeCloseTo(0.71, 10);
    expect(bubbleBrightness(0, 100)).toBe(0);
    expect(bubbleBrightness(Number.POSITIVE_INFINITY, 100)).toBe(0);
  });
});

describe("deterministic map ordering and labels", () => {
  it("paints small budgets first and resolves budget ties by display name", () => {
    const source = [
      mapPoint({ geoId: "large", geoDisplayName: "Москва", budgetRub: 300 }),
      mapPoint({ geoId: "small-z", geoDisplayName: "Ярославль", budgetRub: 100 }),
      mapPoint({ geoId: "small-a", geoDisplayName: "Анапа", budgetRub: 100 }),
    ];
    expect(sortPointsForPaint(source).map((point) => point.geoId)).toEqual(["small-a", "small-z", "large"]);
    expect(source.map((point) => point.geoId)).toEqual(["large", "small-z", "small-a"]);
  });

  it("selects exactly the historical top ten with deterministic boundary ties", () => {
    const points = Array.from({ length: 11 }, (_, index) => mapPoint({
      geoId: `geo_${index}`,
      geoDisplayName: index === 9 ? "Анапа" : index === 10 ? "Ярославль" : `Город ${index}`,
      budgetRub: index < 9 ? 100 - index : 10,
    }));
    const labels = selectLabelIds("historical-model", points);
    expect(labels).toHaveLength(10);
    expect(labels.has("geo_9")).toBe(true);
    expect(labels.has("geo_10")).toBe(false);
  });

  it("selects every located campaign point", () => {
    const points = [mapPoint({ geoId: "one" }), mapPoint({ geoId: "two", budgetRub: 0 })];
    expect([...selectLabelIds("campaign", points)]).toEqual(["one", "two"]);
  });

  it("places dense desktop labels inside the fixed canvas without collisions", () => {
    const inputs = TEST_GEO_CATALOG.map((geo) => {
      const projected = projectGeoPoint(geo.latitude, geo.longitude);
      if (!projected) throw new Error("Test catalog coordinates must project.");
      return { ...projected, geoId: geo.geo_id, geoDisplayName: geo.geo_display_name, radius: 22 };
    });
    const layout = layoutMapLabels(inputs, 1100);
    expect(layout).toHaveLength(15);
    const positions = [...layout.values()];
    for (const position of positions) {
      expect(position.x - position.width / 2).toBeGreaterThanOrEqual(0);
      expect(position.x + position.width / 2).toBeLessThanOrEqual(1200);
      expect(position.y - position.height / 2).toBeGreaterThanOrEqual(0);
      expect(position.y + position.height / 2).toBeLessThanOrEqual(680);
    }
    for (let leftIndex = 0; leftIndex < positions.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < positions.length; rightIndex += 1) {
        const left = positions[leftIndex];
        const right = positions[rightIndex];
        const overlapX = Math.min(left.x + left.width / 2, right.x + right.width / 2)
          - Math.max(left.x - left.width / 2, right.x - right.width / 2);
        const overlapY = Math.min(left.y + left.height / 2, right.y + right.height / 2)
          - Math.max(left.y - left.height / 2, right.y - right.height / 2);
        expect(overlapX > 0 && overlapY > 0).toBe(false);
      }
    }
  });
});

describe("contract adapters", () => {
  it("maps only canonical historical rows and preserves exact server totals, period and coverage", () => {
    const payload = historicalPayload();
    const model = adaptHistoricalModelGeoBudget(payload);

    expect(model).toMatchObject({
      mode: "historical-model",
      title: "Исторический рекламный бюджет в данных модели",
      periodDisplayText: "Период данных: 01.01.2025 — 31.05.2026",
      totalBudgetRub: HISTORICAL_TOTAL_BUDGET,
      geographiesN: 2,
      maxBudgetRub: 7_000_000_000,
      coverage: {
        status: "partial",
        locatedBudgetRub: 7_000_000_000,
        unlocatedBudgetRub: HISTORICAL_TOTAL_BUDGET - 7_000_000_000,
        unlocatedGeographies: [{ geoId: "geo_unknown", geoDisplayName: "Неизвестный город" }],
      },
    });
    expect(model.points).toEqual([expect.objectContaining({
      geoId: "geo_moscow",
      budgetRub: 7_000_000_000,
      activeDaysN: 500,
      activeRowsN: 600,
    })]);
    expect(model.points.some((point) => point.geoId === "geo_unknown")).toBe(false);
    expect(model.points[0]).not.toHaveProperty("campaignsN");
  });

  it("preserves controlled historical artifact unavailability without workspace-derived values", () => {
    const payload = historicalPayload();
    payload.record_origin = "model_package_artifact_unavailable";
    payload.status = "unavailable";
    payload.display_text = "Исторический артефакт модели пока недоступен.";
    payload.period_display_text = "Период данных недоступен";
    payload.model_version = null;
    payload.artifact_id = null;
    payload.artifact_version = null;
    payload.period_start = null;
    payload.period_end = null;
    payload.spend_columns_version = null;
    payload.total_budget_rub = null;
    payload.geographies_n = 0;
    payload.coverage = {
      status: "unavailable",
      located_geographies_n: 0,
      unlocated_geographies_n: 0,
      unlocated_geographies: [],
      located_budget_rub: 0,
      unlocated_budget_rub: 0,
      unlocated_budget_share: null,
    };
    payload.rows = [];
    payload.updated_at_utc = null;

    const model = adaptHistoricalModelGeoBudget(payload);
    expect(model).toMatchObject({
      mode: "historical-model",
      totalBudgetRub: null,
      geographiesN: 0,
      points: [],
      maxBudgetRub: 0,
      coverage: { status: "unavailable" },
    });
  });

  it("maps campaign display fields without a frontend geo or channel dictionary", () => {
    const model = adaptValidationGeoBudget(validationPayload());
    expect(model).toMatchObject({
      mode: "campaign",
      validationId: "validation_1234567890ab",
      requestedBudgetRub: 300,
      geographiesN: 2,
      maxBudgetRub: 180,
      coverage: {
        status: "partial",
        unlocatedBudgetRub: 120,
        unlocatedBudgetShare: 0.4,
      },
    });
    expect(model.points).toEqual([expect.objectContaining({
      geoId: "geo_kazan",
      geoDisplayName: "Казань",
      channels: ["Цифровая реклама", "Радио"],
      hasModelLimitations: true,
      modelLimitationsN: 2,
    })]);
    expect(model.points.some((point) => point.geoId === "geo_input_unknown")).toBe(false);
  });

  it("preserves controlled unavailable coverage without guessing coordinates", () => {
    const payload = validationPayload();
    payload.geo_points = [validationUnavailable];
    payload.map_coverage = {
      ...payload.map_coverage,
      status: "unavailable",
      located_geographies_n: 0,
      unlocated_geographies_n: 1,
      located_budget_rub: 0,
      unlocated_budget_rub: 300,
      unlocated_budget_share: 1,
    };
    const model = adaptValidationGeoBudget(payload);
    expect(model.points).toEqual([]);
    expect(model.maxBudgetRub).toBe(0);
    expect(model.coverage).toMatchObject({ status: "unavailable", unlocatedBudgetRub: 300 });
  });

  it("fails closed when a canonical point contains malformed numeric data", () => {
    const payload = validationPayload();
    const point = payload.geo_points[0];
    if (point.coordinates_status !== "canonical") throw new Error("Test fixture must be canonical.");
    point.latitude = Number.NaN;
    expect(() => adaptValidationGeoBudget(payload)).toThrow(InvalidGeoBudgetMapDataError);
    expect(() => sortPointsForPaint([mapPoint({ budgetRub: -1 })])).toThrow(InvalidGeoBudgetMapDataError);
  });
});

describe("accessible point copy", () => {
  it("formats historical and campaign tooltip content without raw identifiers", () => {
    const historicalLabel = formatGeoPointAccessibleLabel(
      "historical-model",
      mapPoint({ activeDaysN: 500, activeRowsN: 600 }),
      "Период данных: 01.01.2025 — 31.05.2026",
    );
    expect(historicalLabel).toContain("Москва");
    expect(historicalLabel).toContain("Исторический рекламный бюджет");
    expect(historicalLabel).toContain("Доля общего бюджета");
    expect(historicalLabel).not.toContain("Дней с рекламной активностью");
    expect(historicalLabel).toContain("Период данных: 01.01.2025 — 31.05.2026");
    expect(historicalLabel).not.toContain("Кампаний");

    const campaignLabel = formatGeoPointAccessibleLabel("campaign", mapPoint({
      channels: ["Цифровая реклама", "Радио"],
      hasModelLimitations: true,
      modelLimitationsN: 2,
    }));
    expect(campaignLabel).toContain("Каналы: Цифровая реклама, Радио");
    expect(campaignLabel).toContain("Ограничения модели: 2");
    expect(campaignLabel).not.toContain("Digital_Performance");

    expect(formatGeoPointAccessibleLabel("campaign", mapPoint()))
      .toContain("Ограничения модели: Нет данных");
  });
});
