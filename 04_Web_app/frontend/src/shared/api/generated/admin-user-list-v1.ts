/* Generated from ../../contracts/admin_user_list_v1.schema.json. Do not edit manually. */

export interface AdminUserListV1 {
  contract_name: "admin_user_list_v1";
  schema_version: "1.0.0";
  items: User[];
  pagination: Pagination;
  applied_filters: Filters;
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
export interface Pagination {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
}
export interface Filters {
  search: string | null;
  role: "viewer" | "analyst" | "admin" | null;
  status: "active" | "disabled" | null;
  sort: "created_desc" | "created_asc" | "name_asc" | "email_asc" | "last_login_desc";
}
