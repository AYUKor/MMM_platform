import type { AdminAuditLogV1 } from "../shared/api/generated/admin-audit-log-v1";
import type { AdminRoleCatalogV1 } from "../shared/api/generated/admin-role-catalog-v1";
import type { AdminSystemStatusV1 } from "../shared/api/generated/admin-system-status-v1";
import type { AdminUserDetailV1 } from "../shared/api/generated/admin-user-detail-v1";
import type { AdminUserListV1 } from "../shared/api/generated/admin-user-list-v1";
import type { AuthSessionV1 } from "../shared/api/generated/auth-session-v1";

export const DEMO_BADGE = "Демонстрационные данные";

type FixtureRoleId = "viewer" | "analyst" | "admin";

const ROLE_TITLES: Record<FixtureRoleId, string> = {
  viewer: "Наблюдатель",
  analyst: "Аналитик",
  admin: "Администратор",
};

const VIEWER_PERMISSIONS = [
  "workspace.read",
  "calculation.read",
  "result.read",
  "model.read",
  "help.read",
];

const ANALYST_PERMISSIONS = [
  ...VIEWER_PERMISSIONS,
  "calculation.create",
  "calculation.cancel",
  "report.download",
];

const ADMIN_PERMISSIONS = [
  ...ANALYST_PERMISSIONS,
  "admin.users.read",
  "admin.users.write",
  "admin.roles.write",
  "admin.sessions.write",
  "admin.system.read",
  "admin.audit.read",
];

const ROLE_PERMISSIONS: Record<FixtureRoleId, string[]> = {
  viewer: VIEWER_PERMISSIONS,
  analyst: ANALYST_PERMISSIONS,
  admin: ADMIN_PERMISSIONS,
};

const SESSION_USERS: Record<
  FixtureRoleId,
  {
    userId: string;
    sessionId: string;
    displayName: string;
    email: string;
  }
> = {
  viewer: {
    userId: "usr_333333333333333333333333",
    sessionId: "ses_cccccccccccccccccccccccc",
    displayName: "Анна Морозова",
    email: "anna.morozova@example.org",
  },
  analyst: {
    userId: "usr_222222222222222222222222",
    sessionId: "ses_bbbbbbbbbbbbbbbbbbbbbbbb",
    displayName: "Илья Волков",
    email: "ilya.volkov@example.org",
  },
  admin: {
    userId: "usr_111111111111111111111111",
    sessionId: "ses_aaaaaaaaaaaaaaaaaaaaaaaa",
    displayName: "Мария Соколова",
    email: "maria.sokolova@example.org",
  },
};

function fixtureRole(roleId: FixtureRoleId) {
  return {
    role_id: roleId,
    title: ROLE_TITLES[roleId],
  };
}

export function createAnonymousSessionFixture(): AuthSessionV1 {
  return {
    contract_name: "auth_session_v1",
    schema_version: "1.0.0",
    authenticated: false,
    user: null,
    session: null,
  };
}

export function createAuthenticatedSessionFixture(
  roleId: FixtureRoleId = "admin",
): AuthSessionV1 {
  const identity = SESSION_USERS[roleId];

  return {
    contract_name: "auth_session_v1",
    schema_version: "1.0.0",
    authenticated: true,
    user: {
      user_id: identity.userId,
      display_name: identity.displayName,
      email: identity.email,
      role: fixtureRole(roleId),
      permissions: [...ROLE_PERMISSIONS[roleId]],
      status: "active",
    },
    session: {
      session_id: identity.sessionId,
      created_at_utc: "2026-07-17T09:00:00Z",
      expires_at_utc: "2026-07-17T17:00:00Z",
      last_seen_at_utc: "2026-07-17T10:15:00Z",
      idle_timeout_seconds: 3_600,
    },
  };
}

export function createAdminUserListFixture(): AdminUserListV1 {
  return {
    contract_name: "admin_user_list_v1",
    schema_version: "1.0.0",
    items: [
      {
        user_id: "usr_444444444444444444444444",
        display_name: "Олег Смирнов",
        email: "oleg.smirnov@example.org",
        role: fixtureRole("viewer"),
        status: "disabled",
        created_at_utc: "2026-07-17T09:20:00Z",
        updated_at_utc: "2026-07-17T10:05:00Z",
        last_login_at_utc: null,
        created_by_user_id: "usr_111111111111111111111111",
        active_sessions_n: 0,
      },
      {
        user_id: "usr_333333333333333333333333",
        display_name: "Анна Морозова",
        email: "anna.morozova@example.org",
        role: fixtureRole("viewer"),
        status: "active",
        created_at_utc: "2026-07-17T08:00:00Z",
        updated_at_utc: "2026-07-17T08:00:00Z",
        last_login_at_utc: "2026-07-17T09:40:00Z",
        created_by_user_id: "usr_111111111111111111111111",
        active_sessions_n: 1,
      },
      {
        user_id: "usr_222222222222222222222222",
        display_name: "Илья Волков",
        email: "ilya.volkov@example.org",
        role: fixtureRole("analyst"),
        status: "active",
        created_at_utc: "2026-07-16T11:00:00Z",
        updated_at_utc: "2026-07-16T11:00:00Z",
        last_login_at_utc: "2026-07-17T09:55:00Z",
        created_by_user_id: "usr_111111111111111111111111",
        active_sessions_n: 2,
      },
      {
        user_id: "usr_111111111111111111111111",
        display_name: "Мария Соколова",
        email: "maria.sokolova@example.org",
        role: fixtureRole("admin"),
        status: "active",
        created_at_utc: "2026-07-15T08:30:00Z",
        updated_at_utc: "2026-07-15T08:30:00Z",
        last_login_at_utc: "2026-07-17T10:15:00Z",
        created_by_user_id: null,
        active_sessions_n: 1,
      },
    ],
    pagination: {
      page: 1,
      page_size: 25,
      total_items: 4,
      total_pages: 1,
    },
    applied_filters: {
      search: null,
      role: null,
      status: null,
      sort: "created_desc",
    },
  };
}

export function createAdminUserDetailFixture(): AdminUserDetailV1 {
  const analyst = createAdminUserListFixture().items[2];

  return {
    contract_name: "admin_user_detail_v1",
    schema_version: "1.0.0",
    user: {
      ...analyst,
      role: { ...analyst.role },
    },
  };
}

export function createAdminRoleCatalogFixture(): AdminRoleCatalogV1 {
  return {
    contract_name: "admin_role_catalog_v1",
    schema_version: "1.0.0",
    catalog_version: "1.0.0",
    permissions: [
      {
        permission_id: "workspace.read",
        title: "Просмотр главной",
        description: "Просматривать рабочее пространство и сводку расчетов.",
      },
      {
        permission_id: "calculation.read",
        title: "Просмотр расчетов",
        description: "Просматривать историю, состояние и ход расчетов.",
      },
      {
        permission_id: "calculation.create",
        title: "Создание расчетов",
        description: "Загружать кампании, проверять их и запускать расчет.",
      },
      {
        permission_id: "calculation.cancel",
        title: "Отмена расчетов",
        description: "Запрашивать отмену незавершенного расчета.",
      },
      {
        permission_id: "result.read",
        title: "Просмотр результатов",
        description: "Просматривать опубликованные результаты и медиапланы.",
      },
      {
        permission_id: "report.download",
        title: "Скачивание отчетов",
        description: "Скачивать опубликованные файлы результата.",
      },
      {
        permission_id: "model.read",
        title: "Просмотр модели",
        description: "Просматривать паспорт и ограничения активной модели.",
      },
      {
        permission_id: "help.read",
        title: "Просмотр справки",
        description: "Просматривать справку и опубликованные контракты.",
      },
      {
        permission_id: "admin.users.read",
        title: "Просмотр пользователей",
        description: "Просматривать учетные записи и каталог ролей.",
      },
      {
        permission_id: "admin.users.write",
        title: "Изменение пользователей",
        description: "Создавать и изменять локальные учетные записи.",
      },
      {
        permission_id: "admin.roles.write",
        title: "Управление ролями",
        description: "Изменять назначения ролей в пределах каталога.",
      },
      {
        permission_id: "admin.sessions.write",
        title: "Отзыв сессий",
        description: "Завершать активные пользовательские сессии.",
      },
      {
        permission_id: "admin.system.read",
        title: "Состояние системы",
        description: "Просматривать безопасную техническую сводку.",
      },
      {
        permission_id: "admin.audit.read",
        title: "Журнал действий",
        description: "Просматривать административный журнал действий.",
      },
    ],
    roles: [
      {
        role_id: "viewer",
        title: "Наблюдатель",
        description: "Может читать рабочие сведения и опубликованные результаты.",
        permissions: [...VIEWER_PERMISSIONS],
      },
      {
        role_id: "analyst",
        title: "Аналитик",
        description:
          "Может готовить, запускать и отменять расчеты, а также скачивать отчеты.",
        permissions: [...ANALYST_PERMISSIONS],
      },
      {
        role_id: "admin",
        title: "Администратор",
        description:
          "Управляет пользователями, сессиями и просмотром состояния системы.",
        permissions: [...ADMIN_PERMISSIONS],
      },
    ],
  };
}

export function createAdminSystemStatusFixture(): AdminSystemStatusV1 {
  return {
    contract_name: "admin_system_status_v1",
    schema_version: "1.0.0",
    overall_status: "degraded",
    checked_at_utc: "2026-07-17T10:20:00Z",
    subsystems: {
      application: {
        status: "healthy",
        display_text: "Приложение отвечает на запросы.",
        facts: { service_version: "1.6.0" },
      },
      storage: {
        status: "healthy",
        display_text: "Хранилище расчетов доступно.",
        facts: { available: true },
      },
      queue: {
        status: "healthy",
        display_text: "Локальная очередь расчетов работает.",
        facts: {
          mode: "single_process_thread_pool",
          workers: 1,
          active_jobs: 1,
          queued_jobs: 0,
          failed_jobs_24h: 0,
        },
      },
      model: {
        status: "degraded",
        display_text: "Активная модель доступна с ограничениями.",
        facts: { available: true, calculation_allowed: false },
      },
      reports: {
        status: "healthy",
        display_text: "Формирование отчетов доступно.",
        facts: { available: true },
      },
      auth_storage: {
        status: "healthy",
        display_text: "Хранилище пользователей и сессий доступно.",
        facts: { available: true, integrity_check: "ok" },
      },
    },
    build: {
      application_version: "1.6.0",
      api_version: "1.6.0",
      config_schema_version: "1.2.0",
      source_revision: "4444444444444444444444444444444444444444",
    },
  };
}

export function createAdminAuditLogFixture(): AdminAuditLogV1 {
  return {
    contract_name: "admin_audit_log_v1",
    schema_version: "1.0.0",
    items: [
      {
        event_id: "evt_444444444444444444444444",
        event_type: "session_revoked",
        occurred_at_utc: "2026-07-17T10:18:00Z",
        actor_user_id: "usr_111111111111111111111111",
        actor_display_name: "Мария Соколова",
        target_type: "user",
        target_id: "usr_222222222222222222222222",
        result: "succeeded",
        browser_safe_summary: "Активные сеансы пользователя завершены.",
        request_id: "req_444444444444444444444444",
      },
      {
        event_id: "evt_333333333333333333333333",
        event_type: "role_changed",
        occurred_at_utc: "2026-07-17T10:12:00Z",
        actor_user_id: "usr_111111111111111111111111",
        actor_display_name: "Мария Соколова",
        target_type: "user",
        target_id: "usr_222222222222222222222222",
        result: "succeeded",
        browser_safe_summary: "Пользователю назначена роль «Аналитик».",
        request_id: "req_333333333333333333333333",
      },
      {
        event_id: "evt_222222222222222222222222",
        event_type: "user_created",
        occurred_at_utc: "2026-07-17T10:05:00Z",
        actor_user_id: "usr_111111111111111111111111",
        actor_display_name: "Мария Соколова",
        target_type: "user",
        target_id: "usr_444444444444444444444444",
        result: "succeeded",
        browser_safe_summary: "Создана локальная учетная запись пользователя.",
        request_id: "req_222222222222222222222222",
      },
      {
        event_id: "evt_111111111111111111111111",
        event_type: "login_failed",
        occurred_at_utc: "2026-07-17T09:58:00Z",
        actor_user_id: null,
        actor_display_name: null,
        target_type: "authentication",
        target_id: null,
        result: "denied",
        browser_safe_summary: "Неудачная попытка входа.",
        request_id: "req_111111111111111111111111",
      },
    ],
    pagination: {
      page: 1,
      page_size: 50,
      total_items: 4,
      total_pages: 1,
    },
    applied_filters: {
      actor_user_id: null,
      event_type: null,
      occurred_from_utc: null,
      occurred_to_utc: null,
      sort: "occurred_desc",
    },
  };
}
