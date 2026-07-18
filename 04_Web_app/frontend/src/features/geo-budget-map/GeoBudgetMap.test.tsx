import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  buildValidationResultV2,
  CONTROL_REQUESTED_BUDGET,
} from "../../test/businessSemanticsV2Fixtures";
import { createWorkspaceGeoBudgetFixture } from "../../../e2e/support/business-semantics-fixtures";
import { GeoBudgetMap } from "./GeoBudgetMap";
import {
  adaptValidationGeoBudget,
  adaptWorkspaceGeoBudget,
  type GeoBudgetMapModel,
} from "./geoBudgetMapModel";

function workspaceModel() {
  return adaptWorkspaceGeoBudget(createWorkspaceGeoBudgetFixture());
}

function campaignModel() {
  return adaptValidationGeoBudget(buildValidationResultV2());
}

describe("GeoBudgetMap", () => {
  it("renders workspace bubbles from backend rows, top-10 labels and largest point last", () => {
    const model = workspaceModel();
    const { container } = render(<GeoBudgetMap model={model} />);

    expect(screen.getByRole("group", { name: "Карта суммарного рекламного бюджета по городам" }))
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

  it("opens an exact workspace tooltip by hover and keyboard focus, closes on Escape", () => {
    const model = workspaceModel();
    const { container } = render(<GeoBudgetMap model={model} />);
    const point = model.points[0];
    const marker = container.querySelector(
      "[data-map-marker='" + point.geoId + "']",
    ) as HTMLButtonElement;

    fireEvent.mouseEnter(marker);
    const tooltip = screen.getByRole("tooltip");
    expect(within(tooltip).getByText(point.geoDisplayName)).toBeInTheDocument();
    expect(within(tooltip).getByText("Кампаний")).toBeInTheDocument();
    expect(marker).toHaveAccessibleName(/Общий бюджет/);

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
    const source = campaignModel();
    const partial: GeoBudgetMapModel = {
      ...source,
      coverage: {
        status: "partial",
        locatedGeographiesN: 14,
        unlocatedGeographiesN: 1,
        locatedBudgetRub: source.requestedBudgetRub - 500_000,
        unlocatedBudgetRub: 500_000,
        unlocatedBudgetShare: 500_000 / source.requestedBudgetRub,
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

  it("distinguishes unavailable, empty, loading, network and unsupported states", () => {
    const source = workspaceModel();
    const unavailable: GeoBudgetMapModel = {
      ...source,
      points: [],
      maxBudgetRub: 0,
      coverage: {
        ...source.coverage,
        status: "unavailable",
        locatedGeographiesN: 0,
        unlocatedGeographiesN: source.geographiesN,
        locatedBudgetRub: 0,
        unlocatedBudgetRub: source.totalBudgetRub,
        unlocatedBudgetShare: 1,
        unlocatedGeographies: source.points.map((point) => ({
          geoId: point.geoId,
          geoDisplayName: point.geoDisplayName,
        })),
      },
    };
    const { rerender } = render(<GeoBudgetMap model={unavailable} />);
    expect(screen.getByText("Карта пока недоступна")).toBeInTheDocument();
    expect(screen.getByText(/Бюджет сохранен/)).toBeInTheDocument();

    const empty: GeoBudgetMapModel = {
      ...source,
      totalBudgetRub: 0,
      campaignsN: 0,
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
    rerender(<GeoBudgetMap model={empty} />);
    expect(screen.getByText("Пока нет данных для карты")).toBeInTheDocument();

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
