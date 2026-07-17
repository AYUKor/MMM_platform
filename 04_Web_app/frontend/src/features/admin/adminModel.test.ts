import { describe, expect, it } from "vitest";
import {
  AUDIT_EVENT_TYPES,
  EVENT_LABELS,
  RESULT_LABELS,
  SYSTEM_STATUS_LABELS,
  auditUrlParams,
  formatAdminDate,
  formatSystemFact,
  fromDateTimeLocal,
  readAuditUrlState,
  readUsersUrlState,
  toDateTimeLocal,
  usersUrlParams,
  type AdminAuditUrlState,
  type AdminUsersUrlState,
} from "./adminModel";

describe("Phase E admin URL state", () => {
  it("round-trips every supported Users filter through backend query names", () => {
    const state: AdminUsersUrlState = {
      page: 3,
      pageSize: 50,
      search: "Медиаплан августа",
      role: "analyst",
      status: "active",
      sort: "last_login_desc",
    };

    const params = usersUrlParams(state);

    expect(params.toString()).toContain("page_size=50");
    expect(readUsersUrlState(params)).toEqual(state);
  });

  it("uses controlled Users defaults for missing or unsupported URL values", () => {
    const params = new URLSearchParams({
      page: "0",
      page_size: "101",
      search: "   ",
      role: "owner",
      status: "pending",
      sort: "unknown",
    });

    expect(readUsersUrlState(params)).toEqual({
      page: 1,
      pageSize: 25,
      search: null,
      role: null,
      status: null,
      sort: "created_desc",
    });
  });

  it("round-trips every supported Audit filter and normalizes timestamps", () => {
    const state: AdminAuditUrlState = {
      page: 2,
      pageSize: 100,
      actorUserId: "usr_111111111111111111111111",
      eventType: "role_changed",
      occurredFromUtc: "2026-07-01T00:00:00.000Z",
      occurredToUtc: "2026-07-17T23:59:00.000Z",
      sort: "occurred_asc",
    };

    const params = auditUrlParams(state);

    expect(params.toString()).toContain("actor_user_id=usr_111111111111111111111111");
    expect(readAuditUrlState(params)).toEqual(state);
  });

  it("uses controlled Audit defaults for malformed IDs, dates and enums", () => {
    const params = new URLSearchParams({
      page: "-1",
      page_size: "0",
      actor_user_id: "usr_visible-name",
      event_type: "password_reset",
      occurred_from_utc: "not-a-date",
      occurred_to_utc: "also-not-a-date",
      sort: "latest",
    });

    expect(readAuditUrlState(params)).toEqual({
      page: 1,
      pageSize: 50,
      actorUserId: null,
      eventType: null,
      occurredFromUtc: null,
      occurredToUtc: null,
      sort: "occurred_desc",
    });
  });
});

describe("Phase E admin labels and missing-value semantics", () => {
  it("provides reviewed Russian labels for every audit event and result", () => {
    expect(AUDIT_EVENT_TYPES).toHaveLength(11);
    for (const eventType of AUDIT_EVENT_TYPES) {
      expect(EVENT_LABELS[eventType]).toEqual(expect.any(String));
      expect(EVENT_LABELS[eventType]).not.toBe(eventType);
    }
    expect(RESULT_LABELS).toEqual({
      succeeded: "Выполнено",
      denied: "Отклонено",
      rate_limited: "Временно ограничено",
      account_disabled: "Учетная запись отключена",
    });
    expect(SYSTEM_STATUS_LABELS).toEqual({
      healthy: "Работает",
      degraded: "Есть ограничения",
      unavailable: "Недоступно",
    });
  });

  it("keeps null distinct from known zero and false", () => {
    expect(formatAdminDate(null)).toBe("Нет данных");
    expect(formatAdminDate("invalid")).toBe("Нет данных");
    expect(formatSystemFact("queued_jobs", null)).toBe("Нет данных");
    expect(formatSystemFact("queued_jobs", 0)).toBe("0");
    expect(formatSystemFact("available", false)).toBe("Нет");
    expect(formatSystemFact("available", true)).toBe("Да");
    expect(toDateTimeLocal(null)).toBe("");
    expect(fromDateTimeLocal("")).toBeNull();
  });
});
