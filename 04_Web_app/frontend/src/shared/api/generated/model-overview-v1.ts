/* Generated from ../../contracts/model_overview_v1.schema.json. Do not edit manually. */

export type NonEmptyText = string;
export type ModelId = string;
export type NullableText = string | null;

export interface ModelOverviewV1 {
  contract_name: "model_overview_v1";
  schema_version: "1.0.0";
  record_origin: "application_runtime" | "synthetic_fixture";
  active_model: ActiveModel;
  /**
   * @minItems 5
   * @maxItems 5
   */
  capabilities: [Capability, Capability, Capability, Capability, Capability];
  /**
   * @minItems 1
   */
  data_requirements: [DataRequirement, ...DataRequirement[]];
  /**
   * @minItems 6
   * @maxItems 6
   */
  methodology: [Methodology, Methodology, Methodology, Methodology, Methodology, Methodology];
  /**
   * @minItems 4
   */
  limitations: [Limitation, Limitation, Limitation, Limitation, ...Limitation[]];
  versions: Version[];
  artifacts: Artifact[];
  updated_at_utc: string;
}
export interface ActiveModel {
  status: {
    code: "available" | "unavailable";
    display_text: NonEmptyText;
  };
  model_id: ModelId | null;
  display_name: NullableText;
  version: NullableText;
  published_at_utc: string | null;
  framework: NullableText;
  purpose: NonEmptyText;
  training_period: Period | null;
  supported_scope: SupportedScope | null;
  description: NonEmptyText;
}
export interface Period {
  start_date: string;
  end_date: string;
}
export interface SupportedScope {
  segments: NonEmptyText[];
  channels: NonEmptyText[];
  targets: NonEmptyText[];
  geographies_n: number;
  capability_cells_n: number;
  allowed_use_counts: AllowedUseCounts;
}
export interface AllowedUseCounts {
  primary: number;
  caution: number;
  diagnostic: number;
  unavailable: number;
}
export interface Capability {
  capability_id:
    "incremental_effect_forecast" | "six_scenarios" | "budget_allocation" | "safe_recommendation" | "marketer_report";
  title: NonEmptyText;
  status: "available" | "conditional" | "unavailable";
  description: NonEmptyText;
}
export interface DataRequirement {
  requirement_id: NonEmptyText;
  title: NonEmptyText;
  required: boolean;
  description: NonEmptyText;
  accepted_values: NonEmptyText[];
}
export interface Methodology {
  method_id:
    | "carryover"
    | "saturation"
    | "uncertainty"
    | "counterfactual_forecast"
    | "scenario_search"
    | "reliability_guardrails";
  title: NonEmptyText;
  summary: NonEmptyText;
}
export interface Limitation {
  code: NonEmptyText;
  status: "active" | "unavailable";
  title: NonEmptyText;
  display_text: NonEmptyText;
  recommended_action: NonEmptyText;
}
export interface Version {
  model_id: ModelId;
  model_run_id: NonEmptyText;
  registered_at_utc: string | null;
  package_stage: NonEmptyText;
  activation_status: NonEmptyText;
  status: "active" | "registered";
  source: "registry_registration" | "active_model_passport";
}
export interface Artifact {
  artifact_id: NonEmptyText;
  title: NonEmptyText;
  status: "available" | "unavailable";
  path: string | null;
  display_text: NonEmptyText;
}
