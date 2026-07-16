/* Generated from ../../contracts/calculation_history_v1.schema.json. Do not edit manually. */

export type OpaqueId = string;
export type InternalPath = string;

export interface CalculationHistoryV1 {
  contract_name: "calculation_history_v1";
  schema_version: "1.0.0";
  record_origin: "application_runtime" | "synthetic_fixture";
  summary: {
    all: number;
    active: number;
    succeeded: number;
    failed: number;
    cancelled: number;
    timed_out: number;
  };
  filters: {
    status:
      null | "active" | "queued" | "running" | "cancel_requested" | "succeeded" | "failed" | "cancelled" | "timed_out";
    search: string | null;
    created_from: string | null;
    created_to: string | null;
    sort: "created_desc" | "created_asc" | "completed_desc" | "campaign_asc";
  };
  pagination: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
  };
  items: HistoryItem[];
  updated_at_utc: string;
}
export interface HistoryItem {
  job_id: OpaqueId;
  campaign_name: string;
  created_at_utc: string;
  completed_at_utc: string | null;
  status: "queued" | "running" | "cancel_requested" | "succeeded" | "failed" | "cancelled" | "timed_out";
  status_display_text: string;
  campaign_period: Period | null;
  total_budget_rub: number | null;
  segments: string[] | null;
  channels_n: number | null;
  geographies_n: number | null;
  result_available: boolean;
  report_available: boolean;
  progress_path: InternalPath;
  result_path: InternalPath | null;
  warnings_count: number | null;
}
export interface Period {
  start_date: string;
  end_date: string;
}
