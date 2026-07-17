import type { CalculationProfile } from "./generated/product-api-v1";
import { appEnv } from "../config/env";
import { credentialedFetch } from "./credentialed-fetch";

const CALCULATION_PROFILE_PATH = "/api/v1/calculation-profile";
const CAMPAIGN_TEMPLATE_PATH = "/api/v1/templates/campaign-plan.xlsx";
const PROFILE_KEYS = [
  "contract_name",
  "schema_version",
  "scenario6_attempt_budget",
  "profile_label",
  "model_version_label",
] as const;

type JsonRecord = Record<string, unknown>;

export type { CalculationProfile };

export class CalculationProfileUnavailableError extends Error {
  readonly status = 503;

  constructor() {
    super("Параметры расчета временно недоступны.");
    this.name = "CalculationProfileUnavailableError";
  }
}

export class UnsupportedCalculationProfileError extends Error {
  readonly status: number | null;

  constructor(status: number | null = null) {
    super("Сервис вернул неподдерживаемый формат параметров расчета.");
    this.name = "UnsupportedCalculationProfileError";
    this.status = status;
  }
}

export class CalculationProfileRequestError extends Error {
  readonly status: number | null;

  constructor(status: number | null = null) {
    super("Не удалось получить параметры расчета.");
    this.name = "CalculationProfileRequestError";
    this.status = status;
  }
}

function endpoint(path: string): string {
  return `${appEnv.apiBaseUrl.replace(/\/+$/, "")}${path}`;
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isRequiredText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function parseCalculationProfile(value: unknown): CalculationProfile {
  if (!isRecord(value)) throw new UnsupportedCalculationProfileError();
  const keys = Object.keys(value);
  if (
    keys.length !== PROFILE_KEYS.length
    || PROFILE_KEYS.some((key) => !(key in value))
    || value.contract_name !== "calculation_profile_v1"
    || value.schema_version !== "1.0.0"
    || typeof value.scenario6_attempt_budget !== "number"
    || !Number.isInteger(value.scenario6_attempt_budget)
    || value.scenario6_attempt_budget <= 0
    || !isRequiredText(value.profile_label)
    || !isRequiredText(value.model_version_label)
  ) {
    throw new UnsupportedCalculationProfileError();
  }
  return value as unknown as CalculationProfile;
}

export async function getCalculationProfile(
  signal?: AbortSignal,
): Promise<CalculationProfile> {
  let response: Response;
  try {
    response = await credentialedFetch(endpoint(CALCULATION_PROFILE_PATH), {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new CalculationProfileRequestError();
  }

  if (response.status === 503) throw new CalculationProfileUnavailableError();
  if (response.status === 404) throw new UnsupportedCalculationProfileError(404);
  if (!response.ok) throw new CalculationProfileRequestError(response.status);

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new UnsupportedCalculationProfileError(response.status);
  }
  return parseCalculationProfile(payload);
}

export function campaignPlanTemplateUrl(): string {
  return endpoint(CAMPAIGN_TEMPLATE_PATH);
}
