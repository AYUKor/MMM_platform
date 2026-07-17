/* Generated from ../../contracts/admin_user_detail_v1.schema.json. Do not edit manually. */

export interface AdminUserDetailV1 {
  contract_name: "admin_user_detail_v1";
  schema_version: "1.0.0";
  user: User;
}
export interface User {
  user_id: string;
  display_name: string;
  email: string;
  role: Role;
  status: "active" | "disabled";
  created_at_utc: string;
  updated_at_utc: string;
  last_login_at_utc: string | null;
  created_by_user_id: null | string;
  active_sessions_n: number;
}
export interface Role {
  role_id: "viewer" | "analyst" | "admin";
  title: string;
}
