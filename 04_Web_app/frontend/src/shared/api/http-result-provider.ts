import type { DecisionResultV1 } from "../../entities/decision-result/types";
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

function isDecisionResult(value: unknown): value is DecisionResultV1 {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<DecisionResultV1>;
  return (
    candidate.contract_name === "decision_result_v1" &&
    candidate.schema_version === "1.0.0" &&
    typeof candidate.result_id === "string" &&
    typeof candidate.job?.job_id === "string" &&
    Array.isArray(candidate.campaign_results)
  );
}

async function responseError(response: Response): Promise<Error> {
  let payload: ApiErrorPayload | null = null;
  try {
    payload = (await response.json()) as ApiErrorPayload;
  } catch {
    // The status still provides an auditable fallback when the body is invalid.
  }
  const detail = payload?.error?.display_text;
  if (response.status === 404) {
    return new Error(detail ?? "Результат ещё не готов или расчёт не найден.");
  }
  return new Error(detail ?? `Backend вернул ошибку HTTP ${response.status}.`);
}

export function createHttpResultProvider(apiBaseUrl: string): ResultProvider {
  const baseUrl = normalizeBaseUrl(apiBaseUrl);
  return {
    kind: "http",
    async getResult(jobId) {
      if (!jobId) throw new Error("Не указан job_id расчёта.");
      const response = await fetch(
        `${baseUrl}/api/v1/jobs/${encodeURIComponent(jobId)}/result`,
        { headers: { Accept: "application/json" } },
      );
      if (!response.ok) throw await responseError(response);
      const payload: unknown = await response.json();
      if (!isDecisionResult(payload)) {
        throw new Error("Backend вернул результат неизвестного формата.");
      }
      return payload;
    },
  };
}
