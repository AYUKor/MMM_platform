import { describe, expect, it } from "vitest";
import type { AuthSessionV1 } from "../shared/api/generated/auth-session-v1";
import { firstAdminPath, hasAnyPermission, hasPermission, safeReturnTo } from "./access";

function session(permissions: string[]): AuthSessionV1 {
  return {
    contract_name: "auth_session_v1",
    schema_version: "1.0.0",
    authenticated: true,
    user: {
      user_id: "usr_0123456789abcdef01234567",
      display_name: "Тестовый пользователь",
      email: "test@example.org",
      role: { role_id: "viewer", title: "Наблюдатель" },
      permissions,
      status: "active",
    },
    session: {
      session_id: "ses_0123456789abcdef01234567",
      created_at_utc: "2026-07-17T08:00:00Z",
      last_seen_at_utc: "2026-07-17T08:01:00Z",
      expires_at_utc: "2026-07-17T18:00:00Z",
      idle_timeout_seconds: 1800,
    },
  };
}

describe("permission helpers", () => {
  it("uses only returned permission IDs and never infers access from role_id", () => {
    const adminWithoutPermissions = session([]);
    if (adminWithoutPermissions.user) adminWithoutPermissions.user.role.role_id = "admin";
    expect(hasPermission(adminWithoutPermissions, "admin.users.read")).toBe(false);
    expect(firstAdminPath(adminWithoutPermissions)).toBeNull();
  });

  it("selects the first actually permitted admin section", () => {
    expect(firstAdminPath(session(["admin.audit.read"]))).toBe("/admin/audit");
    expect(firstAdminPath(session(["admin.system.read", "admin.audit.read"]))).toBe("/admin/system");
    expect(hasAnyPermission(session(["admin.sessions.write"]), ["admin.users.read", "admin.sessions.write"])).toBe(true);
  });
});

describe("safeReturnTo", () => {
  it("keeps an internal route with query and rejects external or login loops", () => {
    expect(safeReturnTo("/calculations?status=active#items")).toBe("/calculations?status=active#items");
    expect(safeReturnTo("//evil.example.org/admin")).toBe("/");
    expect(safeReturnTo("https://evil.example.org")).toBe("/");
    expect(safeReturnTo("/login?return_to=/admin")).toBe("/");
  });
});
