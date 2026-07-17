/* Generated from ../../contracts/admin_system_status_v1.schema.json. Do not edit manually. */

export type Status = "healthy" | "degraded" | "unavailable";
export type Fact = string | number | boolean | null;

export interface AdminSystemStatusV1 {
  contract_name: "admin_system_status_v1";
  schema_version: "1.0.0";
  overall_status: Status;
  checked_at_utc: string;
  subsystems: {
    application: Subsystem;
    storage: Subsystem;
    queue: Subsystem;
    model: Subsystem;
    reports: Subsystem;
    auth_storage: Subsystem;
  };
  build: {
    application_version: string;
    api_version: string;
    config_schema_version: string;
    source_revision: null | string;
  };
}
export interface Subsystem {
  status: Status;
  display_text: string;
  facts: {
    [k: string]: Fact;
  };
}
