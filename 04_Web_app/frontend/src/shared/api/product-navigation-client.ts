import type { CalculationHistoryV1 } from "./generated/calculation-history-v1";
import type { HelpCatalogV1 } from "./generated/help-catalog-v1";
import type { ModelOverviewV1 } from "./generated/model-overview-v1";
import type { WorkspaceHomeV1 } from "./generated/workspace-home-v1";
import { appEnv } from "../config/env";
import { credentialedFetch } from "./credentialed-fetch";

const WORKSPACE_HOME_PATH = "/api/v1/workspace/home";
const CALCULATION_HISTORY_PATH = "/api/v1/calculations/history";
const MODEL_OVERVIEW_PATH = "/api/v1/model/overview";
const HELP_CATALOG_PATH = "/api/v1/help/catalog";

const JOB_STATUSES = [
  "queued",
  "running",
  "cancel_requested",
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
] as const;
const ACTIVE_STATUSES = ["queued", "running", "cancel_requested"] as const;
const TERMINAL_STATUSES = ["succeeded", "failed", "cancelled", "timed_out"] as const;
const HISTORY_STATUSES = ["active", ...JOB_STATUSES] as const;
const HISTORY_SORTS = [
  "created_desc",
  "created_asc",
  "completed_desc",
  "campaign_asc",
] as const;
const STAGE_STATUSES = [
  "pending",
  "active",
  "completed",
  "warning",
  "failed",
  "skipped",
] as const;
const CAPABILITY_IDS = [
  "incremental_effect_forecast",
  "six_scenarios",
  "budget_allocation",
  "safe_recommendation",
  "marketer_report",
] as const;
const CAPABILITY_STATUSES = ["available", "conditional", "unavailable"] as const;
const METHODOLOGY_IDS = [
  "carryover",
  "saturation",
  "uncertainty",
  "counterfactual_forecast",
  "scenario_search",
  "reliability_guardrails",
] as const;
const HELP_SECTION_IDS = [
  "getting_started",
  "data_preparation",
  "scenarios",
  "result_reading",
  "reliability",
  "media_plan",
  "report",
  "common_errors",
  "limitations",
] as const;
const SAFE_HELP_ROUTES = ["/", "/calculations", "/calculations/new", "/model", "/help"] as const;
const QUICK_ACTION_IDS = [
  "new_calculation",
  "calculation_history",
  "model_overview",
  "help_catalog",
] as const;

const HOME_KEYS = [
  "contract_name",
  "schema_version",
  "record_origin",
  "summary",
  "active_calculations",
  "recent_calculations",
  "model",
  "quick_actions",
  "warnings",
  "updated_at_utc",
] as const;
const HOME_SUMMARY_KEYS = ["running", "queued", "completed_30d", "failed_30d"] as const;
const ACTIVE_CALCULATION_KEYS = [
  "job_id",
  "campaign_name",
  "status",
  "current_stage",
  "created_at_utc",
  "progress_path",
  "can_cancel",
  "display_text",
] as const;
const STATUS_KEYS = ["code", "display_text"] as const;
const CURRENT_STAGE_KEYS = ["stage_id", "title", "status", "display_text"] as const;
const RECENT_CALCULATION_KEYS = [
  "job_id",
  "campaign_name",
  "campaign_period",
  "total_budget_rub",
  "created_at_utc",
  "completed_at_utc",
  "status",
  "result_available",
  "report_available",
  "result_path",
  "progress_path",
  "warnings_count",
] as const;
const PERIOD_KEYS = ["start_date", "end_date"] as const;
const HOME_MODEL_KEYS = [
  "status",
  "model_id",
  "display_name",
  "version",
  "published_at_utc",
  "training_period",
  "supported_scope",
  "description",
  "details_path",
] as const;
const HOME_SCOPE_KEYS = ["segments", "channels", "targets", "geographies_n"] as const;
const QUICK_ACTION_KEYS = ["action_id", "title", "description", "path"] as const;
const WARNING_KEYS = [
  "code",
  "severity",
  "title",
  "display_text",
  "recommended_action",
  "path",
] as const;

const HISTORY_KEYS = [
  "contract_name",
  "schema_version",
  "record_origin",
  "summary",
  "filters",
  "pagination",
  "items",
  "updated_at_utc",
] as const;
const HISTORY_SUMMARY_KEYS = ["all", "active", "succeeded", "failed", "cancelled", "timed_out"] as const;
const HISTORY_FILTER_KEYS = ["status", "search", "created_from", "created_to", "sort"] as const;
const PAGINATION_KEYS = ["page", "page_size", "total_items", "total_pages"] as const;
const HISTORY_ITEM_KEYS = [
  "job_id",
  "campaign_name",
  "created_at_utc",
  "completed_at_utc",
  "status",
  "status_display_text",
  "campaign_period",
  "total_budget_rub",
  "segments",
  "channels_n",
  "geographies_n",
  "result_available",
  "report_available",
  "progress_path",
  "result_path",
  "warnings_count",
] as const;

const MODEL_KEYS = [
  "contract_name",
  "schema_version",
  "record_origin",
  "active_model",
  "capabilities",
  "data_requirements",
  "methodology",
  "limitations",
  "versions",
  "artifacts",
  "updated_at_utc",
] as const;
const ACTIVE_MODEL_KEYS = [
  "status",
  "model_id",
  "display_name",
  "version",
  "published_at_utc",
  "framework",
  "purpose",
  "training_period",
  "supported_scope",
  "description",
] as const;
const MODEL_SCOPE_KEYS = [
  "segments",
  "channels",
  "targets",
  "geographies_n",
  "capability_cells_n",
  "allowed_use_counts",
] as const;
const ALLOWED_USE_KEYS = ["primary", "caution", "diagnostic", "unavailable"] as const;
const CAPABILITY_KEYS = ["capability_id", "title", "status", "description"] as const;
const REQUIREMENT_KEYS = [
  "requirement_id",
  "title",
  "required",
  "description",
  "accepted_values",
] as const;
const METHODOLOGY_KEYS = ["method_id", "title", "summary"] as const;
const LIMITATION_KEYS = ["code", "status", "title", "display_text", "recommended_action"] as const;
const VERSION_KEYS = [
  "model_id",
  "model_run_id",
  "registered_at_utc",
  "package_stage",
  "activation_status",
  "status",
  "source",
] as const;
const ARTIFACT_KEYS = ["artifact_id", "title", "status", "path", "display_text"] as const;

const HELP_KEYS = ["contract_name", "schema_version", "record_origin", "sections", "updated_at_utc"] as const;
const SECTION_KEYS = ["section_id", "order", "title", "articles"] as const;
const ARTICLE_KEYS = [
  "article_id",
  "title",
  "summary",
  "body",
  "related_routes",
  "related_article_ids",
  "keywords",
] as const;
const PARAGRAPH_KEYS = ["block_type", "text"] as const;
const STEPS_KEYS = ["block_type", "items"] as const;
const NOTE_KEYS = ["block_type", "tone", "title", "text"] as const;
const API_ERROR_ROOT_KEYS = ["error"] as const;
const API_ERROR_KEYS = ["code", "display_text", "retryable", "user_action"] as const;

const OPAQUE_ID_RE = /^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$/;
const MODEL_ID_RE = /^pkg_[0-9a-f]{16}_[0-9a-f]{16}$/;
const ARTICLE_ID_RE = /^[a-z][a-z0-9_]{2,80}$/;
const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const ABSOLUTE_PATH_RE = /^(?:\/|[A-Za-z]:[\\/]|file:\/\/)/i;
const UNSAFE_HELP_CONTENT_RE = /<[^>]*>|javascript:|data:text\/html|on(?:error|load|click)\s*=/i;
const PRESENTATION_TERMS = [
  "backend",
  "api",
  "worker",
  "stack trace",
  "local path",
  "model package",
  "internal registry",
] as const;
const HELP_FORBIDDEN_TERMS = [
  "backend",
  "stack trace",
  "worker id",
  "local path",
  "model package",
  "internal registry",
] as const;

type JsonRecord = Record<string, unknown>;
export type HistoryStatus = (typeof HISTORY_STATUSES)[number];
export type HistorySort = (typeof HISTORY_SORTS)[number];
export type ProductNavigationContract =
  | "workspace_home_v1"
  | "calculation_history_v1"
  | "model_overview_v1"
  | "help_catalog_v1";

export interface CalculationHistoryQuery {
  page?: number;
  pageSize?: number;
  status?: HistoryStatus | null;
  search?: string | null;
  createdFrom?: string | null;
  createdTo?: string | null;
  sort?: HistorySort;
}

export type HistoryQuery = CalculationHistoryQuery;

export interface NormalizedCalculationHistoryQuery {
  page: number;
  pageSize: number;
  status: HistoryStatus | null;
  search: string | null;
  createdFrom: string | null;
  createdTo: string | null;
  sort: HistorySort;
}

interface ApiErrorPayload {
  code: string;
  displayText: string;
  retryable: boolean;
  userAction: string;
}

export class ProductNavigationQueryInvalidError extends Error {
  readonly status = 422;
  readonly code = "PRODUCT_NAVIGATION_QUERY_INVALID";
  readonly retryable: boolean;
  readonly userAction: string;

  constructor(
    displayText = "Параметры просмотра заполнены некорректно.",
    userAction = "Исправьте фильтры или параметры страницы и повторите запрос.",
    retryable = true,
  ) {
    super(displayText);
    this.name = "ProductNavigationQueryInvalidError";
    this.retryable = retryable;
    this.userAction = userAction;
  }
}

export class ProductNavigationInconsistentError extends Error {
  readonly status = 409;
  readonly code = "PRODUCT_NAVIGATION_INCONSISTENT";
  readonly retryable: boolean;
  readonly userAction: string;

  constructor(
    displayText = "Опубликованные сведения не согласованы между собой.",
    userAction = "Не используйте спорные данные и сообщите ответственному за инструмент.",
    retryable = false,
  ) {
    super(displayText);
    this.name = "ProductNavigationInconsistentError";
    this.retryable = retryable;
    this.userAction = userAction;
  }
}

export class ProductNavigationUnavailableError extends Error {
  readonly status = 503;
  readonly code = "PRODUCT_NAVIGATION_UNAVAILABLE";
  readonly retryable: boolean;
  readonly userAction: string;

  constructor(
    displayText = "Сведения для этой страницы временно недоступны.",
    userAction = "Обновите страницу позже.",
    retryable = true,
  ) {
    super(displayText);
    this.name = "ProductNavigationUnavailableError";
    this.retryable = retryable;
    this.userAction = userAction;
  }
}

export class ProductNavigationRequestError extends Error {
  readonly status: number | null;
  readonly retryable: boolean;

  constructor(status: number | null = null) {
    super("Не удалось получить сведения для страницы.");
    this.name = "ProductNavigationRequestError";
    this.status = status;
    this.retryable = status === null || status >= 500;
  }
}

export class UnsupportedProductNavigationContractError extends Error {
  readonly status: number | null;
  readonly contract: ProductNavigationContract;

  constructor(contract: ProductNavigationContract, status: number | null = null) {
    super("Сервис вернул неподдерживаемый формат сведений.");
    this.name = "UnsupportedProductNavigationContractError";
    this.contract = contract;
    this.status = status;
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertRecord(value: unknown, fail: () => never): asserts value is JsonRecord {
  if (!isRecord(value)) fail();
}

function hasExactKeys(value: JsonRecord, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && expected.every((key) => key in value);
}

function isEnum<T extends readonly string[]>(value: unknown, allowed: T): value is T[number] {
  return typeof value === "string" && allowed.includes(value as T[number]);
}

function isRequiredText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isNullableText(value: unknown): value is string | null {
  return value === null || isRequiredText(value);
}

function isSafePresentationText(value: unknown): value is string {
  if (!isRequiredText(value) || ABSOLUTE_PATH_RE.test(value)) return false;
  const normalized = value.toLocaleLowerCase();
  return !PRESENTATION_TERMS.some((term) => normalized.includes(term));
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function hasNonNegativeIntegerFields(value: unknown, keys: readonly string[]): value is JsonRecord {
  return isRecord(value) && hasExactKeys(value, keys) &&
    keys.every((key) => isNonNegativeInteger(value[key]));
}

function isPositiveInteger(value: unknown): value is number {
  return isNonNegativeInteger(value) && value > 0;
}

function isNonNegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isNullableNonNegativeInteger(value: unknown): value is number | null {
  return value === null || isNonNegativeInteger(value);
}

function isNullableNonNegativeNumber(value: unknown): value is number | null {
  return value === null || isNonNegativeNumber(value);
}

function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = ISO_DATE_RE.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}

function isIsoDateTime(value: unknown): value is string {
  return typeof value === "string" && ISO_DATETIME_RE.test(value) && Number.isFinite(Date.parse(value));
}

function isNullableIsoDateTime(value: unknown): value is string | null {
  return value === null || isIsoDateTime(value);
}

function isOrderedPeriod(value: unknown): boolean {
  return isRecord(value) && hasExactKeys(value, PERIOD_KEYS) &&
    isIsoDate(value.start_date) && isIsoDate(value.end_date) && value.start_date <= value.end_date;
}

function hasUniqueStrings(value: unknown, minimum = 0): value is string[] {
  return Array.isArray(value) && value.length >= minimum && value.every(isRequiredText) &&
    new Set(value).size === value.length;
}

export function isSafeInternalPath(value: unknown): value is string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return false;
  }
  let url: URL;
  try {
    url = new URL(value, "https://x5.local");
  } catch {
    return false;
  }
  if (url.origin !== "https://x5.local") return false;
  const pathSegments = url.pathname.split("/");
  if (pathSegments.includes("..")) return false;
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(url.pathname);
  } catch {
    return false;
  }
  if (decodedPath.split("/").includes("..")) return false;
  return !/^\/(?:Users|home|private|tmp|var)(?:\/|$)/i.test(decodedPath);
}

function containsAbsolutePathLeak(value: unknown, fieldName: string | null = null): boolean {
  if (typeof value === "string") {
    if (!ABSOLUTE_PATH_RE.test(value)) return false;
    if (fieldName === "related_routes") return !isEnum(value, SAFE_HELP_ROUTES);
    if (fieldName === "path" || fieldName?.endsWith("_path")) return !isSafeInternalPath(value);
    return true;
  }
  if (Array.isArray(value)) {
    return value.some((nested) => containsAbsolutePathLeak(nested, fieldName));
  }
  return isRecord(value) && Object.entries(value)
    .some(([key, nested]) => containsAbsolutePathLeak(nested, key));
}

function containsForbiddenScore(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(containsForbiddenScore);
  if (!isRecord(value)) return false;
  return Object.entries(value).some(([key, nested]) =>
    ["score", "quality_score", "reliability_score"].includes(key.toLocaleLowerCase()) ||
    containsForbiddenScore(nested));
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && OPAQUE_ID_RE.test(value);
}

function isStatus(value: unknown, allowed: readonly string[]): value is JsonRecord {
  return isRecord(value) && hasExactKeys(value, STATUS_KEYS) && isEnum(value.code, allowed) &&
    isSafePresentationText(value.display_text);
}

function isCurrentStage(value: unknown): boolean {
  return isRecord(value) && hasExactKeys(value, CURRENT_STAGE_KEYS) &&
    isRequiredText(value.stage_id) && isSafePresentationText(value.title) &&
    isEnum(value.status, STAGE_STATUSES) && isSafePresentationText(value.display_text);
}

function isHomeModel(value: unknown): boolean {
  if (!isRecord(value) || !hasExactKeys(value, HOME_MODEL_KEYS) ||
    !isStatus(value.status, ["available", "unavailable"]) ||
    !isNullableText(value.model_id) || !isNullableText(value.display_name) ||
    !isNullableText(value.version) || !isNullableIsoDateTime(value.published_at_utc) ||
    (value.training_period !== null && !isOrderedPeriod(value.training_period)) ||
    !isSafePresentationText(value.description) || !isSafeInternalPath(value.details_path)) return false;

  let validScope = value.supported_scope === null;
  if (isRecord(value.supported_scope) && hasExactKeys(value.supported_scope, HOME_SCOPE_KEYS)) {
    validScope = hasUniqueStrings(value.supported_scope.segments) &&
      hasUniqueStrings(value.supported_scope.channels) && hasUniqueStrings(value.supported_scope.targets) &&
      isNonNegativeInteger(value.supported_scope.geographies_n);
  }
  if (!validScope) return false;

  const available = value.status.code === "available";
  const facts = [value.model_id, value.display_name, value.version, value.training_period, value.supported_scope];
  if (available && facts.some((fact) => fact === null)) return false;
  if (!available && facts.some((fact) => fact !== null)) return false;
  return true;
}

export function parseWorkspaceHome(value: unknown): WorkspaceHomeV1 {
  const fail = (): never => { throw new UnsupportedProductNavigationContractError("workspace_home_v1"); };
  assertRecord(value, fail);
  if (!isRecord(value) || !hasExactKeys(value, HOME_KEYS) ||
    value.contract_name !== "workspace_home_v1" || value.schema_version !== "1.0.0" ||
    !isEnum(value.record_origin, ["application_runtime", "synthetic_fixture"]) ||
    !hasNonNegativeIntegerFields(value.summary, HOME_SUMMARY_KEYS) ||
    !Array.isArray(value.active_calculations) || !Array.isArray(value.recent_calculations) ||
    !isHomeModel(value.model) || !Array.isArray(value.quick_actions) || value.quick_actions.length !== 4 ||
    !Array.isArray(value.warnings) || !isIsoDateTime(value.updated_at_utc)) fail();

  const summary = value.summary as JsonRecord;
  const activeCalculations = value.active_calculations as unknown[];
  const recentCalculations = value.recent_calculations as unknown[];
  const quickActions = value.quick_actions as unknown[];
  const warnings = value.warnings as unknown[];
  const activeIds = new Set<string>();
  let queued = 0;
  let running = 0;
  for (const item of activeCalculations) {
    assertRecord(item, fail);
    if (!hasExactKeys(item, ACTIVE_CALCULATION_KEYS) || !isOpaqueId(item.job_id) ||
      activeIds.has(item.job_id) || !isRequiredText(item.campaign_name) ||
      !isStatus(item.status, ACTIVE_STATUSES) ||
      (item.current_stage !== null && !isCurrentStage(item.current_stage)) ||
      !isIsoDateTime(item.created_at_utc) || !isSafeInternalPath(item.progress_path) ||
      typeof item.can_cancel !== "boolean" || !isSafePresentationText(item.display_text)) fail();
    const itemStatus = item.status as JsonRecord;
    activeIds.add(String(item.job_id));
    if (item.can_cancel !== ["queued", "running"].includes(String(itemStatus.code))) fail();
    if (itemStatus.code === "queued") queued += 1;
    else running += 1;
  }
  if (summary.queued !== queued || summary.running !== running) fail();

  const recentIds = new Set<string>();
  for (const item of recentCalculations) {
    assertRecord(item, fail);
    if (!hasExactKeys(item, RECENT_CALCULATION_KEYS) || !isOpaqueId(item.job_id) ||
      activeIds.has(item.job_id) || recentIds.has(item.job_id) || !isRequiredText(item.campaign_name) ||
      (item.campaign_period !== null && !isOrderedPeriod(item.campaign_period)) ||
      !isNullableNonNegativeNumber(item.total_budget_rub) || !isIsoDateTime(item.created_at_utc) ||
      !isNullableIsoDateTime(item.completed_at_utc) || !isStatus(item.status, JOB_STATUSES) ||
      typeof item.result_available !== "boolean" || typeof item.report_available !== "boolean" ||
      (item.result_path !== null && !isSafeInternalPath(item.result_path)) ||
      !isSafeInternalPath(item.progress_path) || !isNullableNonNegativeInteger(item.warnings_count)) fail();
    if ((item.completed_at_utc !== null &&
      Date.parse(String(item.completed_at_utc)) < Date.parse(String(item.created_at_utc))) ||
      (item.report_available && !item.result_available) ||
      item.result_available !== (item.result_path !== null)) fail();
    recentIds.add(String(item.job_id));
  }

  const actionIds = new Set<string>();
  for (const action of quickActions) {
    assertRecord(action, fail);
    if (!hasExactKeys(action, QUICK_ACTION_KEYS) ||
      !isEnum(action.action_id, QUICK_ACTION_IDS) || actionIds.has(action.action_id) ||
      !isSafePresentationText(action.title) || !isSafePresentationText(action.description) ||
      !isSafeInternalPath(action.path)) fail();
    actionIds.add(String(action.action_id));
  }
  if (actionIds.size !== QUICK_ACTION_IDS.length) fail();

  const warningCodes = new Set<string>();
  for (const warning of warnings) {
    assertRecord(warning, fail);
    if (!hasExactKeys(warning, WARNING_KEYS) ||
      !isRequiredText(warning.code) || warningCodes.has(warning.code) ||
      !isEnum(warning.severity, ["info", "warning", "error"]) ||
      !isSafePresentationText(warning.title) || !isSafePresentationText(warning.display_text) ||
      !isSafePresentationText(warning.recommended_action) ||
      (warning.path !== null && !isSafeInternalPath(warning.path))) fail();
    warningCodes.add(String(warning.code));
  }
  if (containsAbsolutePathLeak(value)) fail();
  return value as unknown as WorkspaceHomeV1;
}

function isHistoryFilters(value: unknown): boolean {
  return isRecord(value) && hasExactKeys(value, HISTORY_FILTER_KEYS) &&
    (value.status === null || isEnum(value.status, HISTORY_STATUSES)) &&
    (value.search === null || (isRequiredText(value.search) && value.search.length <= 120)) &&
    (value.created_from === null || isIsoDate(value.created_from)) &&
    (value.created_to === null || isIsoDate(value.created_to)) &&
    (value.created_from === null || value.created_to === null || value.created_from <= value.created_to) &&
    isEnum(value.sort, HISTORY_SORTS);
}

function historyFiltersMatch(value: JsonRecord, expected: NormalizedCalculationHistoryQuery): boolean {
  return value.status === expected.status && value.search === expected.search &&
    value.created_from === expected.createdFrom && value.created_to === expected.createdTo &&
    value.sort === expected.sort;
}

export function parseCalculationHistory(
  value: unknown,
  expectedQuery?: NormalizedCalculationHistoryQuery,
): CalculationHistoryV1 {
  const fail = (): never => { throw new UnsupportedProductNavigationContractError("calculation_history_v1"); };
  assertRecord(value, fail);
  if (!isRecord(value) || !hasExactKeys(value, HISTORY_KEYS) ||
    value.contract_name !== "calculation_history_v1" || value.schema_version !== "1.0.0" ||
    !isEnum(value.record_origin, ["application_runtime", "synthetic_fixture"]) ||
    !hasNonNegativeIntegerFields(value.summary, HISTORY_SUMMARY_KEYS) ||
    !isHistoryFilters(value.filters) || !isRecord(value.pagination) ||
    !hasExactKeys(value.pagination, PAGINATION_KEYS) ||
    !isPositiveInteger(value.pagination.page) || !isPositiveInteger(value.pagination.page_size) ||
    value.pagination.page_size > 100 || !isNonNegativeInteger(value.pagination.total_items) ||
    !isNonNegativeInteger(value.pagination.total_pages) || !Array.isArray(value.items) ||
    value.items.length > value.pagination.page_size || !isIsoDateTime(value.updated_at_utc)) fail();

  const summary = value.summary as JsonRecord;
  const filters = value.filters as JsonRecord;
  const pagination = value.pagination as JsonRecord;
  const items = value.items as unknown[];
  if (summary.all !== Number(summary.active) + Number(summary.succeeded) + Number(summary.failed) +
    Number(summary.cancelled) + Number(summary.timed_out)) fail();
  const expectedPages = pagination.total_items === 0 ? 0 :
    Math.ceil(Number(pagination.total_items) / Number(pagination.page_size));
  if (pagination.total_pages !== expectedPages) fail();
  if (expectedQuery && (
    pagination.page !== expectedQuery.page || pagination.page_size !== expectedQuery.pageSize ||
    !historyFiltersMatch(filters, expectedQuery)
  )) fail();

  const ids = new Set<string>();
  for (const item of items) {
    assertRecord(item, fail);
    if (!hasExactKeys(item, HISTORY_ITEM_KEYS) || !isOpaqueId(item.job_id) ||
      ids.has(item.job_id) || !isRequiredText(item.campaign_name) || !isIsoDateTime(item.created_at_utc) ||
      !isNullableIsoDateTime(item.completed_at_utc) || !isEnum(item.status, JOB_STATUSES) ||
      !isSafePresentationText(item.status_display_text) ||
      (item.campaign_period !== null && !isOrderedPeriod(item.campaign_period)) ||
      !isNullableNonNegativeNumber(item.total_budget_rub) ||
      (item.segments !== null && !hasUniqueStrings(item.segments)) ||
      !isNullableNonNegativeInteger(item.channels_n) || !isNullableNonNegativeInteger(item.geographies_n) ||
      typeof item.result_available !== "boolean" || typeof item.report_available !== "boolean" ||
      !isSafeInternalPath(item.progress_path) ||
      (item.result_path !== null && !isSafeInternalPath(item.result_path)) ||
      !isNullableNonNegativeInteger(item.warnings_count)) fail();
    if (isEnum(item.status, TERMINAL_STATUSES) && item.completed_at_utc === null) fail();
    if (isEnum(item.status, ACTIVE_STATUSES) && item.completed_at_utc !== null) fail();
    if (item.completed_at_utc !== null && Date.parse(String(item.completed_at_utc)) < Date.parse(String(item.created_at_utc))) fail();
    if (item.report_available && !item.result_available) fail();
    if (item.status !== "succeeded" && (item.result_available || item.report_available)) fail();
    if (item.result_available !== (item.result_path !== null)) fail();
    ids.add(String(item.job_id));
  }
  if (containsAbsolutePathLeak(value)) fail();
  return value as unknown as CalculationHistoryV1;
}

function isModelScope(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const counts = value.allowed_use_counts;
  if (!hasExactKeys(value, MODEL_SCOPE_KEYS) ||
    !hasUniqueStrings(value.segments) || !hasUniqueStrings(value.channels) || !hasUniqueStrings(value.targets) ||
    !isNonNegativeInteger(value.geographies_n) || !isNonNegativeInteger(value.capability_cells_n) ||
    !isRecord(counts) || !hasExactKeys(counts, ALLOWED_USE_KEYS) ||
    !ALLOWED_USE_KEYS.every((key) => isNonNegativeInteger(counts[key]))) return false;
  return ALLOWED_USE_KEYS.reduce((sum, key) => sum + Number(counts[key]), 0) ===
    value.capability_cells_n;
}

export function parseModelOverview(value: unknown): ModelOverviewV1 {
  const fail = (): never => { throw new UnsupportedProductNavigationContractError("model_overview_v1"); };
  assertRecord(value, fail);
  if (!isRecord(value) || !hasExactKeys(value, MODEL_KEYS) || value.contract_name !== "model_overview_v1" ||
    value.schema_version !== "1.0.0" || !isEnum(value.record_origin, ["application_runtime", "synthetic_fixture"]) ||
    !isRecord(value.active_model) || !hasExactKeys(value.active_model, ACTIVE_MODEL_KEYS) ||
    !isStatus(value.active_model.status, ["available", "unavailable"]) ||
    (value.active_model.model_id !== null &&
      (typeof value.active_model.model_id !== "string" || !MODEL_ID_RE.test(value.active_model.model_id))) ||
    !isNullableText(value.active_model.display_name) || !isNullableText(value.active_model.version) ||
    !isNullableIsoDateTime(value.active_model.published_at_utc) || !isNullableText(value.active_model.framework) ||
    !isSafePresentationText(value.active_model.purpose) ||
    (value.active_model.training_period !== null && !isOrderedPeriod(value.active_model.training_period)) ||
    (value.active_model.supported_scope !== null && !isModelScope(value.active_model.supported_scope)) ||
    !isSafePresentationText(value.active_model.description) || !Array.isArray(value.capabilities) ||
    value.capabilities.length !== 5 || !Array.isArray(value.data_requirements) || value.data_requirements.length < 1 ||
    !Array.isArray(value.methodology) || value.methodology.length !== 6 || !Array.isArray(value.limitations) ||
    value.limitations.length < 4 || !Array.isArray(value.versions) || !Array.isArray(value.artifacts) ||
    !isIsoDateTime(value.updated_at_utc) || containsForbiddenScore(value)) fail();

  const activeModel = value.active_model as JsonRecord;
  const capabilities = value.capabilities as unknown[];
  const requirements = value.data_requirements as unknown[];
  const methodology = value.methodology as unknown[];
  const limitations = value.limitations as unknown[];
  const versions = value.versions as unknown[];
  const artifacts = value.artifacts as unknown[];
  const status = activeModel.status as JsonRecord;
  const active = status.code === "available";
  const activeFacts = [
    activeModel.model_id,
    activeModel.display_name,
    activeModel.version,
    activeModel.framework,
    activeModel.training_period,
    activeModel.supported_scope,
  ];
  if (active && activeFacts.some((fact) => fact === null)) fail();
  if (!active && activeFacts.some((fact) => fact !== null)) fail();

  const capabilityIds = new Set<string>();
  for (const capability of capabilities) {
    assertRecord(capability, fail);
    if (!hasExactKeys(capability, CAPABILITY_KEYS) ||
      !isEnum(capability.capability_id, CAPABILITY_IDS) || capabilityIds.has(capability.capability_id) ||
      !isSafePresentationText(capability.title) || !isEnum(capability.status, CAPABILITY_STATUSES) ||
      !isSafePresentationText(capability.description)) fail();
    capabilityIds.add(String(capability.capability_id));
  }

  const requirementIds = new Set<string>();
  for (const requirement of requirements) {
    assertRecord(requirement, fail);
    if (!hasExactKeys(requirement, REQUIREMENT_KEYS) ||
      !isRequiredText(requirement.requirement_id) || requirementIds.has(requirement.requirement_id) ||
      !isSafePresentationText(requirement.title) || typeof requirement.required !== "boolean" ||
      !isSafePresentationText(requirement.description) || !hasUniqueStrings(requirement.accepted_values)) fail();
    requirementIds.add(String(requirement.requirement_id));
  }

  const methodologyIds = new Set<string>();
  for (const method of methodology) {
    assertRecord(method, fail);
    if (!hasExactKeys(method, METHODOLOGY_KEYS) ||
      !isEnum(method.method_id, METHODOLOGY_IDS) || methodologyIds.has(method.method_id) ||
      !isSafePresentationText(method.title) || !isSafePresentationText(method.summary)) fail();
    methodologyIds.add(String(method.method_id));
  }

  const limitationCodes = new Set<string>();
  for (const limitation of limitations) {
    assertRecord(limitation, fail);
    if (!hasExactKeys(limitation, LIMITATION_KEYS) ||
      !isRequiredText(limitation.code) || limitationCodes.has(limitation.code) ||
      !isEnum(limitation.status, ["active", "unavailable"]) ||
      !isSafePresentationText(limitation.title) || !isSafePresentationText(limitation.display_text) ||
      !isSafePresentationText(limitation.recommended_action)) fail();
    limitationCodes.add(String(limitation.code));
  }

  const versionIds = new Set<string>();
  const activeVersionIds = new Set<string>();
  for (const version of versions) {
    assertRecord(version, fail);
    if (!hasExactKeys(version, VERSION_KEYS) ||
      typeof version.model_id !== "string" || !MODEL_ID_RE.test(version.model_id) || versionIds.has(version.model_id) ||
      !isRequiredText(version.model_run_id) || !isNullableIsoDateTime(version.registered_at_utc) ||
      !isRequiredText(version.package_stage) || !isRequiredText(version.activation_status) ||
      !isEnum(version.status, ["active", "registered"]) ||
      !isEnum(version.source, ["registry_registration", "active_model_passport"])) fail();
    versionIds.add(String(version.model_id));
    if (version.status === "active") activeVersionIds.add(String(version.model_id));
  }
  if (active) {
    if (activeVersionIds.size !== 1 || !activeVersionIds.has(String(activeModel.model_id))) fail();
  } else if (activeVersionIds.size !== 0) fail();

  const artifactIds = new Set<string>();
  for (const artifact of artifacts) {
    assertRecord(artifact, fail);
    if (!hasExactKeys(artifact, ARTIFACT_KEYS) ||
      !isRequiredText(artifact.artifact_id) || artifactIds.has(artifact.artifact_id) ||
      !isSafePresentationText(artifact.title) || !isEnum(artifact.status, ["available", "unavailable"]) ||
      (artifact.path !== null && !isSafeInternalPath(artifact.path)) ||
      !isSafePresentationText(artifact.display_text) ||
      (artifact.status === "available") !== (artifact.path !== null)) fail();
    artifactIds.add(String(artifact.artifact_id));
  }
  if (containsAbsolutePathLeak(value)) fail();
  return value as unknown as ModelOverviewV1;
}

function isHelpText(value: unknown, maximum: number): value is string {
  if (!isRequiredText(value) || value.length > maximum || UNSAFE_HELP_CONTENT_RE.test(value) ||
    ABSOLUTE_PATH_RE.test(value)) return false;
  const normalized = value.toLocaleLowerCase();
  return !HELP_FORBIDDEN_TERMS.some((term) => normalized.includes(term));
}

function isHelpBodyBlock(value: unknown): boolean {
  if (!isRecord(value) || !isRequiredText(value.block_type)) return false;
  if (value.block_type === "paragraph") {
    return hasExactKeys(value, PARAGRAPH_KEYS) && isHelpText(value.text, 2000);
  }
  if (value.block_type === "steps") {
    return hasExactKeys(value, STEPS_KEYS) && Array.isArray(value.items) && value.items.length > 0 &&
      value.items.every((item) => isHelpText(item, 500));
  }
  if (value.block_type === "note") {
    return hasExactKeys(value, NOTE_KEYS) && isEnum(value.tone, ["info", "warning"]) &&
      isHelpText(value.title, 160) && isHelpText(value.text, 2000);
  }
  return false;
}

export function parseHelpCatalog(value: unknown): HelpCatalogV1 {
  const fail = (): never => { throw new UnsupportedProductNavigationContractError("help_catalog_v1"); };
  assertRecord(value, fail);
  if (!isRecord(value) || !hasExactKeys(value, HELP_KEYS) || value.contract_name !== "help_catalog_v1" ||
    value.schema_version !== "1.0.0" ||
    !isEnum(value.record_origin, ["versioned_help_catalog", "synthetic_fixture"]) ||
    !Array.isArray(value.sections) || value.sections.length !== 9 || !isIsoDateTime(value.updated_at_utc)) fail();

  const sections = value.sections as unknown[];
  const articleIds = new Set<string>();
  const relatedByArticle = new Map<string, string[]>();
  for (const [sectionIndex, section] of sections.entries()) {
    assertRecord(section, fail);
    if (!hasExactKeys(section, SECTION_KEYS) ||
      section.section_id !== HELP_SECTION_IDS[sectionIndex] || section.order !== sectionIndex + 1 ||
      !isHelpText(section.title, 120) || !Array.isArray(section.articles) || section.articles.length === 0) fail();
    const articles = section.articles as unknown[];
    for (const article of articles) {
      assertRecord(article, fail);
      if (!hasExactKeys(article, ARTICLE_KEYS) ||
        typeof article.article_id !== "string" || !ARTICLE_ID_RE.test(article.article_id) ||
        articleIds.has(article.article_id) || !isHelpText(article.title, 160) ||
        !isHelpText(article.summary, 500) || !Array.isArray(article.body) || article.body.length === 0 ||
        !article.body.every(isHelpBodyBlock) || !Array.isArray(article.related_routes) ||
        new Set(article.related_routes).size !== article.related_routes.length ||
        !article.related_routes.every((route) => isEnum(route, SAFE_HELP_ROUTES)) ||
        !Array.isArray(article.related_article_ids) ||
        new Set(article.related_article_ids).size !== article.related_article_ids.length ||
        article.related_article_ids.includes(article.article_id) ||
        !article.related_article_ids.every((id) => typeof id === "string" && ARTICLE_ID_RE.test(id)) ||
        !Array.isArray(article.keywords) || article.keywords.length < 2 ||
        !article.keywords.every((keyword) => isHelpText(keyword, 80)) ||
        new Set(article.keywords.map((keyword) => String(keyword).toLocaleLowerCase())).size !== article.keywords.length) fail();
      articleIds.add(String(article.article_id));
      relatedByArticle.set(String(article.article_id), article.related_article_ids as string[]);
    }
  }
  for (const related of relatedByArticle.values()) {
    if (related.some((id) => !articleIds.has(id))) fail();
  }
  if (containsAbsolutePathLeak(value)) fail();
  return value as unknown as HelpCatalogV1;
}

export function normalizeCalculationHistoryQuery(
  query: CalculationHistoryQuery = {},
): NormalizedCalculationHistoryQuery {
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 25;
  const status = query.status ?? null;
  const search = query.search === undefined || query.search === null ? null : query.search.trim();
  const createdFrom = query.createdFrom ?? null;
  const createdTo = query.createdTo ?? null;
  const sort = query.sort ?? "created_desc";
  if (!isPositiveInteger(page) || !isPositiveInteger(pageSize) || pageSize > 100 ||
    (status !== null && !isEnum(status, HISTORY_STATUSES)) ||
    (search !== null && (!search || search.length > 120)) ||
    (createdFrom !== null && !isIsoDate(createdFrom)) || (createdTo !== null && !isIsoDate(createdTo)) ||
    !isEnum(sort, HISTORY_SORTS)) {
    throw new ProductNavigationQueryInvalidError();
  }
  return { page, pageSize, status, search, createdFrom, createdTo, sort };
}

export function serializeCalculationHistoryQuery(
  query: CalculationHistoryQuery | NormalizedCalculationHistoryQuery = {},
): string {
  const normalized = normalizeCalculationHistoryQuery(query);
  const parameters = new URLSearchParams({
    page: String(normalized.page),
    page_size: String(normalized.pageSize),
    sort: normalized.sort,
  });
  if (normalized.status !== null) parameters.set("status", normalized.status);
  if (normalized.search !== null) parameters.set("search", normalized.search);
  if (normalized.createdFrom !== null) parameters.set("created_from", normalized.createdFrom);
  if (normalized.createdTo !== null) parameters.set("created_to", normalized.createdTo);
  return parameters.toString();
}

function apiEndpoint(path: string, baseUrl: string): string {
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

async function responseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function parseApiError(value: unknown): ApiErrorPayload | null {
  if (!isRecord(value) || !hasExactKeys(value, API_ERROR_ROOT_KEYS) || !isRecord(value.error) ||
    !hasExactKeys(value.error, API_ERROR_KEYS) || !isRequiredText(value.error.code) ||
    !isRequiredText(value.error.display_text) || typeof value.error.retryable !== "boolean" ||
    !isRequiredText(value.error.user_action) || containsAbsolutePathLeak(value)) return null;
  return {
    code: value.error.code,
    displayText: value.error.display_text,
    retryable: value.error.retryable,
    userAction: value.error.user_action,
  };
}

async function getProductNavigationContract<T>(
  path: string,
  contract: ProductNavigationContract,
  parser: (value: unknown) => T,
  signal: AbortSignal | undefined,
  baseUrl: string,
): Promise<T> {
  let response: Response;
  try {
    response = await credentialedFetch(apiEndpoint(path, baseUrl), {
      method: "GET",
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ProductNavigationRequestError();
  }
  const payload = await responseJson(response);
  const apiError = parseApiError(payload);
  if (response.status === 422) {
    throw new ProductNavigationQueryInvalidError(
      apiError?.code === "PRODUCT_NAVIGATION_QUERY_INVALID" ? apiError.displayText : undefined,
      apiError?.code === "PRODUCT_NAVIGATION_QUERY_INVALID" ? apiError.userAction : undefined,
      apiError?.code === "PRODUCT_NAVIGATION_QUERY_INVALID" ? apiError.retryable : undefined,
    );
  }
  if (response.status === 409) {
    throw new ProductNavigationInconsistentError(
      apiError?.code === "PRODUCT_NAVIGATION_INCONSISTENT" ? apiError.displayText : undefined,
      apiError?.code === "PRODUCT_NAVIGATION_INCONSISTENT" ? apiError.userAction : undefined,
      apiError?.code === "PRODUCT_NAVIGATION_INCONSISTENT" ? apiError.retryable : undefined,
    );
  }
  if (response.status === 503) {
    throw new ProductNavigationUnavailableError(
      apiError?.code === "PRODUCT_NAVIGATION_UNAVAILABLE" ? apiError.displayText : undefined,
      apiError?.code === "PRODUCT_NAVIGATION_UNAVAILABLE" ? apiError.userAction : undefined,
      apiError?.code === "PRODUCT_NAVIGATION_UNAVAILABLE" ? apiError.retryable : undefined,
    );
  }
  if (!response.ok) throw new ProductNavigationRequestError(response.status);
  if (payload === undefined) throw new UnsupportedProductNavigationContractError(contract, response.status);
  try {
    return parser(payload);
  } catch (error) {
    if (error instanceof UnsupportedProductNavigationContractError) {
      throw new UnsupportedProductNavigationContractError(contract, response.status);
    }
    throw error;
  }
}

export function getWorkspaceHome(
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<WorkspaceHomeV1> {
  return getProductNavigationContract(
    WORKSPACE_HOME_PATH,
    "workspace_home_v1",
    parseWorkspaceHome,
    signal,
    baseUrl,
  );
}

export function getCalculationHistory(
  query: CalculationHistoryQuery = {},
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<CalculationHistoryV1> {
  const normalized = normalizeCalculationHistoryQuery(query);
  const path = `${CALCULATION_HISTORY_PATH}?${serializeCalculationHistoryQuery(normalized)}`;
  return getProductNavigationContract(
    path,
    "calculation_history_v1",
    (value) => parseCalculationHistory(value, normalized),
    signal,
    baseUrl,
  );
}

export function getModelOverview(
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<ModelOverviewV1> {
  return getProductNavigationContract(
    MODEL_OVERVIEW_PATH,
    "model_overview_v1",
    parseModelOverview,
    signal,
    baseUrl,
  );
}

export function getHelpCatalog(
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<HelpCatalogV1> {
  return getProductNavigationContract(
    HELP_CATALOG_PATH,
    "help_catalog_v1",
    parseHelpCatalog,
    signal,
    baseUrl,
  );
}
