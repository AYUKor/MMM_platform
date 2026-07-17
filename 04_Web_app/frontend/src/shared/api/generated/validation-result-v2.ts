/* Generated from ../../contracts/validation_result_v2.schema.json. Do not edit manually. */

export interface ValidationResultV2 {
  contract_name: "validation_result_v2";
  schema_version: "2.0.0";
  validation_id: string;
  status: "passed" | "warning" | "failed" | "unavailable";
  job_creation_allowed: boolean;
  file_validation: {
    status: "passed" | "warning" | "failed" | "unavailable";
    rows_n: number;
    campaigns_n: number;
    geographies_n: number;
    channels_n: number;
    requested_budget_rub: number;
    blocking_errors_n: number;
    warnings_n: number;
    checks: {
      code: string;
      status: "passed" | "warning" | "failed" | "unavailable";
      display_text: string;
    }[];
  };
  model_limitations: {
    target: "turnover";
    channel_id: string;
    channel_display_name: string;
    limitation_type: string;
    affected_geos_n: number;
    affected_geos: string[];
    severity: "information" | "warning" | "manual_review" | "blocking";
    allowed_use: "primary" | "caution" | "diagnostic" | "unsupported" | "unavailable";
    blocks_calculation: boolean;
    what: string;
    why: string;
    recommended_action: string;
  }[];
  geo_points: {
    geo_id: string;
    geo_display_name: string;
    latitude: number | null;
    longitude: number | null;
    coordinates_status: "canonical" | "unavailable";
    budget_rub: number;
    budget_share: number | null;
    channels: {
      channel_id: string;
      channel_display_name: string;
    }[];
    has_model_limitations: boolean;
  }[];
}
