import type { AuthSessionV1 } from "../shared/api/generated/auth-session-v1";

export const APP_PERMISSIONS = [
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

export type AppPermission = (typeof APP_PERMISSIONS)[number];
export type AuthenticatedSession = AuthSessionV1 & {
  authenticated: true;
  user: NonNullable<AuthSessionV1["user"]>;
  session: NonNullable<AuthSessionV1["session"]>;
};

function permissionSet(session: AuthSessionV1 | null): ReadonlySet<string> {
  if (!session?.authenticated || !session.user) return new Set();
  return new Set(session.user.permissions);
}

export function hasPermission(
  session: AuthSessionV1 | null,
  permissionId: AppPermission,
): boolean {
  return permissionSet(session).has(permissionId);
}

export function hasAnyPermission(
  session: AuthSessionV1 | null,
  permissionIds: readonly AppPermission[],
): boolean {
  const permissions = permissionSet(session);
  return permissionIds.some((permissionId) => permissions.has(permissionId));
}

export function firstAdminPath(session: AuthSessionV1 | null): string | null {
  if (hasPermission(session, "admin.users.read")) return "/admin/users";
  if (hasPermission(session, "admin.system.read")) return "/admin/system";
  if (hasPermission(session, "admin.audit.read")) return "/admin/audit";
  return null;
}

export function safeReturnTo(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";
  try {
    const url = new URL(value, "http://local.invalid");
    if (url.origin !== "http://local.invalid" || url.pathname === "/login") return "/";
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/";
  }
}
