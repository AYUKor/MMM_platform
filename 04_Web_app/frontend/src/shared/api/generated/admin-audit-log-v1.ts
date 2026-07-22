/* Generated from ../../contracts/admin_audit_log_v1.schema.json. Do not edit manually. */

export interface AdminAuditLogV1 {
  contract_name: "admin_audit_log_v1";
  schema_version: "1.0.0";
  items: Event[];
  pagination: Pagination;
  applied_filters: Filters;
}
export interface Event {
  event_id: string;
  event_type:
    | "login_succeeded"
    | "login_failed"
    | "logout"
    | "session_revoked"
    | "user_created"
    | "user_updated"
    | "user_enabled"
    | "user_disabled"
    | "user_self_registered"
    | "role_changed"
    | "admin_viewed_system_status"
    | "admin_viewed_audit_log";
  occurred_at_utc: string;
  actor_user_id: null | string;
  actor_display_name: string | null;
  target_type: string;
  target_id: string | null;
  result: "succeeded" | "denied" | "rate_limited" | "account_disabled";
  browser_safe_summary: string;
  request_id: string;
}
export interface Pagination {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
}
export interface Filters {
  actor_user_id: null | string;
  event_type: string | null;
  occurred_from_utc: string | null;
  occurred_to_utc: string | null;
  sort: "occurred_desc" | "occurred_asc";
}
