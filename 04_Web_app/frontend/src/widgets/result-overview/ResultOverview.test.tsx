import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "../../../../tests/fixtures/result_overview_v1_real_sanitized.json";
import type { ResultOverviewV1 } from "../../entities/result-overview/types";
import { ResultOverview } from "./ResultOverview";

function renderFixture(change?: (result: ResultOverviewV1) => void) {
  const result = structuredClone(fixture) as unknown as ResultOverviewV1;
  change?.(result);
  const [campaign] = result.campaigns;
  return render(<ResultOverview result={result} campaign={campaign} />);
}

describe("ResultOverview", () => {
  it("renders the contract-backed overview without raw backend names", () => {
    const { container } = renderFixture();

    expect(screen.getByText("Демонстрационные данные")).toBeInTheDocument();
    expect(screen.getByText("Ориентир по устойчивости", { selector: "div" })).toBeInTheDocument();
    expect(screen.getByText(/не является решением запускать/)).toBeInTheDocument();
    expect(screen.getByText("Дополнительные заказы")).toBeInTheDocument();
    expect(container.textContent).not.toContain("candidate_");
    expect(container.textContent).not.toContain("MISSING_OR_FAILED");
    expect(container.textContent).not.toContain("support/model risk");
  });

  it("opens the detailed six-scenario comparison", () => {
    renderFixture();
    fireEvent.click(screen.getByRole("tab", { name: "Сценарии" }));

    expect(screen.getByRole("heading", { name: "Сравнение вариантов медиаплана" })).toBeInTheDocument();
    expect(screen.getAllByText(/Сценарий [1-6]/).length).toBeGreaterThanOrEqual(6);
    expect(screen.getByText("Осторожное распределение")).toBeInTheDocument();
    expect(screen.getAllByText("ROAS по обороту").length).toBe(6);
  });

  it("shows status-based reliability and structured warnings", () => {
    const { container } = renderFixture();
    fireEvent.click(screen.getByRole("tab", { name: "Надежность" }));

    expect(screen.getByRole("heading", { name: /Что можно использовать/ })).toBeInTheDocument();
    expect(screen.getByText("Лучший вариант до проверок")).toBeInTheDocument();
    expect(screen.getByText("Лучший допустимый вариант")).toBeInTheDocument();
    expect(screen.getByText("Не настроен бизнес-порог")).toBeInTheDocument();
    expect(screen.queryByText(/Надежность · \d/)).not.toBeInTheDocument();
    expect(container.textContent).not.toContain("historical p95");
  });

  it("renders the line-level media plan and report downloads", () => {
    renderFixture();
    fireEvent.click(screen.getByRole("tab", { name: "Медиаплан" }));
    expect(screen.getByRole("heading", { name: "Было → рекомендуется" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Рекомендуется" })).toBeInTheDocument();
    expect(screen.getByLabelText("Канал")).toBeInTheDocument();
    expect(screen.getByText("Сводные итоги по каналам и гео")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Отчет" }));
    expect(screen.getByText("Отчет для маркетолога")).toBeInTheDocument();
    expect(screen.getByText("Рекомендованный медиаплан")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Скачать Excel" }).every((button) => button.hasAttribute("disabled"))).toBe(true);
  });

  it("renders S6 unavailable without substituting zero metrics", () => {
    renderFixture((result) => {
      const campaign = result.campaigns[0];
      const s6 = campaign.scenarios.find((scenario) => scenario.scenario_id === "S06");
      if (!s6) throw new Error("S6 is required");
      s6.available = false;
      s6.metrics = {
        incremental_turnover: null,
        turnover_roas: null,
        incremental_orders: null,
        incremental_orders_usage: "diagnostic_only",
        avg_basket_turnover_bridge: null,
      };
      campaign.scenario6.audit.run_status.code = "gate_policy_blocked";
      campaign.scenario6.best_raw = null;
      campaign.scenario6.best_safe = null;
      campaign.scenario6.raw_differs_from_safe = false;
    });
    fireEvent.click(screen.getByRole("tab", { name: "Сценарии" }));

    expect(screen.getByText("Адаптивный поиск недоступен")).toBeInTheDocument();
    expect(screen.getAllByText("Нет данных").length).toBeGreaterThan(0);
  });

  it("shows partial coverage from direct contract fields", () => {
    renderFixture((result) => {
      const campaign = result.campaigns[0];
      campaign.statuses.calculation_status.code = "partially_calculated";
      campaign.budget.model_coverage_share = 0.72;
      campaign.budget.unmodeled_budget_rub = 2_000_000;
      campaign.budget.unallocated_budget_rub = 500_000;
    });

    expect(screen.getByRole("heading", { name: "Результат рассчитан частично" })).toBeInTheDocument();
    expect(screen.getByText(/72\s*%/)).toBeInTheDocument();
  });
});
