/* Generated from ../../contracts/auth_session_v1.schema.json. Do not edit manually. */

export type AuthSessionV1 = {
  [k: string]: unknown;
} & {
  contract_name: "auth_session_v1";
  schema_version: "1.0.0";
  authenticated: boolean;
  user: null | User;
  session: null | Session;
};

export interface User {
  user_id: string;
  display_name: string;
  email: string;
  role: Role;
  permissions: string[];
  status: "active";
}
export interface Role {
  role_id: "viewer" | "analyst" | "admin";
  title: string;
}
export interface Session {
  session_id: string;
  created_at_utc: string;
  expires_at_utc: string;
  last_seen_at_utc: string;
  idle_timeout_seconds: number;
}
