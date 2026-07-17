/* Generated from ../../contracts/workspace_geo_budget_v1.schema.json. Do not edit manually. */

export interface WorkspaceGeoBudgetV1 {
  contract_name: "workspace_geo_budget_v1";
  schema_version: "1.0.0";
  catalog_version: string;
  status: "available" | "partial" | "unavailable";
  display_text: string;
  total_budget_rub: number;
  campaigns_n: number;
  geographies_n: number;
  rows: {
    geo_id: string;
    geo_display_name: string;
    latitude: number | null;
    longitude: number | null;
    coordinates_status: "canonical" | "unavailable";
    total_budget_rub: number;
    campaigns_n: number;
    budget_share: number | null;
  }[];
}
