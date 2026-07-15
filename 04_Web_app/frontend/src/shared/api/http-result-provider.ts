import type { ResultOverviewV1 } from "../../entities/result-overview/types";
import type { ResultProvider } from "./result-provider";

interface ApiErrorPayload {
  error?: {
    code?: string;
    display_text?: string;
  };
}

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function isResultOverview(value: unknown): value is ResultOverviewV1 {
  if (!isRecord(value)) return false;
  if (
    value.contract_name !== "result_overview_v1" ||
    value.schema_version !== "1.0.0" ||
    value.overview_adapter_version !== "1.0.0" ||
    typeof value.overview_id !== "string" ||
    !Array.isArray(value.campaigns) ||
    value.campaigns.length === 0 ||
    !Array.isArray(value.artifacts) ||
    value.artifacts.length === 0 ||
    !Array.isArray(value.warnings)
  ) {
    return false;
  }
  const expectedScenarioIds = new Set(["S01", "S02", "S03", "S04", "S05", "S06"]);
  const campaignsAreValid = value.campaigns.every((campaign) => {
    if (
      !isRecord(campaign) ||
      typeof campaign.campaign_id !== "string" ||
      !isRecord(campaign.passport) ||
      typeof campaign.passport.campaign_name !== "string" ||
      !isRecord(campaign.budget) ||
      !isRecord(campaign.statuses) ||
      !isRecord(campaign.recommendation) ||
      !Array.isArray(campaign.scenarios) ||
      campaign.scenarios.length !== 6 ||
      !Array.isArray(campaign.allocation_comparison) ||
      campaign.allocation_comparison.length === 0 ||
      !Array.isArray(campaign.warnings)
    ) {
      return false;
    }
    const scenarioIds = new Set(
      campaign.scenarios.map((scenario) =>
        isRecord(scenario) ? scenario.scenario_id : undefined,
      ),
    );
    if (
      scenarioIds.size !== expectedScenarioIds.size ||
      [...expectedScenarioIds].some((scenarioId) => !scenarioIds.has(scenarioId))
    ) {
      return false;
    }
    const scenariosAreValid = campaign.scenarios.every(
      (scenario) =>
        isRecord(scenario) &&
        typeof scenario.available === "boolean" &&
        isRecord(scenario.metrics) &&
        isRecord(scenario.budget) &&
        isRecord(scenario.quality) &&
        isRecord(scenario.calculation_status) &&
        typeof scenario.calculation_status.code === "string",
    );
    const recommendationScenario = campaign.recommendation.scenario_id;
    const allocationsAreValid = campaign.allocation_comparison.every(
      (line) =>
        isRecord(line) &&
        typeof line.segment === "string" &&
        typeof line.geo === "string" &&
        typeof line.channel === "string" &&
        typeof line.delta_budget_rub === "number",
    );
    return (
      scenariosAreValid &&
      typeof recommendationScenario === "string" &&
      scenarioIds.has(recommendationScenario) &&
      allocationsAreValid
    );
  });
  const artifactsAreValid = value.artifacts.every(
    (artifact) =>
      isRecord(artifact) &&
      typeof artifact.kind === "string" &&
      typeof artifact.download_path === "string",
  );
  return campaignsAreValid && artifactsAreValid;
}

export class ResultOverviewHttpError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ResultOverviewHttpError";
    this.status = status;
  }
}

async function responseError(response: Response): Promise<ResultOverviewHttpError> {
  let payload: ApiErrorPayload | null = null;
  try {
    payload = (await response.json()) as ApiErrorPayload;
  } catch {
    // The status still provides an auditable fallback when the body is invalid.
  }
  const hasStructuredError = typeof payload?.error?.code === "string";
  if (response.status === 404) {
    return new ResultOverviewHttpError(
      "Готовый обзор не найден. Возможно, расчёт ещё выполняется или создан до появления browser overview.",
      response.status,
    );
  }
  return new ResultOverviewHttpError(
    hasStructuredError
      ? "Сервис не смог вернуть обзор результата. Повторите попытку позже."
      : `Не удалось прочитать ответ сервиса (HTTP ${response.status}).`,
    response.status,
  );
}

export function createHttpResultProvider(apiBaseUrl: string): ResultProvider {
  const baseUrl = normalizeBaseUrl(apiBaseUrl);
  return {
    kind: "http",
    async getOverview(jobId) {
      if (!jobId) throw new Error("Не указан расчёт.");
      const response = await fetch(
        `${baseUrl}/api/v1/jobs/${encodeURIComponent(jobId)}/overview`,
        { headers: { Accept: "application/json" } },
      );
      if (!response.ok) throw await responseError(response);
      const payload: unknown = await response.json();
      if (!isResultOverview(payload)) {
        throw new Error("Сервис вернул неполный или неизвестный формат обзора.");
      }
      return payload;
    },
  };
}
