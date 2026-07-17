import type { AdminAuditLogV1 } from "./generated/admin-audit-log-v1";
import type { AdminRoleCatalogV1 } from "./generated/admin-role-catalog-v1";
import type { AdminSystemStatusV1 } from "./generated/admin-system-status-v1";
import type { AdminUserDetailV1 } from "./generated/admin-user-detail-v1";
import type { AdminUserListV1 } from "./generated/admin-user-list-v1";
import type {
  CreateLocalPilotUser,
  UpdateLocalPilotUser,
} from "./generated/admin-user-mutation-v1";
import type { AuthSessionV1 } from "./generated/auth-session-v1";
import { appEnv } from "../config/env";
import { credentialedFetch } from "./credentialed-fetch";

const AUTH_LOGIN_PATH = "/api/v1/auth/login";
const AUTH_LOGOUT_PATH = "/api/v1/auth/logout";
const AUTH_SESSION_PATH = "/api/v1/auth/session";
const ADMIN_USERS_PATH = "/api/v1/admin/users";
const ADMIN_ROLES_PATH = "/api/v1/admin/roles";
const ADMIN_SYSTEM_PATH = "/api/v1/admin/system/status";
const ADMIN_AUDIT_PATH = "/api/v1/admin/audit";

const ROLE_IDS = ["viewer", "analyst", "admin"] as const;
const USER_STATUSES = ["active", "disabled"] as const;
const USER_SORTS = [
  "created_desc",
  "created_asc",
  "name_asc",
  "email_asc",
  "last_login_desc",
] as const;
const PERMISSION_IDS = [
  "workspace.read",
  "calculation.read",
  "calculation.create",
  "calculation.cancel",
  "result.read",
  "report.download",
  "model.read",
  "help.read",
  "admin.users.read",
  "admin.users.write",
  "admin.roles.write",
  "admin.sessions.write",
  "admin.system.read",
  "admin.audit.read",
] as const;
const SYSTEM_STATUSES = ["healthy", "degraded", "unavailable"] as const;
const SYSTEM_IDS = [
  "application",
  "storage",
  "queue",
  "model",
  "reports",
  "auth_storage",
] as const;
const AUDIT_EVENT_TYPES = [
  "login_succeeded",
  "login_failed",
  "logout",
  "session_revoked",
  "user_created",
  "user_updated",
  "user_enabled",
  "user_disabled",
  "role_changed",
  "admin_viewed_system_status",
  "admin_viewed_audit_log",
] as const;
const AUDIT_RESULTS = ["succeeded", "denied", "rate_limited", "account_disabled"] as const;
const AUDIT_SORTS = ["occurred_desc", "occurred_asc"] as const;

const AUTH_SESSION_KEYS = [
  "contract_name",
  "schema_version",
  "authenticated",
  "user",
  "session",
] as const;
const SESSION_USER_KEYS = [
  "user_id",
  "display_name",
  "email",
  "role",
  "permissions",
  "status",
] as const;
const SESSION_KEYS = [
  "session_id",
  "created_at_utc",
  "expires_at_utc",
  "last_seen_at_utc",
  "idle_timeout_seconds",
] as const;
const ROLE_KEYS = ["role_id", "title"] as const;
const ADMIN_USER_LIST_KEYS = [
  "contract_name",
  "schema_version",
  "items",
  "pagination",
  "applied_filters",
] as const;
const ADMIN_USER_DETAIL_KEYS = ["contract_name", "schema_version", "user"] as const;
const ADMIN_USER_KEYS = [
  "user_id",
  "display_name",
  "email",
  "role",
  "status",
  "created_at_utc",
  "updated_at_utc",
  "last_login_at_utc",
  "created_by_user_id",
  "active_sessions_n",
] as const;
const PAGINATION_KEYS = ["page", "page_size", "total_items", "total_pages"] as const;
const USER_FILTER_KEYS = ["search", "role", "status", "sort"] as const;
const ROLE_CATALOG_KEYS = [
  "contract_name",
  "schema_version",
  "catalog_version",
  "permissions",
  "roles",
] as const;
const PERMISSION_KEYS = ["permission_id", "title", "description"] as const;
const CATALOG_ROLE_KEYS = ["role_id", "title", "description", "permissions"] as const;
const SYSTEM_KEYS = [
  "contract_name",
  "schema_version",
  "overall_status",
  "checked_at_utc",
  "subsystems",
  "build",
] as const;
const SUBSYSTEM_KEYS = ["status", "display_text", "facts"] as const;
const BUILD_KEYS = [
  "application_version",
  "api_version",
  "config_schema_version",
  "source_revision",
] as const;
const AUDIT_KEYS = [
  "contract_name",
  "schema_version",
  "items",
  "pagination",
  "applied_filters",
] as const;
const AUDIT_EVENT_KEYS = [
  "event_id",
  "event_type",
  "occurred_at_utc",
  "actor_user_id",
  "actor_display_name",
  "target_type",
  "target_id",
  "result",
  "browser_safe_summary",
  "request_id",
] as const;
const AUDIT_FILTER_KEYS = [
  "actor_user_id",
  "event_type",
  "occurred_from_utc",
  "occurred_to_utc",
  "sort",
] as const;
const API_ERROR_ROOT_KEYS = ["error"] as const;
const API_ERROR_KEYS = ["code", "display_text", "retryable", "user_action"] as const;
const REVOKE_KEYS = ["user_id", "revoked_sessions_n"] as const;

const USER_ID_RE = /^usr_[0-9a-f]{24}$/;
const SESSION_ID_RE = /^ses_[0-9a-f]{24}$/;
const EVENT_ID_RE = /^evt_[0-9a-f]{24}$/;
const REQUEST_ID_RE = /^req_[0-9a-f]{24}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PERMISSION_ID_RE = /^[a-z]+(?:\.[a-z]+)+$/;
const FACT_ID_RE = /^[a-z][a-z0-9_]*$/;
const ERROR_CODE_RE = /^[A-Z][A-Z0-9_]+$/;
const SHA_RE = /^[0-9a-f]{40}$/;
const ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const ABSOLUTE_PATH_RE = /^(?:\/|[A-Za-z]:[\\/]|file:\/\/)/i;
const SENSITIVE_TEXT_RE = /password_hash|session_secret|session_id|user_id|request_id|set-cookie|traceback|stack\s*trace|session token|\bcookie\b|\bsqlite\b|\bfilesystem\b|\borigin\b|\bhost\b|argon2id|req_[0-9a-f]{24}/i;
const EMAIL_IN_TEXT_RE = /[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/i;

type JsonRecord = Record<string, unknown>;
export type AdminRoleId = (typeof ROLE_IDS)[number];
export type AdminUserStatus = (typeof USER_STATUSES)[number];
export type AdminUsersSort = (typeof USER_SORTS)[number];
export type AdminAuditEventType = (typeof AUDIT_EVENT_TYPES)[number];
export type AdminAuditSort = (typeof AUDIT_SORTS)[number];

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface AdminUsersQuery {
  page?: number;
  pageSize?: number;
  search?: string | null;
  role?: AdminRoleId | null;
  status?: AdminUserStatus | null;
  sort?: AdminUsersSort;
}

export interface NormalizedAdminUsersQuery {
  page: number;
  pageSize: number;
  search: string | null;
  role: AdminRoleId | null;
  status: AdminUserStatus | null;
  sort: AdminUsersSort;
}

export interface AdminAuditQuery {
  page?: number;
  pageSize?: number;
  actorUserId?: string | null;
  eventType?: AdminAuditEventType | null;
  occurredFromUtc?: string | null;
  occurredToUtc?: string | null;
  sort?: AdminAuditSort;
}

export interface NormalizedAdminAuditQuery {
  page: number;
  pageSize: number;
  actorUserId: string | null;
  eventType: AdminAuditEventType | null;
  occurredFromUtc: string | null;
  occurredToUtc: string | null;
  sort: AdminAuditSort;
}

export interface RevokeAdminUserSessionsResult {
  user_id: string;
  revoked_sessions_n: number;
}

interface ApiErrorPayload {
  code: string;
  displayText: string;
  retryable: boolean;
  userAction: string;
}

interface AuthAdminErrorOptions {
  status: number | null;
  code: string;
  retryable: boolean;
  userAction: string;
  contract?: string;
}

export class AuthAdminError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly retryable: boolean;
  readonly userAction: string;
  readonly contract: string | null;

  constructor(message: string, options: AuthAdminErrorOptions) {
    super(message);
    this.name = "AuthAdminError";
    this.status = options.status;
    this.code = options.code;
    this.retryable = options.retryable;
    this.userAction = options.userAction;
    this.contract = options.contract ?? null;
  }
}

function unsupportedContract(contract: string, status: number | null = null): AuthAdminError {
  return new AuthAdminError("Сервис вернул неподдерживаемый формат данных.", {
    status,
    code: "UNSUPPORTED_AUTH_ADMIN_CONTRACT",
    retryable: false,
    userAction: "Обновите страницу. Если проблема сохраняется, сообщите ответственному за сервис.",
    contract,
  });
}

function invalidQuery(message = "Параметры просмотра заполнены некорректно."): AuthAdminError {
  return new AuthAdminError(message, {
    status: 422,
    code: "ADMIN_QUERY_INVALID",
    retryable: true,
    userAction: "Исправьте фильтры или параметры страницы и повторите запрос.",
  });
}

function invalidMutation(message = "Данные пользователя заполнены некорректно."): AuthAdminError {
  return new AuthAdminError(message, {
    status: 409,
    code: "ADMIN_STATE_INCONSISTENT",
    retryable: true,
    userAction: "Проверьте данные и повторите действие.",
  });
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertRecord(value: unknown, fail: () => never): asserts value is JsonRecord {
  if (!isRecord(value)) fail();
}

function assertArray(value: unknown, fail: () => never): asserts value is unknown[] {
  if (!Array.isArray(value)) fail();
}

function hasExactKeys(value: JsonRecord, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && expected.every((key) => key in value);
}

function isEnum<T extends readonly string[]>(value: unknown, allowed: T): value is T[number] {
  return typeof value === "string" && allowed.includes(value as T[number]);
}

function isSafeText(value: unknown, minimum = 1, maximum = 500): value is string {
  return typeof value === "string" && value.trim().length >= minimum && value.length <= maximum &&
    !ABSOLUTE_PATH_RE.test(value) && !SENSITIVE_TEXT_RE.test(value);
}

function isNullableSafeText(value: unknown, maximum = 500): value is string | null {
  return value === null || isSafeText(value, 1, maximum);
}

function isEmail(value: unknown): value is string {
  return typeof value === "string" && value.length <= 254 && EMAIL_RE.test(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return isNonNegativeInteger(value) && value > 0;
}

function isIsoDateTime(value: unknown): value is string {
  return typeof value === "string" && ISO_DATETIME_RE.test(value) &&
    Number.isFinite(Date.parse(value));
}

function parseTimestamp(value: unknown): number | null {
  return isIsoDateTime(value) ? Date.parse(value) : null;
}

function hasUniqueStrings(values: unknown[]): boolean {
  return values.every((value) => typeof value === "string") &&
    new Set(values).size === values.length;
}

function parseRole(value: unknown, fail: () => never): void {
  if (!isRecord(value) || !hasExactKeys(value, ROLE_KEYS) ||
    !isEnum(value.role_id, ROLE_IDS) || !isSafeText(value.title, 1, 120)) fail();
}

export function parseAuthSession(value: unknown): AuthSessionV1 {
  const fail = (): never => { throw unsupportedContract("auth_session_v1"); };
  assertRecord(value, fail);
  if (!hasExactKeys(value, AUTH_SESSION_KEYS) ||
    value.contract_name !== "auth_session_v1" || value.schema_version !== "1.0.0" ||
    typeof value.authenticated !== "boolean") fail();
  if (!value.authenticated) {
    if (value.user !== null || value.session !== null) fail();
    return value as unknown as AuthSessionV1;
  }
  assertRecord(value.user, fail);
  const user = value.user;
  if (!hasExactKeys(user, SESSION_USER_KEYS) || !USER_ID_RE.test(String(user.user_id)) ||
    !isSafeText(user.display_name, 2, 120) || !isEmail(user.email) || user.status !== "active" ||
    !Array.isArray(user.permissions) || user.permissions.length === 0 ||
    !hasUniqueStrings(user.permissions) ||
    !user.permissions.every((permission: unknown) => isEnum(permission, PERMISSION_IDS))) fail();
  parseRole(user.role, fail);
  assertRecord(value.session, fail);
  const session = value.session;
  if (!hasExactKeys(session, SESSION_KEYS) || !SESSION_ID_RE.test(String(session.session_id)) ||
    !isIsoDateTime(session.created_at_utc) || !isIsoDateTime(session.expires_at_utc) ||
    !isIsoDateTime(session.last_seen_at_utc) || !isPositiveInteger(session.idle_timeout_seconds) ||
    session.idle_timeout_seconds < 60) fail();
  const created = Date.parse(String(session.created_at_utc));
  const expires = Date.parse(String(session.expires_at_utc));
  const lastSeen = Date.parse(String(session.last_seen_at_utc));
  if (created > lastSeen || lastSeen > expires) fail();
  return value as unknown as AuthSessionV1;
}

function parseAdminUserItem(value: unknown, fail: () => never): void {
  assertRecord(value, fail);
  if (!hasExactKeys(value, ADMIN_USER_KEYS) ||
    !USER_ID_RE.test(String(value.user_id)) || !isSafeText(value.display_name, 2, 120) ||
    !isEmail(value.email) || !isEnum(value.status, USER_STATUSES) ||
    !isIsoDateTime(value.created_at_utc) || !isIsoDateTime(value.updated_at_utc) ||
    !(value.last_login_at_utc === null || isIsoDateTime(value.last_login_at_utc)) ||
    !(value.created_by_user_id === null ||
      (typeof value.created_by_user_id === "string" && USER_ID_RE.test(value.created_by_user_id))) ||
    !isNonNegativeInteger(value.active_sessions_n)) fail();
  parseRole(value.role, fail);
  const created = Date.parse(value.created_at_utc);
  if (Date.parse(value.updated_at_utc) < created ||
    (typeof value.last_login_at_utc === "string" && Date.parse(value.last_login_at_utc) < created)) fail();
}

function parsePagination(value: unknown, itemCount: number, fail: () => never): void {
  assertRecord(value, fail);
  if (!hasExactKeys(value, PAGINATION_KEYS) ||
    !isPositiveInteger(value.page) || !isPositiveInteger(value.page_size) ||
    value.page_size > 100 || !isNonNegativeInteger(value.total_items) ||
    !isNonNegativeInteger(value.total_pages) || itemCount > value.page_size ||
    itemCount > value.total_items ||
    value.total_pages !== Math.ceil(value.total_items / value.page_size)) fail();
}

function parseUserFilters(value: unknown, fail: () => never): void {
  assertRecord(value, fail);
  if (!hasExactKeys(value, USER_FILTER_KEYS) ||
    !(value.search === null || isSafeText(value.search, 1, 120)) ||
    !(value.role === null || isEnum(value.role, ROLE_IDS)) ||
    !(value.status === null || isEnum(value.status, USER_STATUSES)) ||
    !isEnum(value.sort, USER_SORTS)) fail();
}

export function parseAdminUserList(
  value: unknown,
  expectedQuery?: NormalizedAdminUsersQuery,
): AdminUserListV1 {
  const fail = (): never => { throw unsupportedContract("admin_user_list_v1"); };
  assertRecord(value, fail);
  if (!hasExactKeys(value, ADMIN_USER_LIST_KEYS) ||
    value.contract_name !== "admin_user_list_v1" || value.schema_version !== "1.0.0") fail();
  assertArray(value.items, fail);
  const items = value.items;
  const userIds = new Set<string>();
  for (const item of items) {
    parseAdminUserItem(item, fail);
    const userId = String((item as JsonRecord).user_id);
    if (userIds.has(userId)) fail();
    userIds.add(userId);
  }
  parsePagination(value.pagination, items.length, fail);
  parseUserFilters(value.applied_filters, fail);
  if (expectedQuery) {
    const pagination = value.pagination as JsonRecord;
    const filters = value.applied_filters as JsonRecord;
    if (pagination.page !== expectedQuery.page || pagination.page_size !== expectedQuery.pageSize ||
      filters.search !== expectedQuery.search || filters.role !== expectedQuery.role ||
      filters.status !== expectedQuery.status || filters.sort !== expectedQuery.sort) fail();
  }
  return value as unknown as AdminUserListV1;
}

export function parseAdminUserDetail(value: unknown): AdminUserDetailV1 {
  const fail = (): never => { throw unsupportedContract("admin_user_detail_v1"); };
  assertRecord(value, fail);
  if (!hasExactKeys(value, ADMIN_USER_DETAIL_KEYS) ||
    value.contract_name !== "admin_user_detail_v1" || value.schema_version !== "1.0.0") fail();
  parseAdminUserItem(value.user, fail);
  return value as unknown as AdminUserDetailV1;
}

export function parseAdminRoleCatalog(value: unknown): AdminRoleCatalogV1 {
  const fail = (): never => { throw unsupportedContract("admin_role_catalog_v1"); };
  assertRecord(value, fail);
  if (!hasExactKeys(value, ROLE_CATALOG_KEYS) ||
    value.contract_name !== "admin_role_catalog_v1" || value.schema_version !== "1.0.0" ||
    value.catalog_version !== "1.0.0") fail();
  assertArray(value.permissions, fail);
  assertArray(value.roles, fail);
  const permissions = value.permissions;
  const roles = value.roles;
  if (permissions.length !== PERMISSION_IDS.length || roles.length !== ROLE_IDS.length) fail();
  const permissionIds = new Set<string>();
  for (const permission of permissions) {
    assertRecord(permission, fail);
    if (!hasExactKeys(permission, PERMISSION_KEYS) ||
      !isEnum(permission.permission_id, PERMISSION_IDS) ||
      !isSafeText(permission.title, 1, 120) ||
      !isSafeText(permission.description, 1, 500) ||
      permissionIds.has(permission.permission_id)) fail();
    permissionIds.add(String(permission.permission_id));
  }
  if (permissionIds.size !== PERMISSION_IDS.length) fail();
  const roleIds = new Set<string>();
  for (const role of roles) {
    assertRecord(role, fail);
    if (!hasExactKeys(role, CATALOG_ROLE_KEYS) ||
      !isEnum(role.role_id, ROLE_IDS) || roleIds.has(role.role_id) ||
      !isSafeText(role.title, 1, 120) || !isSafeText(role.description, 1, 500) ||
      !Array.isArray(role.permissions) || !hasUniqueStrings(role.permissions) ||
      !role.permissions.every((permission) =>
        typeof permission === "string" && permissionIds.has(permission) &&
        PERMISSION_ID_RE.test(permission))) fail();
    roleIds.add(String(role.role_id));
  }
  if (roleIds.size !== ROLE_IDS.length) fail();
  return value as unknown as AdminRoleCatalogV1;
}

function parseSubsystem(value: unknown, fail: () => never): void {
  assertRecord(value, fail);
  if (!hasExactKeys(value, SUBSYSTEM_KEYS) ||
    !isEnum(value.status, SYSTEM_STATUSES) || !isSafeText(value.display_text, 1, 500) ||
    !isRecord(value.facts)) fail();
  for (const [key, fact] of Object.entries(value.facts)) {
    if (!FACT_ID_RE.test(key) || !(fact === null || typeof fact === "boolean" ||
      (typeof fact === "number" && Number.isFinite(fact)) || isSafeText(fact, 1, 500))) fail();
  }
}

export function parseAdminSystemStatus(value: unknown): AdminSystemStatusV1 {
  const fail = (): never => { throw unsupportedContract("admin_system_status_v1"); };
  assertRecord(value, fail);
  if (!hasExactKeys(value, SYSTEM_KEYS) ||
    value.contract_name !== "admin_system_status_v1" || value.schema_version !== "1.0.0" ||
    !isEnum(value.overall_status, SYSTEM_STATUSES) || !isIsoDateTime(value.checked_at_utc)) fail();
  assertRecord(value.subsystems, fail);
  assertRecord(value.build, fail);
  const subsystems = value.subsystems;
  const build = value.build;
  if (!hasExactKeys(subsystems, SYSTEM_IDS) || !hasExactKeys(build, BUILD_KEYS)) fail();
  for (const subsystemId of SYSTEM_IDS) parseSubsystem(subsystems[subsystemId], fail);
  const application = subsystems.application as JsonRecord;
  const authStorage = subsystems.auth_storage as JsonRecord;
  const statuses = SYSTEM_IDS.map((id) => subsystems[id] as JsonRecord)
    .map((subsystem) => subsystem.status);
  const expectedOverall = application.status === "unavailable" || authStorage.status === "unavailable"
    ? "unavailable"
    : statuses.some((status) => status !== "healthy") ? "degraded" : "healthy";
  if (value.overall_status !== expectedOverall ||
    !isSafeText(build.application_version, 1, 100) ||
    !isSafeText(build.api_version, 1, 100) ||
    !isSafeText(build.config_schema_version, 1, 100) ||
    !(build.source_revision === null ||
      (typeof build.source_revision === "string" && SHA_RE.test(build.source_revision)))) fail();
  return value as unknown as AdminSystemStatusV1;
}

function parseAuditFilters(value: unknown, fail: () => never): void {
  assertRecord(value, fail);
  if (!hasExactKeys(value, AUDIT_FILTER_KEYS) ||
    !(value.actor_user_id === null ||
      (typeof value.actor_user_id === "string" && USER_ID_RE.test(value.actor_user_id))) ||
    !(value.event_type === null || isEnum(value.event_type, AUDIT_EVENT_TYPES)) ||
    !(value.occurred_from_utc === null || isIsoDateTime(value.occurred_from_utc)) ||
    !(value.occurred_to_utc === null || isIsoDateTime(value.occurred_to_utc)) ||
    !isEnum(value.sort, AUDIT_SORTS)) fail();
  const from = parseTimestamp(value.occurred_from_utc);
  const to = parseTimestamp(value.occurred_to_utc);
  if (from !== null && to !== null && to < from) fail();
}

export function parseAdminAuditLog(
  value: unknown,
  expectedQuery?: NormalizedAdminAuditQuery,
): AdminAuditLogV1 {
  const fail = (): never => { throw unsupportedContract("admin_audit_log_v1"); };
  assertRecord(value, fail);
  if (!hasExactKeys(value, AUDIT_KEYS) ||
    value.contract_name !== "admin_audit_log_v1" || value.schema_version !== "1.0.0") fail();
  assertArray(value.items, fail);
  const items = value.items;
  const eventIds = new Set<string>();
  for (const item of items) {
    assertRecord(item, fail);
    if (!hasExactKeys(item, AUDIT_EVENT_KEYS) ||
      typeof item.event_id !== "string" || !EVENT_ID_RE.test(item.event_id) ||
      eventIds.has(item.event_id) || !isEnum(item.event_type, AUDIT_EVENT_TYPES) ||
      !isIsoDateTime(item.occurred_at_utc) ||
      !(item.actor_user_id === null ||
        (typeof item.actor_user_id === "string" && USER_ID_RE.test(item.actor_user_id))) ||
      !isNullableSafeText(item.actor_display_name, 120) || !isSafeText(item.target_type, 1, 80) ||
      !isNullableSafeText(item.target_id, 120) || !isEnum(item.result, AUDIT_RESULTS) ||
      !isSafeText(item.browser_safe_summary, 1, 500) ||
      EMAIL_IN_TEXT_RE.test(String(item.browser_safe_summary)) ||
      typeof item.request_id !== "string" || !REQUEST_ID_RE.test(item.request_id)) fail();
    eventIds.add(String(item.event_id));
  }
  parsePagination(value.pagination, items.length, fail);
  parseAuditFilters(value.applied_filters, fail);
  if (expectedQuery) {
    const pagination = value.pagination as JsonRecord;
    const filters = value.applied_filters as JsonRecord;
    if (pagination.page !== expectedQuery.page || pagination.page_size !== expectedQuery.pageSize ||
      filters.actor_user_id !== expectedQuery.actorUserId ||
      filters.event_type !== expectedQuery.eventType ||
      filters.occurred_from_utc !== expectedQuery.occurredFromUtc ||
      filters.occurred_to_utc !== expectedQuery.occurredToUtc ||
      filters.sort !== expectedQuery.sort) fail();
  }
  return value as unknown as AdminAuditLogV1;
}

export function parseRevokeAdminUserSessions(value: unknown): RevokeAdminUserSessionsResult {
  const fail = (): never => { throw unsupportedContract("admin_user_sessions_revoke_response"); };
  assertRecord(value, fail);
  if (!hasExactKeys(value, REVOKE_KEYS) ||
    typeof value.user_id !== "string" || !USER_ID_RE.test(value.user_id) ||
    !isNonNegativeInteger(value.revoked_sessions_n)) {
    fail();
  }
  return value as unknown as RevokeAdminUserSessionsResult;
}

export function normalizeAdminUsersQuery(
  query: AdminUsersQuery = {},
): NormalizedAdminUsersQuery {
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 25;
  const search = query.search === undefined || query.search === null ? null : query.search.trim();
  const role = query.role ?? null;
  const status = query.status ?? null;
  const sort = query.sort ?? "created_desc";
  if (!isPositiveInteger(page) || !isPositiveInteger(pageSize) || pageSize > 100 ||
    (search !== null && (!search || search.length > 120)) ||
    (role !== null && !isEnum(role, ROLE_IDS)) ||
    (status !== null && !isEnum(status, USER_STATUSES)) || !isEnum(sort, USER_SORTS)) {
    throw invalidQuery();
  }
  return { page, pageSize, search, role, status, sort };
}

export function serializeAdminUsersQuery(
  query: AdminUsersQuery | NormalizedAdminUsersQuery = {},
): string {
  const normalized = normalizeAdminUsersQuery(query);
  const parameters = new URLSearchParams({
    page: String(normalized.page),
    page_size: String(normalized.pageSize),
    sort: normalized.sort,
  });
  if (normalized.search !== null) parameters.set("search", normalized.search);
  if (normalized.role !== null) parameters.set("role", normalized.role);
  if (normalized.status !== null) parameters.set("status", normalized.status);
  return parameters.toString();
}

export function normalizeAdminAuditQuery(
  query: AdminAuditQuery = {},
): NormalizedAdminAuditQuery {
  const page = query.page ?? 1;
  // Runtime uses 50 while the current OpenAPI shared parameter advertises 25.
  // Sending it explicitly makes browser behavior deterministic until the contract is aligned.
  const pageSize = query.pageSize ?? 50;
  const actorUserId = query.actorUserId ?? null;
  const eventType = query.eventType ?? null;
  const occurredFromUtc = query.occurredFromUtc ?? null;
  const occurredToUtc = query.occurredToUtc ?? null;
  const sort = query.sort ?? "occurred_desc";
  const from = parseTimestamp(occurredFromUtc);
  const to = parseTimestamp(occurredToUtc);
  if (!isPositiveInteger(page) || !isPositiveInteger(pageSize) || pageSize > 100 ||
    (actorUserId !== null && !USER_ID_RE.test(actorUserId)) ||
    (eventType !== null && !isEnum(eventType, AUDIT_EVENT_TYPES)) ||
    (occurredFromUtc !== null && from === null) || (occurredToUtc !== null && to === null) ||
    (from !== null && to !== null && to < from) || !isEnum(sort, AUDIT_SORTS)) {
    throw invalidQuery();
  }
  return { page, pageSize, actorUserId, eventType, occurredFromUtc, occurredToUtc, sort };
}

export function serializeAdminAuditQuery(
  query: AdminAuditQuery | NormalizedAdminAuditQuery = {},
): string {
  const normalized = normalizeAdminAuditQuery(query);
  const parameters = new URLSearchParams({
    page: String(normalized.page),
    page_size: String(normalized.pageSize),
    sort: normalized.sort,
  });
  if (normalized.actorUserId !== null) parameters.set("actor_user_id", normalized.actorUserId);
  if (normalized.eventType !== null) parameters.set("event_type", normalized.eventType);
  if (normalized.occurredFromUtc !== null) {
    parameters.set("occurred_from_utc", normalized.occurredFromUtc);
  }
  if (normalized.occurredToUtc !== null) parameters.set("occurred_to_utc", normalized.occurredToUtc);
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
  if (!isRecord(value) || !hasExactKeys(value, API_ERROR_ROOT_KEYS) ||
    !isRecord(value.error) || !hasExactKeys(value.error, API_ERROR_KEYS) ||
    typeof value.error.code !== "string" || !ERROR_CODE_RE.test(value.error.code) ||
    !isSafeText(value.error.display_text, 1, 500) || typeof value.error.retryable !== "boolean" ||
    !isSafeText(value.error.user_action, 1, 500)) return null;
  return {
    code: value.error.code,
    displayText: value.error.display_text,
    retryable: value.error.retryable,
    userAction: value.error.user_action,
  };
}

function fallbackHttpError(status: number): AuthAdminError {
  const fallback = status === 401
    ? ["Сессия завершена. Войдите повторно.", "Откройте страницу входа."]
    : status === 403
      ? ["Недостаточно прав для выполнения этого действия.", "Обратитесь к администратору."]
      : status === 404
        ? ["Пользователь не найден.", "Обновите список пользователей."]
        : status === 409
          ? ["Не удалось применить изменение.", "Обновите страницу и повторите действие."]
          : status === 422
            ? ["Параметры просмотра заполнены некорректно.", "Исправьте параметры и повторите запрос."]
            : status === 429
              ? ["Слишком много попыток входа.", "Повторите попытку немного позже."]
              : status >= 500
                ? ["Сервис временно недоступен.", "Повторите действие позже."]
                : ["Не удалось выполнить запрос.", "Повторите действие."];
  return new AuthAdminError(fallback[0], {
    status,
    code: `HTTP_${status}`,
    retryable: status === 401 || status === 409 || status === 422 || status === 429 || status >= 500,
    userAction: fallback[1],
  });
}

async function requestContract<T>(
  path: string,
  parser: (value: unknown) => T,
  init: RequestInit,
  baseUrl: string,
  signalUnauthorized = true,
  signalForbidden = true,
): Promise<T> {
  let response: Response;
  try {
    response = await credentialedFetch(
      apiEndpoint(path, baseUrl),
      { ...init, credentials: "include" },
      { signalUnauthorized, signalForbidden },
    );
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new AuthAdminError("Сервис временно недоступен.", {
      status: null,
      code: "AUTH_ADMIN_REQUEST_FAILED",
      retryable: true,
      userAction: "Проверьте соединение и повторите действие.",
    });
  }
  const payload = await responseJson(response);
  if (!response.ok) {
    const apiError = parseApiError(payload);
    if (apiError) {
      throw new AuthAdminError(apiError.displayText, {
        status: response.status,
        code: apiError.code,
        retryable: apiError.retryable,
        userAction: apiError.userAction,
      });
    }
    throw fallbackHttpError(response.status);
  }
  if (payload === undefined) throw unsupportedContract("phase_e_response", response.status);
  try {
    return parser(payload);
  } catch (error) {
    if (error instanceof AuthAdminError && error.code === "UNSUPPORTED_AUTH_ADMIN_CONTRACT") {
      throw new AuthAdminError(error.message, {
        status: response.status,
        code: error.code,
        retryable: error.retryable,
        userAction: error.userAction,
        contract: error.contract ?? undefined,
      });
    }
    throw error;
  }
}

function getRequest(signal?: AbortSignal): RequestInit {
  return { method: "GET", headers: { Accept: "application/json" }, signal };
}

function postRequest(body: unknown | undefined, signal?: AbortSignal): RequestInit {
  return body === undefined
    ? { method: "POST", headers: { Accept: "application/json" }, signal }
    : {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      };
}

function assertUserId(userId: string): void {
  if (!USER_ID_RE.test(userId)) {
    throw new AuthAdminError("Пользователь не найден.", {
      status: 404,
      code: "ADMIN_USER_NOT_FOUND",
      retryable: false,
      userAction: "Обновите список пользователей.",
    });
  }
}

function assertLoginCredentials(credentials: LoginCredentials): void {
  if (!isRecord(credentials) || !hasExactKeys(credentials, ["email", "password"]) ||
    typeof credentials.email !== "string" || credentials.email.length > 254 ||
    typeof credentials.password !== "string" || credentials.password.length > 256) {
    throw new AuthAdminError("Не удалось войти. Проверьте данные и повторите попытку.", {
      status: 401,
      code: "AUTH_INVALID_CREDENTIALS",
      retryable: true,
      userAction: "Проверьте адрес и пароль.",
    });
  }
}

function assertCreateUser(input: CreateLocalPilotUser): void {
  if (!isRecord(input) || !hasExactKeys(input, ["email", "display_name", "password", "role_id"]) ||
    !isEmail(input.email) || !isSafeText(input.display_name, 2, 120) ||
    typeof input.password !== "string" || input.password.length < 12 || input.password.length > 256 ||
    !/[A-Za-zА-Яа-яЁё]/.test(input.password) || !/\d/.test(input.password) ||
    !isEnum(input.role_id, ROLE_IDS)) throw invalidMutation();
}

function assertUserPatch(input: UpdateLocalPilotUser): void {
  if (!isRecord(input) || !Object.keys(input).length ||
    Object.keys(input).some((key) => key !== "display_name" && key !== "role_id") ||
    ("display_name" in input && !isSafeText(input.display_name, 2, 120)) ||
    ("role_id" in input && !isEnum(input.role_id, ROLE_IDS))) throw invalidMutation();
}

export function getAuthSession(
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AuthSessionV1> {
  return requestContract(AUTH_SESSION_PATH, parseAuthSession, getRequest(signal), baseUrl);
}

export function loginWithCredentials(
  credentials: LoginCredentials,
  signal?: AbortSignal,
  baseUrl?: string,
): Promise<AuthSessionV1>;
export function loginWithCredentials(
  email: string,
  password: string,
  signal?: AbortSignal,
  baseUrl?: string,
): Promise<AuthSessionV1>;
export async function loginWithCredentials(
  credentialsOrEmail: LoginCredentials | string,
  passwordOrSignal?: string | AbortSignal,
  signalOrBaseUrl?: AbortSignal | string,
  explicitBaseUrl = appEnv.apiBaseUrl,
): Promise<AuthSessionV1> {
  const credentials = typeof credentialsOrEmail === "string"
    ? {
        email: credentialsOrEmail,
        password: typeof passwordOrSignal === "string" ? passwordOrSignal : "",
      }
    : credentialsOrEmail;
  const signal = typeof credentialsOrEmail === "string"
    ? typeof signalOrBaseUrl === "string" ? undefined : signalOrBaseUrl
    : typeof passwordOrSignal === "string" ? undefined : passwordOrSignal;
  const baseUrl = typeof credentialsOrEmail === "string"
    ? explicitBaseUrl
    : typeof signalOrBaseUrl === "string" ? signalOrBaseUrl : appEnv.apiBaseUrl;
  assertLoginCredentials(credentials);
  const session = await requestContract(
    AUTH_LOGIN_PATH,
    parseAuthSession,
    postRequest(credentials, signal),
    baseUrl,
    false,
    false,
  );
  if (!session.authenticated) throw unsupportedContract("auth_session_v1", 200);
  return session;
}

export async function logoutSession(
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AuthSessionV1> {
  const session = await requestContract(
    AUTH_LOGOUT_PATH,
    parseAuthSession,
    postRequest(undefined, signal),
    baseUrl,
    false,
    false,
  );
  if (session.authenticated) throw unsupportedContract("auth_session_v1", 200);
  return session;
}

export function getAdminUsers(
  query: AdminUsersQuery = {},
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AdminUserListV1> {
  const normalized = normalizeAdminUsersQuery(query);
  return requestContract(
    `${ADMIN_USERS_PATH}?${serializeAdminUsersQuery(normalized)}`,
    (value) => parseAdminUserList(value, normalized),
    getRequest(signal),
    baseUrl,
  );
}

export function createAdminUser(
  input: CreateLocalPilotUser,
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AdminUserDetailV1> {
  assertCreateUser(input);
  return requestContract(
    ADMIN_USERS_PATH,
    parseAdminUserDetail,
    postRequest(input, signal),
    baseUrl,
  );
}

export function getAdminUser(
  userId: string,
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AdminUserDetailV1> {
  assertUserId(userId);
  return requestContract(
    `${ADMIN_USERS_PATH}/${encodeURIComponent(userId)}`,
    parseAdminUserDetail,
    getRequest(signal),
    baseUrl,
  );
}

export function patchAdminUser(
  userId: string,
  input: UpdateLocalPilotUser,
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AdminUserDetailV1> {
  assertUserId(userId);
  assertUserPatch(input);
  return requestContract(
    `${ADMIN_USERS_PATH}/${encodeURIComponent(userId)}`,
    parseAdminUserDetail,
    {
      method: "PATCH",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(input),
      signal,
    },
    baseUrl,
  );
}

export function setAdminUserEnabled(
  userId: string,
  enabled: boolean,
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AdminUserDetailV1> {
  assertUserId(userId);
  return requestContract(
    `${ADMIN_USERS_PATH}/${encodeURIComponent(userId)}/${enabled ? "enable" : "disable"}`,
    parseAdminUserDetail,
    postRequest(undefined, signal),
    baseUrl,
  );
}

export function revokeAdminUserSessions(
  userId: string,
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<RevokeAdminUserSessionsResult> {
  assertUserId(userId);
  return requestContract(
    `${ADMIN_USERS_PATH}/${encodeURIComponent(userId)}/sessions/revoke`,
    parseRevokeAdminUserSessions,
    postRequest(undefined, signal),
    baseUrl,
  );
}

export function getAdminRoles(
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AdminRoleCatalogV1> {
  return requestContract(ADMIN_ROLES_PATH, parseAdminRoleCatalog, getRequest(signal), baseUrl);
}

export function getAdminSystemStatus(
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AdminSystemStatusV1> {
  return requestContract(ADMIN_SYSTEM_PATH, parseAdminSystemStatus, getRequest(signal), baseUrl);
}

export function getAdminAudit(
  query: AdminAuditQuery = {},
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<AdminAuditLogV1> {
  const normalized = normalizeAdminAuditQuery(query);
  return requestContract(
    `${ADMIN_AUDIT_PATH}?${serializeAdminAuditQuery(normalized)}`,
    (value) => parseAdminAuditLog(value, normalized),
    getRequest(signal),
    baseUrl,
  );
}
