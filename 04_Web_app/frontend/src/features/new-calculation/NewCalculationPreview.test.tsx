import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ValidationPreview } from "../../entities/lifecycle/types";
import { buildValidationResultV2 } from "../../test/businessSemanticsV2Fixtures";
import { BusinessValidationReview, CampaignPreviewVisuals, ValidationChecks } from "./NewCalculationPreview";

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

  it("separates calm file validation from grouped model limitations", () => {
    const validation = buildValidationResultV2();
    const { container } = render(<BusinessValidationReview validation={validation} />);

    expect(screen.getByRole("heading", { name: "Кампания готова к расчету" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Проверка файла" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ограничения модели" })).toBeInTheDocument();
    expect(screen.getAllByText("15", { selector: "dd" })).toHaveLength(2);
    expect(screen.getByText("Показать географии (15)")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "15 географий сохранены" })).toBeInTheDocument();
    const map = screen.getByRole("group", { name: "Карта рекламного бюджета текущей кампании" });
    expect(map.querySelectorAll("[data-map-marker]")).toHaveLength(15);
    expect(map.querySelectorAll("[data-map-label]")).toHaveLength(15);
    expect(screen.getByText("Координаты городов: GeoNames, CC BY 4.0.")).toBeInTheDocument();
    expect(screen.queryByText("Карта будет доступна после подключения утвержденного справочника координат."))
      .not.toBeInTheDocument();
    expect(container.querySelectorAll("details")).toHaveLength(1);
    expect(container.querySelectorAll("[class*='contextChip']")).toHaveLength(0);
    expect(container.textContent).not.toContain("Digital_Performance");
    expect(container.textContent).not.toContain("orders_per_user");
    expect(container.textContent).not.toContain("avg_basket");
  });

  it("distinguishes file errors from model-blocked and unavailable states", () => {
    const modelBlocked = buildValidationResultV2();
    modelBlocked.job_creation_allowed = false;
    modelBlocked.status = "warning";
    modelBlocked.model_limitations[0].severity = "blocking";
    modelBlocked.model_limitations[0].blocks_calculation = true;
    const { rerender } = render(<BusinessValidationReview validation={modelBlocked} />);
    expect(screen.getByRole("heading", { name: "Расчет ограничен возможностями модели" })).toBeInTheDocument();
    expect(screen.getByText("За пределами доступного расчета")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Файл нужно исправить" })).not.toBeInTheDocument();

    const failedFile = buildValidationResultV2();
    failedFile.job_creation_allowed = false;
    failedFile.status = "failed";
    failedFile.file_validation.status = "failed";
    rerender(<BusinessValidationReview validation={failedFile} />);
    expect(screen.getByRole("heading", { name: "Файл нужно исправить" })).toBeInTheDocument();

    const unavailable = buildValidationResultV2();
    unavailable.job_creation_allowed = false;
    unavailable.status = "unavailable";
    unavailable.file_validation.status = "unavailable";
    rerender(<BusinessValidationReview validation={unavailable} />);
    expect(screen.getByRole("heading", { name: "Результат проверки пока недоступен" })).toBeInTheDocument();
  });

  it("renders federal allocation only from backend-provided totals and wording", () => {
    const validation = buildValidationResultV2();
    validation.federal_allocation = {
      status: "available",
      title: "Обнаружено федеральное размещение",
      description: "Федеральный бюджет автоматически распределен между поддерживаемыми географиями модели выбранного бизнес-направления пропорционально населению.",
      policy_version: "FEDERAL_GEO_ALLOCATION_V1",
      package_id: "pkg_1234567890abcdef_1234567890abcdef",
      source_rows_count: 2,
      source_budget_rub: 100_000_000,
      allocated_budget_rub: 100_000_000,
      difference_rub: 0.000001,
      geo_count: 211,
      method_display_name: "Пропорционально населению",
      channels: [{ channel_id: "Digital_Performance", channel_display_name: "Цифровая реклама" }],
      business_directions: ["ТС5/Онлайн"],
      mixed_local_overlap: true,
      information: [{ code: "FEDERAL_GEO_ALLOCATION_INFO", display_text: "Информация сохранена." }],
      warnings: [{ code: "FEDERAL_AND_LOCAL_GEO_OVERLAP", display_text: "Локальные суммы будут добавлены поверх федерального распределения." }],
      errors: [],
      breakdown: [{
        business_direction: "ТС5/Онлайн",
        channels: [{ channel_id: "Digital_Performance", channel_display_name: "Цифровая реклама" }],
        source_rows_count: 2,
        source_budget_rub: 100_000_000,
        allocated_budget_rub: 100_000_000,
        difference_rub: 0,
        geo_count: 211,
      }],
    };
    const { container } = render(<BusinessValidationReview validation={validation} />);

    expect(screen.getByRole("heading", { name: "Обнаружено федеральное размещение" })).toBeInTheDocument();
    expect(screen.getAllByText("100 млн ₽", { selector: "dd" })).toHaveLength(2);
    expect(screen.getByText("211", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Пропорционально населению")).toBeInTheDocument();
    expect(screen.getByText("Распределено полностью · 0 ₽")).toBeInTheDocument();
    expect(screen.getByText("Локальные суммы будут добавлены поверх федерального распределения.")).toBeInTheDocument();
    expect(container.textContent).not.toContain("Digital_Performance");
    expect(container.textContent).not.toContain("pkg_1234567890abcdef_1234567890abcdef");
  });

  it("shows a backend federal error as a blocking human message", () => {
    const validation = buildValidationResultV2();
    validation.federal_allocation = {
      status: "error", title: null, description: null, policy_version: null, package_id: null,
      source_rows_count: 0, source_budget_rub: 0, allocated_budget_rub: 0, difference_rub: 0,
      geo_count: null, method_display_name: null, channels: [], business_directions: [],
      mixed_local_overlap: false, information: [], warnings: [], breakdown: [],
      errors: [{ code: "UNKNOWN_GEO_VALUE", display_text: "География «Вся Россия» не распознана. Укажите РФ, Россия или Российская Федерация." }],
    };
    render(<BusinessValidationReview validation={validation} />);
    expect(screen.getByRole("heading", { name: "Федеральный бюджет не распределен" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Вся Россия");
  });
});
