import type {
  JobResultViewV2,
  Scenario,
} from "../../shared/api/generated/job-result-view-v2";
import type { ScenarioId } from "../../shared/api/generated/scenario-media-plan-v2";

export const RESULT_TABS = [
  { id: "overview", label: "Обзор" },
  { id: "scenarios", label: "Сценарии и надежность" },
  { id: "media-plan", label: "Медиаплан" },
  { id: "report", label: "Отчет" },
] as const;

export type ResultTabId = (typeof RESULT_TABS)[number]["id"];

export function resultTabFromSearch(value: string | null | undefined): ResultTabId {
  return RESULT_TABS.some((tab) => tab.id === value) ? value as ResultTabId : "overview";
}

export function isScenarioId(value: string | null | undefined): value is ScenarioId {
  return ["S01", "S02", "S03", "S04", "S05", "S06"].includes(value ?? "");
}

export function scenarioById(result: JobResultViewV2, id: string | null | undefined): Scenario {
  return result.scenarios.find((scenario) => scenario.scenario_id === id) ?? result.scenarios[0];
}

export function completedMediaScenario(result: JobResultViewV2, id: string | null | undefined): ScenarioId | null {
  if (isScenarioId(id) && scenarioById(result, id).status === "completed") return id;
  const selected = result.media_plan.selected_scenario_id;
  if (isScenarioId(selected) && scenarioById(result, selected).status === "completed") return selected;
  const benchmark = scenarioById(result, "S05");
  if (benchmark.status === "completed") return "S05";
  return scenarioById(result, "S01").status === "completed" ? "S01" : null;
}

export function resultSearchParams(tab: ResultTabId, scenarioId?: ScenarioId | null): URLSearchParams {
  const params = new URLSearchParams({ tab });
  if (tab === "media-plan" && scenarioId) params.set("scenario", scenarioId);
  return params;
}
