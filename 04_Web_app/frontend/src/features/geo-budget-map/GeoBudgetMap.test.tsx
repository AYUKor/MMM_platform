import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { HistoricalModelGeoBudgetV1 } from "../../shared/api/generated/historical-model-geo-budget-v1";
import {
  buildValidationResultV2,
  CONTROL_REQUESTED_BUDGET,
  TEST_GEO_CATALOG,
} from "../../test/businessSemanticsV2Fixtures";
import { GeoBudgetMap } from "./GeoBudgetMap";
import {
  adaptHistoricalModelGeoBudget,
  adaptValidationGeoBudget,
  type GeoBudgetMapModel,
} from "./geoBudgetMapModel";

function historicalPayload(): HistoricalModelGeoBudgetV1 {
  const budgets = TEST_GEO_CATALOG.map((_, index) => (TEST_GEO_CATALOG.length - index) * 10_000_000);
  const total = budgets.reduce((sum, budget) => sum + budget, 0);
  return {
    contract_name: "historical_model_geo_budget_v1",
    schema_version: "1.0.0",
    record_origin: "verified_model_package_artifact",
    status: "available",
    title: "Исторический рекламный бюджет в данных модели",
    display_text: "Исторические расходы модели доступны для карты.",
    period_display_text: "Период данных: 01.01.2025 — 31.05.2026",
    package_id: "pkg_test_historical_model",
    model_version: "model_test_v1",
    artifact_id: "artifact_0123456789abcdef01234567",
    artifact_version: "historical_geo_budget_v1",
    catalog_version: "geo_catalog_v1_test",
    period_start: "2025-01-01",
    period_end: "2026-05-31",
    spend_columns_version: "spend_columns_v1",
    total_budget_rub: total,
    geographies_n: TEST_GEO_CATALOG.length,
    coverage: {
      status: "available",
      located_geographies_n: TEST_GEO_CATALOG.length,
      unlocated_geographies_n: 0,
      unlocated_geographies: [],
      located_budget_rub: total,
      unlocated_budget_rub: 0,
      unlocated_budget_share: 0,
    },
    rows: TEST_GEO_CATALOG.map((geo, index) => ({
      geo_id: geo.geo_id,
      geo_display_name: geo.geo_display_name,
      latitude: geo.latitude,
      longitude: geo.longitude,
      coordinates_status: "canonical" as const,
      historical_total_budget_rub: budgets[index],
      budget_share: budgets[index] / total,
      active_days_n: 500 - index,
      active_rows_n: 600 - index,
    })),
    limitations: [],
    updated_at_utc: "2026-07-19T10:00:00Z",
  };
}

function historicalModel() {
  return adaptHistoricalModelGeoBudget(historicalPayload());
}

function campaignModel() {
  return adaptValidationGeoBudget(buildValidationResultV2());
}

describe("GeoBudgetMap", () => {
  it("renders historical bubbles from backend rows, top-10 labels and largest point last", () => {
    const model = historicalModel();
    const { container } = render(<GeoBudgetMap model={model} />);

    expect(screen.getByRole("group", { name: "Карта исторического рекламного бюджета модели по географиям" }))
      .toBeInTheDocument();
    const markers = [...container.querySelectorAll("[data-map-marker]")];
    const labels = [...container.querySelectorAll("[data-map-label]")];
    expect(markers).toHaveLength(15);
    expect(labels).toHaveLength(10);
    expect(markers.at(-1)).toHaveAttribute("data-budget-rub", String(model.maxBudgetRub));
    expect(screen.getByText("Подписаны 10 городов с наибольшим бюджетом")).toBeInTheDocument();
    expect(screen.getByText("Координаты городов: GeoNames, CC BY 4.0.")).toBeInTheDocument();
    expect(screen.getByText("Контур карты: Natural Earth, public domain.")).toBeInTheDocument();
  });

  it("opens an exact historical tooltip without campaign count and closes on Escape", () => {
    const model = historicalModel();
    const { container } = render(<GeoBudgetMap model={model} />);
    const point = model.points[0];
    const marker = container.querySelector(
      "[data-map-marker='" + point.geoId + "']",
    ) as HTMLButtonElement;

    fireEvent.mouseEnter(marker);
    const tooltip = screen.getByRole("tooltip");
    expect(within(tooltip).getByText(point.geoDisplayName)).toBeInTheDocument();
    expect(within(tooltip).getByText("Исторический рекламный бюджет")).toBeInTheDocument();
    expect(within(tooltip).getByText("Доля общего бюджета")).toBeInTheDocument();
    expect(within(tooltip).getByText("Дней с рекламной активностью")).toBeInTheDocument();
    expect(within(tooltip).getByText(String(point.activeDaysN))).toBeInTheDocument();
    expect(within(tooltip).getByText("Период данных")).toBeInTheDocument();
    expect(within(tooltip).getByText("01.01.2025 — 31.05.2026")).toBeInTheDocument();
    expect(within(tooltip).queryByText(/Кампани/u)).not.toBeInTheDocument();
    expect(marker).toHaveAccessibleName(/Исторический рекламный бюджет/);
    expect(marker).toHaveAccessibleName(/Дней с рекламной активностью/);
    expect(marker).not.toHaveAccessibleName(/Кампани/u);

    screen.getByRole("button", { name: "Закрыть подсказку" }).focus();
    fireEvent.keyDown(container.querySelector("[data-map-mode]") as HTMLElement, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(marker).toHaveFocus();
  });

  it("renders all campaign labels and backend-provided channels and limitation count", () => {
    const model = campaignModel();
    const { container } = render(<GeoBudgetMap model={model} />);

    expect(container.querySelectorAll("[data-map-marker]")).toHaveLength(15);
    expect(container.querySelectorAll("[data-map-label]")).toHaveLength(15);
    expect(screen.getByText("Подписаны все географии кампании")).toBeInTheDocument();

    const marker = container.querySelector("[data-map-marker]") as HTMLButtonElement;
    fireEvent.click(marker);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent("Цифровая реклама");
    expect(tooltip).toHaveTextContent("Наружная реклама");
    expect(tooltip).toHaveTextContent("Радио");
    expect(within(tooltip).getByText("Ограничения модели")).toBeInTheDocument();
    expect(within(tooltip).getByText("1")).toBeInTheDocument();
    expect(model.requestedBudgetRub).toBe(CONTROL_REQUESTED_BUDGET);
  });

  it("keeps partial unlocated budget and names visible without treating coverage as an error", () => {
    const source = historicalModel();
    const partial: GeoBudgetMapModel = {
      ...source,
      coverage: {
        status: "partial",
        locatedGeographiesN: 14,
        unlocatedGeographiesN: 1,
        locatedBudgetRub: (source.totalBudgetRub ?? 0) - 500_000,
        unlocatedBudgetRub: 500_000,
        unlocatedBudgetShare: 500_000 / (source.totalBudgetRub ?? 1),
        unlocatedGeographies: [{
          geoId: "geo_ffffffffffffffff",
          geoDisplayName: "Синтетическая география без координат",
        }],
      },
    };
    render(<GeoBudgetMap model={partial} />);

    expect(screen.getByText("Частичное покрытие")).toBeInTheDocument();
    expect(screen.getByText(/Неразмещенный бюджет: 500/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Показать географии"));
    expect(screen.getByText("Синтетическая география без координат")).toBeInTheDocument();
    expect(screen.queryByText("Не удалось загрузить карту")).not.toBeInTheDocument();
  });

  it("distinguishes controlled unavailable, loading, network and unsupported states", () => {
    const source = historicalModel();
    const unavailable: GeoBudgetMapModel = {
      ...source,
      displayText: "Исторический артефакт модели пока недоступен.",
      periodDisplayText: "Период данных недоступен",
      totalBudgetRub: null,
      geographiesN: 0,
      points: [],
      maxBudgetRub: 0,
      coverage: {
        status: "unavailable",
        locatedGeographiesN: 0,
        unlocatedGeographiesN: 0,
        locatedBudgetRub: 0,
        unlocatedBudgetRub: 0,
        unlocatedBudgetShare: null,
        unlocatedGeographies: [],
      },
    };
    const { rerender } = render(<GeoBudgetMap model={unavailable} />);
    expect(screen.getByText("Карта пока недоступна")).toBeInTheDocument();
    expect(screen.getByText("Исторический артефакт модели пока недоступен.")).toBeInTheDocument();
    expect(screen.queryByText(/Бюджет сохранен/)).not.toBeInTheDocument();

    rerender(<GeoBudgetMap model={null} requestState="loading" />);
    expect(screen.getByText("Загружаем карту бюджета")).toBeInTheDocument();

    const retry = vi.fn();
    rerender(<GeoBudgetMap model={null} requestState="network-error" onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(retry).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Не удалось загрузить карту")).toBeInTheDocument();

    rerender(<GeoBudgetMap model={null} requestState="unsupported-contract" />);
    expect(screen.getByText("Формат данных карты не поддерживается")).toBeInTheDocument();
  });

  it("does not draw or focus a zero-budget point", () => {
    const source = campaignModel();
    const zero = {
      ...source,
      points: source.points.map((point, index) => (
        index === 0 ? { ...point, budgetRub: 0, budgetShare: 0 } : point
      )),
    };
    const { container } = render(<GeoBudgetMap model={zero} />);
    expect(container.querySelector("[data-map-marker='" + source.points[0].geoId + "']"))
      .not.toBeInTheDocument();
    expect(container.querySelector("[data-map-label='" + source.points[0].geoId + "']"))
      .not.toBeInTheDocument();
  });
});
