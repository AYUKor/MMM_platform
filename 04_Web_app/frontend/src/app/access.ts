export type AppRole = "marketer" | "analyst" | "admin";

export interface AppAccess {
  role: AppRole | null;
  authConnected: boolean;
}

export const currentAccess: AppAccess = {
  role: null,
  authConnected: false,
};

export function canAccessAdmin(access: AppAccess): boolean {
  return access.authConnected && access.role === "admin";
}
