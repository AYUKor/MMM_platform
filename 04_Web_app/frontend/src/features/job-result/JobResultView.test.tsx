import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import {
  buildJobResultViewV2,
  buildScenarioMediaPlanV2,
} from "../../test/businessSemanticsV2Fixtures";
import { JobResultView, type JobResultViewProps } from "./JobResultView";

function renderView(overrides: Partial<JobResultViewProps> = {}) {
  const props: JobResultViewProps = {
    result: buildJobResultViewV2(),
    activeTab: "overview",
    mediaPlan: undefined,
    mediaScenarioId: "S01",
    mediaControls: { channel: null, geo: null, page: 1, pageSize: 25 },
    mediaLoading: false,
    mediaError: null,
    refreshNotice: null,
    onTabChange: vi.fn(),
    onMediaScenarioChange: vi.fn(),
    onMediaControlsChange: vi.fn(),
    onMediaPageChange: vi.fn(),
    onMediaRetry: vi.fn(),
    onRefresh: vi.fn(),
    ...overrides,
  };
  const rendered = render(<MemoryRouter><JobResultView {...props} /></MemoryRouter>);
  return { props, ...rendered };
}

describe("JobResultView turnover-only", () => {
  it("shows S1 as a manual-review point of reference, never a system recommendation", () => {
    renderView({ activeTab: "scenarios" });
    expect(screen.getAllByText("Исходный план").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Точка отсчета").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Требуется ручная проверка").length).toBeGreaterThan(0);
    expect(screen.getByText("Исходный план показан как точка отсчета. Он не является рекомендацией системы и требует ручной проверки.")).toBeInTheDocument();
    expect(screen.queryByText(/перераспределение не подтвердило надежного улучшения/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Рекомендован системой")).not.toBeInTheDocument();
  });

  it("shows partial S5 allocated and unallocated budget plus both ROAS meanings", () => {
    renderView();
    expect(screen.getAllByRole("heading", { name: "Безопасно распределяемая часть" }).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/173,9.*млн.*₽/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/93,9.*млн.*₽/).length).toBeGreaterThan(0);

    renderView({
      result: {
        ...buildJobResultViewV2(),
        recommendation: {
          ...buildJobResultViewV2().recommendation,
          decision_status: "no_safe_recommendation",
          scenario_id: "S05",
        },
      },
    });
    expect(screen.getAllByText("Распределена безопасная часть").length).toBeGreaterThan(0);
  });

  it("renders infeasible S6 as a controlled state without fake KPI", () => {
    renderView({ activeTab: "scenarios" });
    const heading = screen.getByRole("heading", { name: "Полный план максимального эффекта недоступен" });
    const card = heading.closest("article");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText(/невозможно распределить весь бюджет/i)).toBeInTheDocument();
    expect(within(card as HTMLElement).queryByText("Дополнительный оборот · P50")).not.toBeInTheDocument();
    expect(within(card as HTMLElement).queryByRole("button", { name: /повтор/i })).not.toBeInTheDocument();
  });

  it("uses all geographies and channel display names in media-plan filters", () => {
    const result = buildJobResultViewV2();
    renderView({
      result,
      activeTab: "media-plan",
      mediaPlan: buildScenarioMediaPlanV2("S01", { page: 1, pageSize: 25 }),
    });
    expect(screen.getByText("45 строк · 15 географий")).toBeInTheDocument();
    expect(screen.getAllByText("Цифровая реклама").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Наружная реклама").length).toBeGreaterThan(0);
    expect(screen.queryByText("Digital_Performance")).not.toBeInTheDocument();
    expect(screen.queryByText("OOH_Total")).not.toBeInTheDocument();
    const geoSelect = screen.getByLabelText("География") as HTMLSelectElement;
    expect(geoSelect.options).toHaveLength(16);
  });

  it("renders a controlled empty media-plan state without page 1 of 0", () => {
    renderView({
      activeTab: "media-plan",
      mediaControls: { channel: null, geo: "Нет такой географии", page: 1, pageSize: 25 },
      mediaPlan: buildScenarioMediaPlanV2("S01", { geo: "Нет такой географии", page: 1, pageSize: 25 }),
    });
    expect(screen.getByText("По выбранным фильтрам строк нет")).toBeInTheDocument();
    expect(screen.queryByText("Страница 1 из 0")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("keeps report unavailable instead of falling back to v1", () => {
    renderView({ activeTab: "report" });
    expect(screen.getByRole("heading", { name: "Excel-отчет пока недоступен" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /скачать отчет/i })).not.toBeInTheDocument();
  });

  it("forbids diagnostic KPI and raw target identifiers in mounted UI", () => {
    const { container } = renderView();
    const text = container.textContent ?? "";
    for (const forbidden of [
      "Дополнительные заказы",
      "Заказы на 100 000 ₽",
      "Механизм среднего чека",
      "Часть дополнительного оборота",
      "orders_per_user",
      "avg_basket",
      "... ещё",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });
});
