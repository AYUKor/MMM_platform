import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import gateBlockedFixture from "../../../../tests/fixtures/decision_result_v1_gate_blocked_sanitized.json";
import safeFixture from "../../../../tests/fixtures/decision_result_v1_real_sanitized.json";
import type { DecisionResultV1 } from "../../entities/decision-result/types";
import { ResultOverview } from "./ResultOverview";

function renderFixture(fixture: unknown) {
  const result = fixture as DecisionResultV1;
  const [campaign, extraCampaign] = result.campaign_results;
  if (!campaign || extraCampaign) throw new Error("Expected one sanitized campaign");
  return render(<ResultOverview result={result} campaign={campaign} />);
}

describe("ResultOverview", () => {
  it("renders demo badge and controlled contract gaps", () => {
    const { container } = renderFixture(safeFixture);

    expect(screen.getByText("Демонстрационные данные")).toBeInTheDocument();
    expect(screen.getByText("Устойчивый benchmark", { selector: "div" })).toBeInTheDocument();
    expect(screen.getAllByText("Нет данных").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText(/не является решением запускать/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("candidate_");
  });

  it("renders S6 unavailable with backend explanation", () => {
    renderFixture(gateBlockedFixture);
    expect(screen.getByText("S6 недоступен")).toBeInTheDocument();
    expect(screen.getAllByText(/каналы зафиксированы gate policy/i).length).toBeGreaterThan(0);
  });
});
