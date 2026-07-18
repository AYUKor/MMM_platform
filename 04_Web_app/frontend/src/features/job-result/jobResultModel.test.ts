import { describe, expect, it } from "vitest";
import { buildJobResultViewV2 } from "../../test/businessSemanticsV2Fixtures";
import {
  completedMediaScenario,
  resultSearchParams,
  resultTabFromSearch,
  scenarioById,
} from "./jobResultModel";
import {
  decisionLabel,
  scenarioAnchorLabel,
  scenarioDisplayName,
  scenarioVariantTitle,
} from "./jobResultFormatting";

describe("jobResultModel v2", () => {
  it("normalizes the tab and media-plan URL without changing recommendation", () => {
    const result = buildJobResultViewV2();
    expect(resultTabFromSearch("scenarios")).toBe("scenarios");
    expect(resultTabFromSearch("raw")).toBe("overview");
    expect(completedMediaScenario(result, "S06")).toBe("S01");
    expect(resultSearchParams("media-plan", "S05").toString()).toBe("tab=media-plan&scenario=S05");
    expect(result.recommendation.scenario_id).toBe("S01");
  });

  it("uses product labels instead of legacy media-plan titles", () => {
    const result = buildJobResultViewV2();
    const source = scenarioById(result, "S01");
    const partial = scenarioById(result, "S05");
    const infeasible = scenarioById(result, "S06");
    expect(scenarioDisplayName(source)).toBe("Исходный план");
    expect(scenarioAnchorLabel(source)).toBe("Точка отсчета");
    expect(scenarioDisplayName(partial)).toBe("Безопасно распределяемая часть");
    expect(scenarioVariantTitle(partial)).toBe("Безопасно распределяемая часть");
    expect(scenarioDisplayName(infeasible)).toBe("План максимального эффекта");
  });

  it("maps backend decision states without promoting S1", () => {
    expect(decisionLabel("keep_uploaded_plan")).toBe("Сохранить исходный план");
    expect(decisionLabel("recommended_reallocation")).toBe("Рекомендованное перераспределение");
    expect(decisionLabel("no_safe_recommendation")).toBe("Безопасная рекомендация не найдена");
  });
});
