import type {
  JobProgressViewV1,
  ProductStage,
} from "./generated/job-progress-view-v1";
import type { MMMFactCatalogV1 } from "./generated/mmm-fact-catalog-v1";
import { appEnv } from "../config/env";
import { credentialedFetch } from "./credentialed-fetch";

const PROGRESS_VIEW_PATH = (jobId: string) =>
  `/api/v1/jobs/${encodeURIComponent(jobId)}/progress-view`;
const MMM_FACTS_PATH = "/api/v1/meta/mmm-facts";

const PROGRESS_VIEW_KEYS = [
  "contract_name",
  "schema_version",
  "record_origin",
  "job_id",
  "job_status",
  "queue",
  "campaign",
  "current_stage_id",
  "stages",
  "scenario6",
  "report",
  "errors",
  "can_cancel",
  "result_available",
  "updated_at_utc",
] as const;
const STATUS_KEYS = ["code", "display_text"] as const;
const QUEUE_KEYS = ["position", "queued_jobs_total", "display_text"] as const;
const CAMPAIGN_KEYS = [
  "campaign_id",
  "campaign_name",
  "segment",
  "start_date",
  "end_date",
  "total_budget_rub",
  "channels_n",
  "geographies_n",
] as const;
const STAGE_KEYS = [
  "stage_id",
  "order",
  "title",
  "status",
  "started_at_utc",
  "finished_at_utc",
  "display_text",
  "progress",
] as const;
const STAGE_PROGRESS_KEYS = ["current", "total", "unit"] as const;
const SCENARIO6_KEYS = [
  "status",
  "attempt_budget",
  "attempts_checked",
  "safe_candidates",
  "blocked_candidates",
  "finalists_scored",
  "finalists_total",
] as const;
const REPORT_KEYS = ["status", "display_text", "retryable"] as const;
const ERROR_KEYS = [
  "error_id",
  "stage_id",
  "severity",
  "blocking",
  "retryable",
  "display_text",
  "recommended_action",
] as const;
const FACT_CATALOG_KEYS = ["contract_name", "schema_version", "facts"] as const;
const FACT_KEYS = ["fact_id", "category", "text", "source_label"] as const;

const STAGE_CATALOG = [
  ["P01", "Расчет ожидает запуска"],
  ["P02", "Подготавливаем медиаплан"],
  ["P03", "Рассчитываем исходный медиаплан"],
  ["P04", "Рассчитываем контрольные сценарии"],
  ["P05", "Ищем устойчивый вариант"],
  ["P06", "Перебираем варианты распределения"],
  ["P07", "Проверяем результаты"],
  ["P08", "Формируем отчет"],
  ["P09", "Расчет завершен"],
] as const;

const JOB_STATUSES = [
  "queued",
  "running",
  "cancel_requested",
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
] as const;
const STAGE_STATUSES = [
  "pending",
  "active",
  "completed",
  "warning",
  "failed",
  "skipped",
] as const;
const SCENARIO6_STATUSES = [
  "pending",
  "running",
  "completed",
  "unavailable",
  "failed",
] as const;
const REPORT_STATUSES = [
  "pending",
  "running",
  "completed",
  "failed",
  "not_required",
] as const;
const FACT_CATEGORIES = [
  "adstock",
  "saturation",
  "forecast",
  "uncertainty",
  "support",
  "scenarios",
  "quality",
  "decision",
] as const;

const OPAQUE_ID_RE = /^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$/;
const FACT_ID_RE = /^fact_[a-z0-9_]{3,64}$/;
const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const ABSOLUTE_PATH_RE = /^(?:\/|[A-Za-z]:[\\/]|file:\/\/)/i;

type JsonRecord = Record<string, unknown>;

export class JobProgressNotFoundError extends Error {
  readonly status = 404;

  constructor() {
    super("Расчет не найден.");
    this.name = "JobProgressNotFoundError";
  }
}

export class JobProgressInconsistentError extends Error {
  readonly status = 409;

  constructor() {
    super("Состояние расчета временно не согласовано.");
    this.name = "JobProgressInconsistentError";
  }
}

export class JobProgressUnavailableError extends Error {
  readonly status = 503;

  constructor() {
    super("Сведения о расчете временно недоступны.");
    this.name = "JobProgressUnavailableError";
  }
}

export class JobProgressRequestError extends Error {
  readonly status: number | null;

  constructor(status: number | null = null) {
    super("Не удалось обновить сведения о расчете.");
    this.name = "JobProgressRequestError";
    this.status = status;
  }
}

export class UnsupportedJobProgressContractError extends Error {
  readonly status: number | null;

  constructor(status: number | null = null) {
    super("Сервис вернул неподдерживаемый формат сведений о расчете.");
    this.name = "UnsupportedJobProgressContractError";
    this.status = status;
  }
}

export class MmmFactsUnavailableError extends Error {
  readonly status: number | null;

  constructor(status: number | null = null) {
    super("Факты о MMM временно недоступны.");
    this.name = "MmmFactsUnavailableError";
    this.status = status;
  }
}

export class UnsupportedMmmFactsContractError extends Error {
  readonly status: number | null;

  constructor(status: number | null = null) {
    super("Сервис вернул неподдерживаемый формат фактов о MMM.");
    this.name = "UnsupportedMmmFactsContractError";
    this.status = status;
  }
}

function endpoint(path: string, baseUrl = appEnv.apiBaseUrl): string {
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: JsonRecord, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && expected.every((key) => key in value);
}

function isRequiredText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && OPAQUE_ID_RE.test(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return isNonNegativeInteger(value) && value > 0;
}

function isNullableNonNegativeInteger(value: unknown): value is number | null {
  return value === null || isNonNegativeInteger(value);
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

function isIsoDateTime(value: unknown): value is string {
  return (
    typeof value === "string" &&
    ISO_DATETIME_RE.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function isNullableIsoDateTime(value: unknown): value is string | null {
  return value === null || isIsoDateTime(value);
}

function isEnumValue<T extends readonly string[]>(
  value: unknown,
  allowed: T,
): value is T[number] {
  return typeof value === "string" && allowed.includes(value as T[number]);
}

function hasUniqueRequiredStrings(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(isRequiredText) &&
    new Set(value).size === value.length
  );
}

function containsAbsolutePath(value: unknown): boolean {
  if (typeof value === "string") return ABSOLUTE_PATH_RE.test(value);
  if (Array.isArray(value)) return value.some(containsAbsolutePath);
  return isRecord(value) && Object.values(value).some(containsAbsolutePath);
}

function isStageProgress(value: unknown): boolean {
  if (!isRecord(value) || !hasExactKeys(value, STAGE_PROGRESS_KEYS)) return false;
  if (
    !isNonNegativeInteger(value.current) ||
    !isNullableNonNegativeInteger(value.total) ||
    !isRequiredText(value.unit)
  ) {
    return false;
  }
  return value.total === null || value.current <= value.total;
}

function isStage(
  value: unknown,
  expectedId: (typeof STAGE_CATALOG)[number][0],
  expectedTitle: (typeof STAGE_CATALOG)[number][1],
  expectedOrder: number,
): value is ProductStage {
  if (!isRecord(value) || !hasExactKeys(value, STAGE_KEYS)) return false;
  if (
    value.stage_id !== expectedId ||
    value.order !== expectedOrder ||
    value.title !== expectedTitle ||
    !isEnumValue(value.status, STAGE_STATUSES) ||
    !isNullableIsoDateTime(value.started_at_utc) ||
    !isNullableIsoDateTime(value.finished_at_utc) ||
    !isRequiredText(value.display_text) ||
    (value.progress !== null && !isStageProgress(value.progress))
  ) {
    return false;
  }
  if (value.finished_at_utc !== null && value.started_at_utc === null) {
    return false;
  }
  if (value.status === "pending" && (value.started_at_utc !== null || value.finished_at_utc !== null)) {
    return false;
  }
  if (value.status === "active" && (value.started_at_utc === null || value.finished_at_utc !== null)) {
    return false;
  }
  if (
    (value.status === "completed" || value.status === "failed") &&
    (value.started_at_utc === null || value.finished_at_utc === null)
  ) {
    return false;
  }
  return !(
    value.started_at_utc !== null &&
    value.finished_at_utc !== null &&
    Date.parse(value.finished_at_utc) < Date.parse(value.started_at_utc)
  );
}

function isProgressError(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, ERROR_KEYS) &&
    isOpaqueId(value.error_id) &&
    STAGE_CATALOG.some(([stageId]) => stageId === value.stage_id) &&
    (value.severity === "warning" || value.severity === "error") &&
    typeof value.blocking === "boolean" &&
    typeof value.retryable === "boolean" &&
    isRequiredText(value.display_text) &&
    isRequiredText(value.recommended_action)
  );
}

function isScenario6Progress(
  value: unknown,
): value is JobProgressViewV1["scenario6"] {
  return (
    isRecord(value) &&
    hasExactKeys(value, SCENARIO6_KEYS) &&
    isEnumValue(value.status, SCENARIO6_STATUSES) &&
    SCENARIO6_KEYS.slice(1).every((key) =>
      isNullableNonNegativeInteger(value[key]),
    )
  );
}

export function parseJobProgressView(
  value: unknown,
  expectedJobId: string,
): JobProgressViewV1 {
  if (!isRecord(value) || !hasExactKeys(value, PROGRESS_VIEW_KEYS)) {
    throw new UnsupportedJobProgressContractError();
  }
  if (
    value.contract_name !== "job_progress_view_v1" ||
    value.schema_version !== "1.0.0" ||
    (value.record_origin !== "application_runtime" && value.record_origin !== "synthetic_fixture") ||
    !isOpaqueId(value.job_id) ||
    value.job_id !== expectedJobId ||
    !isRecord(value.job_status) ||
    !hasExactKeys(value.job_status, STATUS_KEYS) ||
    !isEnumValue(value.job_status.code, JOB_STATUSES) ||
    !isRequiredText(value.job_status.display_text) ||
    !isRecord(value.queue) ||
    !hasExactKeys(value.queue, QUEUE_KEYS) ||
    !isNullableNonNegativeInteger(value.queue.position) ||
    !isNullableNonNegativeInteger(value.queue.queued_jobs_total) ||
    !isRequiredText(value.queue.display_text) ||
    !isRecord(value.campaign) ||
    !hasExactKeys(value.campaign, CAMPAIGN_KEYS) ||
    !isOpaqueId(value.campaign.campaign_id) ||
    !isRequiredText(value.campaign.campaign_name) ||
    !hasUniqueRequiredStrings(value.campaign.segment) ||
    !isIsoDate(value.campaign.start_date) ||
    !isIsoDate(value.campaign.end_date) ||
    value.campaign.start_date > value.campaign.end_date ||
    typeof value.campaign.total_budget_rub !== "number" ||
    !Number.isFinite(value.campaign.total_budget_rub) ||
    value.campaign.total_budget_rub < 0 ||
    !isPositiveInteger(value.campaign.channels_n) ||
    !isPositiveInteger(value.campaign.geographies_n) ||
    !STAGE_CATALOG.some(([stageId]) => stageId === value.current_stage_id) ||
    !Array.isArray(value.stages) ||
    value.stages.length !== STAGE_CATALOG.length ||
    !value.stages.every((stage, index) =>
      isStage(stage, STAGE_CATALOG[index][0], STAGE_CATALOG[index][1], index + 1),
    ) ||
    !isScenario6Progress(value.scenario6) ||
    !isRecord(value.report) ||
    !hasExactKeys(value.report, REPORT_KEYS) ||
    !isEnumValue(value.report.status, REPORT_STATUSES) ||
    !isRequiredText(value.report.display_text) ||
    typeof value.report.retryable !== "boolean" ||
    !Array.isArray(value.errors) ||
    !value.errors.every(isProgressError) ||
    typeof value.can_cancel !== "boolean" ||
    typeof value.result_available !== "boolean" ||
    !isIsoDateTime(value.updated_at_utc)
  ) {
    throw new UnsupportedJobProgressContractError();
  }

  const status = value.job_status.code;
  const scenario6 = value.scenario6 as JobProgressViewV1["scenario6"];
  const terminal = ["succeeded", "failed", "cancelled", "timed_out"].includes(status);
  const updatedAt = Date.parse(value.updated_at_utc);
  const stages = value.stages as ProductStage[];
  const startedAt = stages
    .map((stage) => stage.started_at_utc)
    .filter((timestamp): timestamp is string => timestamp !== null)
    .map(Date.parse);
  const stageTimesAreOrdered = startedAt.every(
    (timestamp, index) => index === 0 || timestamp >= startedAt[index - 1],
  );
  const stageTimesAreCurrent = stages.every((stage) =>
    [stage.started_at_utc, stage.finished_at_utc].every(
      (timestamp) => timestamp === null || Date.parse(timestamp) <= updatedAt,
    ),
  );
  const queueIsCoherent = status === "queued"
    ? value.queue.position === null || (
        value.queue.position >= 1 &&
        value.queue.queued_jobs_total !== null &&
        value.queue.position <= value.queue.queued_jobs_total
      )
    : value.queue.position === null;
  const scenario6CountersAreCoherent =
    (scenario6.attempt_budget === null ||
      scenario6.attempts_checked === null ||
      scenario6.attempts_checked <= scenario6.attempt_budget) &&
    (scenario6.finalists_total === null ||
      scenario6.finalists_scored === null ||
      scenario6.finalists_scored <= scenario6.finalists_total);
  const terminalIsCoherent =
    (!terminal || !stages.some((stage) => stage.status === "active")) &&
    (value.can_cancel === (status === "queued" || status === "running")) &&
    (!value.result_available || status === "succeeded") &&
    (status !== "succeeded" || (
      value.result_available === true &&
      stages[8].status === "completed" &&
      value.report.status === "completed"
    ));

  if (
    !queueIsCoherent ||
    !scenario6CountersAreCoherent ||
    !terminalIsCoherent ||
    !stageTimesAreOrdered ||
    !stageTimesAreCurrent ||
    containsAbsolutePath(value)
  ) {
    throw new UnsupportedJobProgressContractError();
  }
  return value as unknown as JobProgressViewV1;
}

export function parseMmmFactCatalog(value: unknown): MMMFactCatalogV1 {
  if (!isRecord(value) || !hasExactKeys(value, FACT_CATALOG_KEYS)) {
    throw new UnsupportedMmmFactsContractError();
  }
  if (
    value.contract_name !== "mmm_fact_catalog_v1" ||
    value.schema_version !== "1.0.0" ||
    !Array.isArray(value.facts) ||
    value.facts.length < 20
  ) {
    throw new UnsupportedMmmFactsContractError();
  }
  const ids = new Set<string>();
  for (const fact of value.facts) {
    if (
      !isRecord(fact) ||
      !hasExactKeys(fact, FACT_KEYS) ||
      typeof fact.fact_id !== "string" ||
      !FACT_ID_RE.test(fact.fact_id) ||
      ids.has(fact.fact_id) ||
      !isEnumValue(fact.category, FACT_CATEGORIES) ||
      !isRequiredText(fact.text) ||
      fact.text.length > 280 ||
      !isRequiredText(fact.source_label)
    ) {
      throw new UnsupportedMmmFactsContractError();
    }
    ids.add(fact.fact_id);
  }
  if (containsAbsolutePath(value)) throw new UnsupportedMmmFactsContractError();
  return value as unknown as MMMFactCatalogV1;
}

async function responseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

export async function getJobProgressView(
  jobId: string,
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<JobProgressViewV1> {
  let response: Response;
  try {
    response = await credentialedFetch(endpoint(PROGRESS_VIEW_PATH(jobId), baseUrl), {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new JobProgressRequestError();
  }
  if (response.status === 404) throw new JobProgressNotFoundError();
  if (response.status === 409) throw new JobProgressInconsistentError();
  if (response.status === 503) throw new JobProgressUnavailableError();
  if (!response.ok) throw new JobProgressRequestError(response.status);
  const payload = await responseJson(response);
  if (payload === undefined) throw new UnsupportedJobProgressContractError(response.status);
  return parseJobProgressView(payload, jobId);
}

export async function getMmmFacts(
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<MMMFactCatalogV1> {
  let response: Response;
  try {
    response = await credentialedFetch(endpoint(MMM_FACTS_PATH, baseUrl), {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new MmmFactsUnavailableError();
  }
  if (!response.ok) throw new MmmFactsUnavailableError(response.status);
  const payload = await responseJson(response);
  if (payload === undefined) throw new UnsupportedMmmFactsContractError(response.status);
  return parseMmmFactCatalog(payload);
}
