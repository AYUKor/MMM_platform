import type { Event as AuditEvent } from "../../shared/api/generated/admin-audit-log-v1";
import type { Status as SystemStatus } from "../../shared/api/generated/admin-system-status-v1";

export const USER_SORTS = [
  "created_desc",
  "created_asc",
  "name_asc",
  "email_asc",
  "last_login_desc",
] as const;
export const USER_ROLES = ["viewer", "analyst", "admin"] as const;
export const USER_STATUSES = ["active", "disabled"] as const;
export const AUDIT_SORTS = ["occurred_desc", "occurred_asc"] as const;
export const AUDIT_EVENT_TYPES: AuditEvent["event_type"][] = [
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
];

export interface AdminUsersUrlState {
  page: number;
  pageSize: number;
  search: string | null;
  role: (typeof USER_ROLES)[number] | null;
  status: (typeof USER_STATUSES)[number] | null;
  sort: (typeof USER_SORTS)[number];
}

export interface AdminAuditUrlState {
  page: number;
  pageSize: number;
  actorUserId: string | null;
  eventType: AuditEvent["event_type"] | null;
  occurredFromUtc: string | null;
  occurredToUtc: string | null;
  sort: (typeof AUDIT_SORTS)[number];
}

function positiveInt(value: string | null, fallback: number, maximum: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 && parsed <= maximum ? parsed : fallback;
}

function member<T extends string>(value: string | null, choices: readonly T[]): value is T {
  return value !== null && choices.includes(value as T);
}

function trimmed(value: string | null, maximum: number): string | null {
  const next = value?.trim() ?? "";
  return next && next.length <= maximum ? next : null;
}

export function readUsersUrlState(params: URLSearchParams): AdminUsersUrlState {
  const role = params.get("role");
  const status = params.get("status");
  const sort = params.get("sort");
  return {
    page: positiveInt(params.get("page"), 1, 1_000_000),
    pageSize: positiveInt(params.get("page_size"), 25, 100),
    search: trimmed(params.get("search"), 120),
    role: member(role, USER_ROLES) ? role : null,
    status: member(status, USER_STATUSES) ? status : null,
    sort: member(sort, USER_SORTS) ? sort : "created_desc",
  };
}

export function usersUrlParams(state: AdminUsersUrlState): URLSearchParams {
  const params = new URLSearchParams({
    page: String(state.page),
    page_size: String(state.pageSize),
    sort: state.sort,
  });
  if (state.search) params.set("search", state.search);
  if (state.role) params.set("role", state.role);
  if (state.status) params.set("status", state.status);
  return params;
}

function readDateTime(value: string | null): string | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : new Date(parsed).toISOString();
}

export function readAuditUrlState(params: URLSearchParams): AdminAuditUrlState {
  const eventType = params.get("event_type");
  const sort = params.get("sort");
  return {
    page: positiveInt(params.get("page"), 1, 1_000_000),
    pageSize: positiveInt(params.get("page_size"), 50, 100),
    actorUserId: /^usr_[0-9a-f]{24}$/.test(params.get("actor_user_id") ?? "")
      ? params.get("actor_user_id")
      : null,
    eventType: member(eventType, AUDIT_EVENT_TYPES) ? eventType : null,
    occurredFromUtc: readDateTime(params.get("occurred_from_utc")),
    occurredToUtc: readDateTime(params.get("occurred_to_utc")),
    sort: member(sort, AUDIT_SORTS) ? sort : "occurred_desc",
  };
}

export function auditUrlParams(state: AdminAuditUrlState): URLSearchParams {
  const params = new URLSearchParams({
    page: String(state.page),
    page_size: String(state.pageSize),
    sort: state.sort,
  });
  if (state.actorUserId) params.set("actor_user_id", state.actorUserId);
  if (state.eventType) params.set("event_type", state.eventType);
  if (state.occurredFromUtc) params.set("occurred_from_utc", state.occurredFromUtc);
  if (state.occurredToUtc) params.set("occurred_to_utc", state.occurredToUtc);
  return params;
}

export function formatAdminDate(value: string | null): string {
  if (value === null) return "Нет данных";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Нет данных";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function toDateTimeLocal(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function fromDateTimeLocal(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export const EVENT_LABELS: Record<AuditEvent["event_type"], string> = {
  login_succeeded: "Вход выполнен",
  login_failed: "Вход отклонен",
  logout: "Выход выполнен",
  session_revoked: "Сессии завершены",
  user_created: "Пользователь создан",
  user_updated: "Пользователь изменен",
  user_enabled: "Пользователь включен",
  user_disabled: "Пользователь отключен",
  role_changed: "Роль изменена",
  admin_viewed_system_status: "Просмотрено состояние системы",
  admin_viewed_audit_log: "Просмотрен журнал действий",
};

export const RESULT_LABELS: Record<AuditEvent["result"], string> = {
  succeeded: "Выполнено",
  denied: "Отклонено",
  rate_limited: "Временно ограничено",
  account_disabled: "Учетная запись отключена",
};

export const SYSTEM_STATUS_LABELS: Record<SystemStatus, string> = {
  healthy: "Работает",
  degraded: "Есть ограничения",
  unavailable: "Недоступно",
};

export const SUBSYSTEM_LABELS = {
  application: "Приложение",
  storage: "Хранилище расчетов",
  queue: "Очередь расчетов",
  model: "Активная модель",
  reports: "Формирование отчетов",
  auth_storage: "Пользователи и сессии",
} as const;

export const SYSTEM_FACT_LABELS: Record<string, string> = {
  service_version: "Версия сервиса",
  available: "Доступность",
  mode: "Режим выполнения",
  workers: "Исполнителей",
  active_jobs: "Активных расчетов",
  queued_jobs: "В очереди",
  failed_jobs_24h: "Ошибок за 24 часа",
  calculation_allowed: "Расчеты разрешены",
  integrity_check: "Проверка целостности",
};

export function formatSystemFact(key: string, value: string | number | boolean | null): string {
  if (value === null) return "Нет данных";
  if (typeof value === "boolean") return value ? "Да" : "Нет";
  if (key === "mode" && value === "single_process_thread_pool") return "Локальная очередь";
  if (key === "integrity_check" && value === "ok") return "Пройдена";
  return String(value);
}
