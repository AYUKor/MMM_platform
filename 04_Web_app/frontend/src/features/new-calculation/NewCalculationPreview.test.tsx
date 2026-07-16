import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ValidationPreview } from "../../entities/lifecycle/types";
import { CampaignPreviewVisuals, ValidationChecks } from "./NewCalculationPreview";

const preview: ValidationPreview = {
  budget_by_channel: [
    {
      channel: "Синтетический канал A",
      total_budget_rub: 700_000,
      max_daily_budget_rub: 100_000,
      status: { code: "passed", display_text: "Проверено" },
    },
    {
      channel: "Синтетический канал B",
      total_budget_rub: 300_000,
      max_daily_budget_rub: 50_000,
      status: { code: "warning", display_text: "Есть ограничение" },
    },
  ],
  budget_by_geo: [
    {
      geo: "Синтетический город",
      total_budget_rub: 1_000_000,
      max_daily_budget_rub: 150_000,
    },
  ],
  channel_flighting: [
    { channel: "Синтетический канал A", date: "2026-02-01", daily_budget_rub: 100_000 },
    { channel: "Синтетический канал A", date: "2026-02-02", daily_budget_rub: 80_000 },
    { channel: "Синтетический канал B", date: "2026-02-01", daily_budget_rub: 50_000 },
    {
      channel: "Синтетический канал B",
      date: "2026-02-02",
      daily_budget_rub: 0,
      status: { code: "warning", display_text: "Нулевой бюджет подтвержден" },
    },
  ],
  checks: [
    {
      code: "SYNTHETIC_FILE_STRUCTURE",
      status: "passed",
      display_text: "Синтетическая структура распознана.",
    },
    {
      code: "SYNTHETIC_HISTORY",
      status: "unavailable",
      display_text: "Синтетическая историческая проверка будет выполнена позже.",
    },
  ],
  geo_points: [
    {
      geo: "Синтетическая точка только для geo_points",
      latitude: 55.7558,
      longitude: 37.6173,
      total_budget_rub: 1_000_000,
    },
  ],
};

describe("new calculation preview", () => {
  it("renders only backend-provided checks and hides raw codes", () => {
    render(<ValidationChecks checks={preview.checks} />);

    expect(screen.getByText("Синтетическая структура распознана.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Результаты проверки" })).toBeInTheDocument();
    expect(screen.getByText("Синтетическая историческая проверка будет выполнена позже.")).toBeInTheDocument();
    expect(screen.getByText("Пройдено")).toBeInTheDocument();
    expect(screen.getByText("Недоступно")).toBeInTheDocument();
    expect(screen.queryByText("SYNTHETIC_FILE_STRUCTURE")).not.toBeInTheDocument();
    expect(screen.queryByText("Поддержка сегмента")).not.toBeInTheDocument();
  });

  it("renders direct channel, geo and flighting preview values", () => {
    render(<CampaignPreviewVisuals preview={preview} />);

    expect(screen.getByRole("heading", { name: "Бюджет по каналам" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Бюджет по географиям" })).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Бюджет по каналам")).getByText("Синтетический канал A"),
    ).toBeInTheDocument();
    expect(screen.getByText("Синтетический город")).toBeInTheDocument();
    const timeline = screen.getByLabelText("Временная диаграмма активности каналов");
    expect(
      within(timeline).getByRole("columnheader", { name: "01 февр. 2026 г." }),
    ).toBeInTheDocument();
    expect(
      within(timeline).getByRole("cell", {
        name: "Синтетический канал A, 01 февр. 2026 г.: 100\u00a0тыс. ₽",
      }),
    ).toBeInTheDocument();
    const zeroBudgetCell = within(timeline).getByRole("cell", {
      name: "Синтетический канал B, 02 февр. 2026 г.: 0 ₽. Статус: Нулевой бюджет подтвержден",
    });
    expect(zeroBudgetCell).toHaveStyle("--cell-strength: 0%");
    expect(
      within(timeline).getByRole("rowheader", { name: "Синтетический канал B" }),
    ).not.toHaveTextContent("Нулевой бюджет подтвержден");
    expect(screen.getByText("Точные значения по дням")).toBeInTheDocument();
    expect(screen.getByText("Нулевой бюджет подтвержден")).toBeInTheDocument();
    expect(screen.getByText("Данные для карты пока недоступны.")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /координаты географий/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Синтетическая точка только для geo_points")).not.toBeInTheDocument();
  });

  it("uses controlled unavailable states for an old validation without preview", () => {
    const { rerender } = render(<ValidationChecks checks={undefined} />);
    expect(screen.getByText("Детализация проверок пока недоступна.")).toBeInTheDocument();

    rerender(<CampaignPreviewVisuals preview={undefined} />);
    expect(screen.getAllByText("Нет данных")).toHaveLength(4);
    expect(screen.getByText("Данные для карты пока недоступны.")).toBeInTheDocument();
  });
});
