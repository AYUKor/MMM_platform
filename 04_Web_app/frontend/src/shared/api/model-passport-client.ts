import type { ModelPassportV1 } from "../../entities/model-passport/types";
import { appEnv } from "../config/env";

const MODEL_PASSPORT_PATH = "/api/v1/models/active";
const CONTRACT_KEYS = [
  "contract_name",
  "schema_version",
  "record_origin",
  "serving",
  "package",
  "data",
  "coverage",
  "validation",
  "caveats",
] as const;
const SERVING_KEYS = [
  "deployment_profile",
  "display_name",
  "calculation_allowed",
  "decision_scope",
  "production_claim_allowed",
] as const;
const PACKAGE_KEYS = [
  "registry_channel",
  "registry_event_id",
  "package_id",
  "package_fingerprint",
  "model_run_id",
  "package_stage",
  "activation_status",
  "package_schema_version",
  "gate_policy_version",
] as const;
const DATA_KEYS = ["grain", "training_period", "development_shadow_period"] as const;
const PERIOD_KEYS = ["start_date", "end_date"] as const;
const SHADOW_PERIOD_KEYS = ["start_date", "end_date", "purpose"] as const;
const COVERAGE_KEYS = [
  "segments",
  "channels",
  "targets",
  "geographies_n",
  "capability_cells_n",
  "allowed_use_counts",
  "channel_policies",
] as const;
const ALLOWED_USE_CODES = ["primary", "caution", "diagnostic", "unavailable"] as const;
const TARGET_KEYS = ["target", "allowed_use_counts", "objective_roles"] as const;
const POLICY_KEYS = [
  "segment",
  "channel",
  "target",
  "allowed_use",
  "forecast_action",
  "optimizer_action",
  "display_text",
] as const;
const VALIDATION_KEYS = ["historical_replay", "sealed_oot", "production_blockers"] as const;
const EVIDENCE_KEYS = ["status", "generated_at_utc", "reason_code", "display_text"] as const;
const STATUS_KEYS = ["code", "display_text"] as const;
const EVIDENCE_STATUSES = ["passed", "unavailable", "failed"] as const;
const PACKAGE_ID_RE = /^pkg_[0-9a-f]{16}_[0-9a-f]{16}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ABSOLUTE_PATH_RE = /^(?:\/|[A-Za-z]:[\\/]|file:\/\/)/i;

type JsonRecord = Record<string, unknown>;

export class ModelPassportUnavailableError extends Error {
  readonly status = 503;
  readonly retryable = true;

  constructor() {
    super("Паспорт активной модели временно недоступен. Повторите попытку позже.");
    this.name = "ModelPassportUnavailableError";
  }
}

export class UnsupportedModelPassportContractError extends Error {
  readonly status: number | null;

  constructor(status: number | null = null) {
    super("Сервис вернул неподдерживаемую версию паспорта модели.");
    this.name = "UnsupportedModelPassportContractError";
    this.status = status;
  }
}

export class ModelPassportRequestError extends Error {
  readonly status: number | null;
  readonly retryable: boolean;

  constructor(status: number | null = null) {
    super("Не удалось получить паспорт модели. Повторите попытку позже.");
    this.name = "ModelPassportRequestError";
    this.status = status;
    this.retryable = status === null || status >= 500;
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: JsonRecord, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && expected.every((key) => key in value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isRequiredText(value: unknown): value is string {
  return isNonEmptyString(value) && value.trim().length > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function hasUniqueStrings(values: unknown, requireNonEmpty: boolean): values is string[] {
  if (!Array.isArray(values) || values.some((value) => typeof value !== "string")) {
    return false;
  }
  if (requireNonEmpty && values.some((value) => value.length === 0)) return false;
  return new Set(values).size === values.length;
}

function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = ISO_DATE_RE.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

function isOrderedPeriod(value: unknown): value is ModelPassportV1["data"]["training_period"] {
  if (!isRecord(value) || !hasExactKeys(value, PERIOD_KEYS)) return false;
  return (
    isIsoDate(value.start_date) &&
    isIsoDate(value.end_date) &&
    value.start_date <= value.end_date
  );
}

function isShadowPeriod(
  value: unknown,
): value is ModelPassportV1["data"]["development_shadow_period"] {
  if (!isRecord(value) || !hasExactKeys(value, SHADOW_PERIOD_KEYS)) return false;
  if (value.purpose !== "development_shadow_not_sealed_oot") return false;
  const bothAbsent = value.start_date === null && value.end_date === null;
  if (bothAbsent) return true;
  if (!isIsoDate(value.start_date) || !isIsoDate(value.end_date)) return false;
  return value.start_date <= value.end_date;
}

function isAllowedUse(value: unknown): value is ModelPassportV1["coverage"]["channel_policies"][number]["allowed_use"] {
  return typeof value === "string" && ALLOWED_USE_CODES.includes(
    value as (typeof ALLOWED_USE_CODES)[number],
  );
}

function isAllowedUseCountRecord(value: unknown, requireEveryCode: boolean): value is JsonRecord {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value);
  if (
    keys.some((key) => !ALLOWED_USE_CODES.includes(key as (typeof ALLOWED_USE_CODES)[number])) ||
    Object.values(value).some((count) => !isNonNegativeInteger(count))
  ) {
    return false;
  }
  return !requireEveryCode || hasExactKeys(value, ALLOWED_USE_CODES);
}

function isTargetSummary(value: unknown): value is ModelPassportV1["coverage"]["targets"][number] {
  return (
    isRecord(value) &&
    hasExactKeys(value, TARGET_KEYS) &&
    isRequiredText(value.target) &&
    isAllowedUseCountRecord(value.allowed_use_counts, false) &&
    hasUniqueStrings(value.objective_roles, false)
  );
}

function isChannelPolicyShape(
  value: unknown,
): value is ModelPassportV1["coverage"]["channel_policies"][number] {
  return (
    isRecord(value) &&
    hasExactKeys(value, POLICY_KEYS) &&
    isRequiredText(value.segment) &&
    isRequiredText(value.channel) &&
    isRequiredText(value.target) &&
    isAllowedUse(value.allowed_use) &&
    isRequiredText(value.forecast_action) &&
    isRequiredText(value.optimizer_action) &&
    isRequiredText(value.display_text)
  );
}

function isEvidenceStatus(
  value: unknown,
): value is ModelPassportV1["validation"]["historical_replay"] {
  return (
    isRecord(value) &&
    hasExactKeys(value, EVIDENCE_KEYS) &&
    typeof value.status === "string" &&
    EVIDENCE_STATUSES.includes(value.status as (typeof EVIDENCE_STATUSES)[number]) &&
    (value.generated_at_utc === null || typeof value.generated_at_utc === "string") &&
    (value.reason_code === null || typeof value.reason_code === "string") &&
    isNonEmptyString(value.display_text)
  );
}

function isStatus(value: unknown): value is ModelPassportV1["caveats"][number] {
  return (
    isRecord(value) &&
    hasExactKeys(value, STATUS_KEYS) &&
    isNonEmptyString(value.code) &&
    isNonEmptyString(value.display_text)
  );
}

function containsAbsolutePath(value: unknown): boolean {
  if (typeof value === "string") return ABSOLUTE_PATH_RE.test(value);
  if (Array.isArray(value)) return value.some(containsAbsolutePath);
  return isRecord(value) && Object.values(value).some(containsAbsolutePath);
}

function isCoverage(value: unknown): value is ModelPassportV1["coverage"] {
  if (!isRecord(value) || !hasExactKeys(value, COVERAGE_KEYS)) return false;
  const allowedUseCounts = value.allowed_use_counts;
  if (
    !hasUniqueStrings(value.segments, true) ||
    !hasUniqueStrings(value.channels, true) ||
    !Array.isArray(value.targets) ||
    !value.targets.every(isTargetSummary) ||
    !isNonNegativeInteger(value.geographies_n) ||
    !isNonNegativeInteger(value.capability_cells_n) ||
    !isAllowedUseCountRecord(allowedUseCounts, true) ||
    !Array.isArray(value.channel_policies) ||
    !value.channel_policies.every(isChannelPolicyShape)
  ) {
    return false;
  }

  const targetNames = value.targets.map((entry) => entry.target);
  if (new Set(targetNames).size !== targetNames.length) return false;

  const segments = new Set(value.segments);
  const channels = new Set(value.channels);
  const targets = new Set(targetNames);
  const policyKeys = new Set<string>();
  const policyCounts: Record<(typeof ALLOWED_USE_CODES)[number], number> = {
    primary: 0,
    caution: 0,
    diagnostic: 0,
    unavailable: 0,
  };

  for (const policy of value.channel_policies) {
    if (
      !segments.has(policy.segment) ||
      !channels.has(policy.channel) ||
      !targets.has(policy.target)
    ) {
      return false;
    }
    const key = JSON.stringify([policy.segment, policy.channel, policy.target]);
    if (policyKeys.has(key)) return false;
    policyKeys.add(key);
    policyCounts[policy.allowed_use] += 1;
  }

  const totalCount = ALLOWED_USE_CODES.reduce(
    (total, code) => total + (allowedUseCounts[code] as number),
    0,
  );
  return (
    value.channel_policies.length === value.capability_cells_n &&
    totalCount === value.capability_cells_n &&
    ALLOWED_USE_CODES.every(
      (code) => policyCounts[code] === allowedUseCounts[code],
    )
  );
}

function isModelPassport(value: unknown): value is ModelPassportV1 {
  if (!isRecord(value) || !hasExactKeys(value, CONTRACT_KEYS)) return false;
  if (
    value.contract_name !== "model_passport_v1" ||
    value.schema_version !== "1.0.0" ||
    (value.record_origin !== "verified_model_package" &&
      value.record_origin !== "synthetic_fixture")
  ) {
    return false;
  }

  const serving = value.serving;
  const packageInfo = value.package;
  const data = value.data;
  const validation = value.validation;
  if (
    !isRecord(serving) ||
    !hasExactKeys(serving, SERVING_KEYS) ||
    (serving.deployment_profile !== "local_development" &&
      serving.deployment_profile !== "research_pilot") ||
    !isNonEmptyString(serving.display_name) ||
    typeof serving.calculation_allowed !== "boolean" ||
    serving.decision_scope !== "forecast_and_allocation_only" ||
    serving.production_claim_allowed !== false ||
    !isRecord(packageInfo) ||
    !hasExactKeys(packageInfo, PACKAGE_KEYS) ||
    !isNonEmptyString(packageInfo.registry_channel) ||
    !isNonEmptyString(packageInfo.registry_event_id) ||
    typeof packageInfo.package_id !== "string" ||
    !PACKAGE_ID_RE.test(packageInfo.package_id) ||
    typeof packageInfo.package_fingerprint !== "string" ||
    !SHA256_RE.test(packageInfo.package_fingerprint) ||
    !isNonEmptyString(packageInfo.model_run_id) ||
    !isNonEmptyString(packageInfo.package_stage) ||
    !isNonEmptyString(packageInfo.activation_status) ||
    !isNonEmptyString(packageInfo.package_schema_version) ||
    !isNonEmptyString(packageInfo.gate_policy_version) ||
    !isRecord(data) ||
    !hasExactKeys(data, DATA_KEYS) ||
    data.grain !== "daily" ||
    !isOrderedPeriod(data.training_period) ||
    !isShadowPeriod(data.development_shadow_period) ||
    !isCoverage(value.coverage) ||
    !isRecord(validation) ||
    !hasExactKeys(validation, VALIDATION_KEYS) ||
    !isEvidenceStatus(validation.historical_replay) ||
    !isEvidenceStatus(validation.sealed_oot) ||
    !Array.isArray(validation.production_blockers) ||
    !validation.production_blockers.every(isStatus) ||
    !Array.isArray(value.caveats) ||
    !value.caveats.every(isStatus)
  ) {
    return false;
  }

  return !containsAbsolutePath(value);
}

function isUnavailablePayload(value: unknown): boolean {
  return (
    isRecord(value) &&
    isRecord(value.error) &&
    value.error.code === "MODEL_PASSPORT_UNAVAILABLE" &&
    isRequiredText(value.error.display_text) &&
    value.error.retryable === true &&
    isRequiredText(value.error.user_action)
  );
}

function apiUrl(baseUrl: string): string {
  return `${baseUrl.replace(/\/+$/, "")}${MODEL_PASSPORT_PATH}`;
}

export async function getActiveModelPassport(
  baseUrl = appEnv.apiBaseUrl,
): Promise<ModelPassportV1> {
  let response: Response;
  try {
    response = await fetch(apiUrl(baseUrl), {
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new ModelPassportRequestError();
  }

  if (response.status === 404) {
    throw new UnsupportedModelPassportContractError(404);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (response.ok) {
      throw new UnsupportedModelPassportContractError(response.status);
    }
    throw new ModelPassportRequestError(response.status);
  }

  if (response.status === 503 && isUnavailablePayload(payload)) {
    throw new ModelPassportUnavailableError();
  }
  if (!response.ok) {
    throw new ModelPassportRequestError(response.status);
  }
  if (!isModelPassport(payload)) {
    throw new UnsupportedModelPassportContractError(response.status);
  }
  return payload;
}
