import { afterEach, describe, expect, it, vi } from "vitest";
import { credentialedFetch } from "./credentialed-fetch";
import {
  AuthAdminError,
  createAdminUser,
  getAdminAudit,
  getAdminRoles,
  getAdminSystemStatus,
  getAdminUser,
  getAdminUsers,
  getAuthSession,
  loginWithCredentials,
  logoutSession,
  normalizeAdminAuditQuery,
  normalizeAdminUsersQuery,
  parseAdminAuditLog,
  parseAdminRoleCatalog,
  parseAdminSystemStatus,
  parseAdminUserDetail,
  parseAdminUserList,
  parseAuthSession,
  parseRevokeAdminUserSessions,
  patchAdminUser,
  revokeAdminUserSessions,
  serializeAdminAuditQuery,
  serializeAdminUsersQuery,
  setAdminUserEnabled,
} from "./auth-admin-client";

vi.mock("./credentialed-fetch", () => ({ credentialedFetch: vi.fn() }));

const API_BASE_URL = "http://127.0.0.1:8765/";
const ADMIN_ID = "usr_0123456789abcdef01234567";
const VIEWER_ID = "usr_abcdef0123456789abcdef01";
const SESSION_ID = "ses_0123456789abcdef01234567";
const PERMISSIONS = [
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

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function anonymousSession(): Record<string, unknown> {
  return {
    contract_name: "auth_session_v1",
    schema_version: "1.0.0",
    authenticated: false,
    user: null,
    session: null,
  };
}

function authenticatedSession(): Record<string, unknown> {
  return {
    contract_name: "auth_session_v1",
    schema_version: "1.0.0",
    authenticated: true,
    user: {
      user_id: ADMIN_ID,
      display_name: "Тестовый администратор",
      email: "admin@example.org",
      role: { role_id: "admin", title: "Администратор" },
      permissions: [...PERMISSIONS],
      status: "active",
    },
    session: {
      session_id: SESSION_ID,
      created_at_utc: "2026-07-17T08:00:00+00:00",
      expires_at_utc: "2026-07-17T18:00:00+00:00",
      last_seen_at_utc: "2026-07-17T09:00:00+00:00",
      idle_timeout_seconds: 3600,
    },
  };
}

function userItem(userId = ADMIN_ID): Record<string, unknown> {
  return {
    user_id: userId,
    display_name: userId === ADMIN_ID ? "Тестовый администратор" : "Тестовый наблюдатель",
    email: userId === ADMIN_ID ? "admin@example.org" : "viewer@example.org",
    role: userId === ADMIN_ID
      ? { role_id: "admin", title: "Администратор" }
      : { role_id: "viewer", title: "Наблюдатель" },
    status: "active",
    created_at_utc: "2026-07-17T08:00:00+00:00",
    updated_at_utc: "2026-07-17T08:30:00+00:00",
    last_login_at_utc: "2026-07-17T09:00:00+00:00",
    created_by_user_id: null,
    active_sessions_n: userId === ADMIN_ID ? 1 : 0,
  };
}

function userDetail(userId = ADMIN_ID): Record<string, unknown> {
  return {
    contract_name: "admin_user_detail_v1",
    schema_version: "1.0.0",
    user: userItem(userId),
  };
}

function userList(): Record<string, unknown> {
  return {
    contract_name: "admin_user_list_v1",
    schema_version: "1.0.0",
    items: [userItem(ADMIN_ID), userItem(VIEWER_ID)],
    pagination: { page: 1, page_size: 25, total_items: 2, total_pages: 1 },
    applied_filters: { search: null, role: null, status: null, sort: "created_desc" },
  };
}

function roleCatalog(): Record<string, unknown> {
  return {
    contract_name: "admin_role_catalog_v1",
    schema_version: "1.0.0",
    catalog_version: "1.0.0",
    permissions: PERMISSIONS.map((permissionId, index) => ({
      permission_id: permissionId,
      title: `Разрешение ${index + 1}`,
      description: `Описание разрешения ${index + 1}.`,
    })),
    roles: [
      {
        role_id: "viewer",
        title: "Наблюдатель",
        description: "Просматривает опубликованные сведения.",
        permissions: ["workspace.read", "calculation.read", "result.read", "model.read", "help.read"],
      },
      {
        role_id: "analyst",
        title: "Аналитик",
        description: "Готовит и запускает расчеты.",
        permissions: [
          "workspace.read",
          "calculation.read",
          "result.read",
          "model.read",
          "help.read",
          "calculation.create",
          "calculation.cancel",
          "report.download",
        ],
      },
      {
        role_id: "admin",
        title: "Администратор",
        description: "Управляет локальными учетными записями.",
        permissions: [...PERMISSIONS],
      },
    ],
  };
}

function systemStatus(): Record<string, unknown> {
  const healthy = (displayText: string, facts: Record<string, unknown>) => ({
    status: "healthy",
    display_text: displayText,
    facts,
  });
  return {
    contract_name: "admin_system_status_v1",
    schema_version: "1.0.0",
    overall_status: "healthy",
    checked_at_utc: "2026-07-17T09:00:00+00:00",
    subsystems: {
      application: healthy("Приложение отвечает на запросы.", { service_version: "1.6.0" }),
      storage: healthy("Хранилище расчетов доступно.", { available: true }),
      queue: healthy("Локальная очередь расчетов работает.", {
        mode: "single_process_thread_pool",
        workers: 1,
        active_jobs: 0,
        queued_jobs: 0,
        failed_jobs_24h: 0,
      }),
      model: healthy("Активная модель разрешает расчеты.", {
        available: true,
        calculation_allowed: true,
      }),
      reports: healthy("Формирование отчетов доступно.", { available: true }),
      auth_storage: healthy("Хранилище пользователей и сессий доступно.", {
        available: true,
        integrity_check: "ok",
      }),
    },
    build: {
      application_version: "1.6.0",
      api_version: "1.6.0",
      config_schema_version: "1.0.0",
      source_revision: "0123456789abcdef0123456789abcdef01234567",
    },
  };
}

function auditLog(): Record<string, unknown> {
  return {
    contract_name: "admin_audit_log_v1",
    schema_version: "1.0.0",
    items: [{
      event_id: "evt_0123456789abcdef01234567",
      event_type: "login_succeeded",
      occurred_at_utc: "2026-07-17T09:00:00+00:00",
      actor_user_id: ADMIN_ID,
      actor_display_name: "Тестовый администратор",
      target_type: "session",
      target_id: SESSION_ID,
      result: "succeeded",
      browser_safe_summary: "Вход выполнен успешно.",
      request_id: "req_0123456789abcdef01234567",
    }],
    pagination: { page: 1, page_size: 50, total_items: 1, total_pages: 1 },
    applied_filters: {
      actor_user_id: null,
      event_type: null,
      occurred_from_utc: null,
      occurred_to_utc: null,
      sort: "occurred_desc",
    },
  };
}

function backendError(code: string, displayText: string, retryable: boolean): Record<string, unknown> {
  return {
    error: {
      code,
      display_text: displayText,
      retryable,
      user_action: "Выполните рекомендуемое действие.",
    },
  };
}

afterEach(() => {
  vi.mocked(credentialedFetch).mockReset();
});

describe("Phase E strict response parsers", () => {
  it("accepts all six coherent versioned contracts and the exact revoke response", () => {
    expect(parseAuthSession(anonymousSession()).authenticated).toBe(false);
    expect(parseAuthSession(authenticatedSession()).authenticated).toBe(true);
    expect(parseAdminUserList(userList()).items).toHaveLength(2);
    expect(parseAdminUserDetail(userDetail()).user.active_sessions_n).toBe(1);
    expect(parseAdminRoleCatalog(roleCatalog()).permissions).toHaveLength(14);
    expect(parseAdminSystemStatus(systemStatus()).overall_status).toBe("healthy");
    expect(parseAdminAuditLog(auditLog()).items[0].event_type).toBe("login_succeeded");
    expect(parseRevokeAdminUserSessions({
      user_id: VIEWER_ID,
      revoked_sessions_n: 0,
    }).revoked_sessions_n).toBe(0);
  });

  it("rejects extra keys, inconsistent auth and duplicate users", () => {
    const session = authenticatedSession();
    session.session_token = "must-not-exist";
    expect(() => parseAuthSession(session)).toThrow(AuthAdminError);

    const anonymous = anonymousSession();
    anonymous.user = (authenticatedSession().user as Record<string, unknown>);
    expect(() => parseAuthSession(anonymous)).toThrow(AuthAdminError);

    const users = userList();
    users.items = [userItem(ADMIN_ID), userItem(ADMIN_ID)];
    expect(() => parseAdminUserList(users)).toThrow(AuthAdminError);
  });

  it("rejects catalog drift, system reconciliation errors and unsafe audit copy", () => {
    const catalog = roleCatalog();
    (catalog.permissions as Array<Record<string, unknown>>)[0].permission_id = "unknown.permission";
    expect(() => parseAdminRoleCatalog(catalog)).toThrow(AuthAdminError);

    const system = systemStatus();
    (system.subsystems as Record<string, Record<string, unknown>>).model.status = "degraded";
    expect(() => parseAdminSystemStatus(system)).toThrow(AuthAdminError);

    const audit = auditLog();
    (audit.items as Array<Record<string, unknown>>)[0].browser_safe_summary = "/Users/private/audit.log";
    expect(() => parseAdminAuditLog(audit)).toThrow(AuthAdminError);
  });

  it.each([
    "Stack trace: at AdminService.updateUser",
    "Origin: https://internal.example.org",
    "Host: internal.service:8765",
    "Внутренний request_id=req_0123456789abcdef01234567.",
    "Неуспешный вход для missing.user@example.org.",
  ])("rejects sensitive audit summary text: %s", (summary) => {
    const audit = auditLog();
    const event = (audit.items as Array<Record<string, unknown>>)[0];
    event.event_type = "login_failed";
    event.result = "denied";
    event.browser_safe_summary = summary;

    expect(() => parseAdminAuditLog(audit)).toThrow(AuthAdminError);
  });

  it("reports malformed contracts with the real AuthAdminError code", () => {
    let caught: unknown;
    try {
      parseAuthSession({ contract_name: "auth_session_v1" });
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(AuthAdminError);
    expect(caught).toMatchObject({
      name: "AuthAdminError",
      code: "UNSUPPORTED_AUTH_ADMIN_CONTRACT",
      contract: "auth_session_v1",
    });
  });

  it("requires echoed pagination and filters when a normalized query is provided", () => {
    const usersQuery = normalizeAdminUsersQuery();
    expect(() => parseAdminUserList(userList(), { ...usersQuery, page: 2 })).toThrow(AuthAdminError);

    const auditQuery = normalizeAdminAuditQuery();
    expect(() => parseAdminAuditLog(auditLog(), { ...auditQuery, eventType: "logout" }))
      .toThrow(AuthAdminError);
  });

  it("allows an email in the contract-supported Users search echo", () => {
    const users = userList();
    (users.applied_filters as Record<string, unknown>).search = "viewer@example.org";

    expect(parseAdminUserList(users, {
      ...normalizeAdminUsersQuery(),
      search: "viewer@example.org",
    }).applied_filters.search).toBe("viewer@example.org");
  });
});

describe("Phase E URL query contracts", () => {
  it("normalizes and serializes Users filters using only backend parameter names", () => {
    expect(normalizeAdminUsersQuery()).toEqual({
      page: 1,
      pageSize: 25,
      search: null,
      role: null,
      status: null,
      sort: "created_desc",
    });
    expect(serializeAdminUsersQuery({
      page: 2,
      pageSize: 50,
      search: "  Иван  ",
      role: "analyst",
      status: "active",
      sort: "name_asc",
    })).toBe(
      "page=2&page_size=50&sort=name_asc&search=%D0%98%D0%B2%D0%B0%D0%BD&role=analyst&status=active",
    );
  });

  it("normalizes and explicitly serializes the runtime Audit page size", () => {
    expect(normalizeAdminAuditQuery()).toEqual({
      page: 1,
      pageSize: 50,
      actorUserId: null,
      eventType: null,
      occurredFromUtc: null,
      occurredToUtc: null,
      sort: "occurred_desc",
    });
    expect(serializeAdminAuditQuery({
      actorUserId: ADMIN_ID,
      eventType: "user_updated",
      occurredFromUtc: "2026-07-01T00:00:00+00:00",
      occurredToUtc: "2026-07-17T23:59:59+00:00",
      sort: "occurred_asc",
    })).toBe(
      `page=1&page_size=50&sort=occurred_asc&actor_user_id=${ADMIN_ID}` +
      "&event_type=user_updated&occurred_from_utc=2026-07-01T00%3A00%3A00%2B00%3A00" +
      "&occurred_to_utc=2026-07-17T23%3A59%3A59%2B00%3A00",
    );
  });

  it.each([
    () => normalizeAdminUsersQuery({ page: 0 }),
    () => normalizeAdminUsersQuery({ search: "   " }),
    () => normalizeAdminAuditQuery({ pageSize: 101 }),
    () => normalizeAdminAuditQuery({ occurredFromUtc: "2026-07-17" }),
    () => normalizeAdminAuditQuery({
      occurredFromUtc: "2026-07-18T00:00:00Z",
      occurredToUtc: "2026-07-17T00:00:00Z",
    }),
  ])("rejects an invalid URL state", (assertion) => {
    expect(assertion).toThrow(AuthAdminError);
  });
});

describe("Phase E HTTP clients", () => {
  it("uses only approved endpoints with exact methods, headers and minimal bodies", async () => {
    const fetchMock = vi.mocked(credentialedFetch)
      .mockResolvedValueOnce(jsonResponse(authenticatedSession()))
      .mockResolvedValueOnce(jsonResponse(authenticatedSession()))
      .mockResolvedValueOnce(jsonResponse(anonymousSession()))
      .mockResolvedValueOnce(jsonResponse(userList()))
      .mockResolvedValueOnce(jsonResponse(userDetail(VIEWER_ID), 201))
      .mockResolvedValueOnce(jsonResponse(userDetail(VIEWER_ID)))
      .mockResolvedValueOnce(jsonResponse(userDetail(VIEWER_ID)))
      .mockResolvedValueOnce(jsonResponse(userDetail(VIEWER_ID)))
      .mockResolvedValueOnce(jsonResponse(userDetail(VIEWER_ID)))
      .mockResolvedValueOnce(jsonResponse({ user_id: VIEWER_ID, revoked_sessions_n: 0 }))
      .mockResolvedValueOnce(jsonResponse(roleCatalog()))
      .mockResolvedValueOnce(jsonResponse(systemStatus()))
      .mockResolvedValueOnce(jsonResponse(auditLog()));

    await getAuthSession(undefined, API_BASE_URL);
    const login = { email: "admin@example.org", password: "Admin-password-2026" };
    const create = {
      email: "viewer@example.org",
      display_name: "Тестовый наблюдатель",
      password: "Viewer-password-2026",
      role_id: "viewer" as const,
    };
    const patch = { display_name: "Новое имя" };

    await loginWithCredentials(login, undefined, API_BASE_URL);
    await logoutSession(undefined, API_BASE_URL);
    await getAdminUsers({}, undefined, API_BASE_URL);
    await createAdminUser(create, undefined, API_BASE_URL);
    await getAdminUser(VIEWER_ID, undefined, API_BASE_URL);
    await patchAdminUser(VIEWER_ID, patch, undefined, API_BASE_URL);
    await setAdminUserEnabled(VIEWER_ID, false, undefined, API_BASE_URL);
    await setAdminUserEnabled(VIEWER_ID, true, undefined, API_BASE_URL);
    await revokeAdminUserSessions(VIEWER_ID, undefined, API_BASE_URL);
    await getAdminRoles(undefined, API_BASE_URL);
    await getAdminSystemStatus(undefined, API_BASE_URL);
    await getAdminAudit({}, undefined, API_BASE_URL);

    const get = {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: undefined,
      credentials: "include",
    };
    const post = {
      method: "POST",
      headers: { Accept: "application/json" },
      signal: undefined,
      credentials: "include",
    };
    const jsonPost = (body: unknown) => ({
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: undefined,
      credentials: "include",
    });
    const jsonPatch = (body: unknown) => ({
      method: "PATCH",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: undefined,
      credentials: "include",
    });

    const protectedSignal = { signalUnauthorized: true, signalForbidden: true };
    const loginSignal = { signalUnauthorized: false, signalForbidden: false };

    expect(fetchMock.mock.calls).toEqual([
      ["http://127.0.0.1:8765/api/v1/auth/session", get, protectedSignal],
      ["http://127.0.0.1:8765/api/v1/auth/login", jsonPost(login), loginSignal],
      ["http://127.0.0.1:8765/api/v1/auth/logout", post, loginSignal],
      [
        "http://127.0.0.1:8765/api/v1/admin/users?page=1&page_size=25&sort=created_desc",
        get,
        protectedSignal,
      ],
      ["http://127.0.0.1:8765/api/v1/admin/users", jsonPost(create), protectedSignal],
      [`http://127.0.0.1:8765/api/v1/admin/users/${VIEWER_ID}`, get, protectedSignal],
      [
        `http://127.0.0.1:8765/api/v1/admin/users/${VIEWER_ID}`,
        jsonPatch(patch),
        protectedSignal,
      ],
      [
        `http://127.0.0.1:8765/api/v1/admin/users/${VIEWER_ID}/disable`,
        post,
        protectedSignal,
      ],
      [
        `http://127.0.0.1:8765/api/v1/admin/users/${VIEWER_ID}/enable`,
        post,
        protectedSignal,
      ],
      [
        `http://127.0.0.1:8765/api/v1/admin/users/${VIEWER_ID}/sessions/revoke`,
        post,
        protectedSignal,
      ],
      ["http://127.0.0.1:8765/api/v1/admin/roles", get, protectedSignal],
      ["http://127.0.0.1:8765/api/v1/admin/system/status", get, protectedSignal],
      [
        "http://127.0.0.1:8765/api/v1/admin/audit?page=1&page_size=50&sort=occurred_desc",
        get,
        protectedSignal,
      ],
    ]);
  });

  it("preserves a valid backend error envelope in AuthAdminError", async () => {
    vi.mocked(credentialedFetch).mockResolvedValueOnce(jsonResponse(
      backendError("PERMISSION_DENIED", "Недостаточно прав.", false),
      403,
    ));

    await expect(getAdminRoles(undefined, API_BASE_URL)).rejects.toMatchObject({
      name: "AuthAdminError",
      status: 403,
      code: "PERMISSION_DENIED",
      message: "Недостаточно прав.",
      retryable: false,
      userAction: "Выполните рекомендуемое действие.",
    });
  });

  it("does not turn login 401 into a global expired-session signal", async () => {
    vi.mocked(credentialedFetch).mockResolvedValueOnce(jsonResponse(
      backendError("AUTH_INVALID_CREDENTIALS", "Не удалось войти.", true),
      401,
    ));

    await expect(loginWithCredentials(
      { email: "missing@example.org", password: "Wrong-password-2026" },
      undefined,
      API_BASE_URL,
    )).rejects.toMatchObject({ code: "AUTH_INVALID_CREDENTIALS", status: 401 });
    expect(vi.mocked(credentialedFetch).mock.calls[0][2]).toEqual({
      signalUnauthorized: false,
      signalForbidden: false,
    });
  });

  it("fails closed on malformed success and controls network failures", async () => {
    vi.mocked(credentialedFetch)
      .mockResolvedValueOnce(jsonResponse({ contract_name: "auth_session_v1" }))
      .mockRejectedValueOnce(new TypeError("network"));

    await expect(getAuthSession(undefined, API_BASE_URL)).rejects.toMatchObject({
      code: "UNSUPPORTED_AUTH_ADMIN_CONTRACT",
      status: 200,
    });
    await expect(getAdminRoles(undefined, API_BASE_URL)).rejects.toMatchObject({
      code: "AUTH_ADMIN_REQUEST_FAILED",
      status: null,
      retryable: true,
    });
  });

  it("refuses malformed mutation paths and empty PATCH bodies before fetch", async () => {
    expect(() => getAdminUser("../../private", undefined, API_BASE_URL))
      .toThrow(expect.objectContaining({ code: "ADMIN_USER_NOT_FOUND" }));
    expect(() => patchAdminUser(VIEWER_ID, {}, undefined, API_BASE_URL))
      .toThrow(expect.objectContaining({ code: "ADMIN_STATE_INCONSISTENT" }));
    expect(() => createAdminUser({
      email: "viewer@example.org",
      display_name: "Тестовый наблюдатель",
      password: "Viewer-password-2026",
      role_id: "viewer",
      active_sessions_n: 0,
    } as never, undefined, API_BASE_URL)).toThrow(
      expect.objectContaining({ code: "ADMIN_STATE_INCONSISTENT" }),
    );
    expect(() => patchAdminUser(VIEWER_ID, {
      display_name: "Новое имя",
      email: "unchanged@example.org",
    } as never, undefined, API_BASE_URL)).toThrow(
      expect.objectContaining({ code: "ADMIN_STATE_INCONSISTENT" }),
    );
    expect(credentialedFetch).not.toHaveBeenCalled();
  });
});
