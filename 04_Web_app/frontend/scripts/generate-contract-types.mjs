import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const contracts = [
  {
    schema: "decision_result_v1.schema.json",
    typeName: "DecisionResultV1",
    output: "decision-result-v1.ts",
  },
  {
    schema: "application_lifecycle_v1.schema.json",
    typeName: "ApplicationLifecycleV1",
    output: "application-lifecycle-v1.ts",
  },
  {
    schema: "result_overview_v1.schema.json",
    typeName: "ResultOverviewV1",
    output: "result-overview-v1.ts",
  },
  {
    schema: "product_api_v1.schema.json",
    typeName: "ProductApiV1",
    output: "product-api-v1.ts",
  },
  {
    schema: "job_progress_view_v1.schema.json",
    typeName: "JobProgressViewV1",
    output: "job-progress-view-v1.ts",
  },
  {
    schema: "job_result_view_v1.schema.json",
    typeName: "JobResultViewV1",
    output: "job-result-view-v1.ts",
  },
  {
    schema: "scenario_media_plan_v1.schema.json",
    typeName: "ScenarioMediaPlanV1",
    output: "scenario-media-plan-v1.ts",
  },
  {
    schema: "mmm_fact_catalog_v1.schema.json",
    typeName: "MmmFactCatalogV1",
    output: "mmm-fact-catalog-v1.ts",
  },
  {
    schema: "workspace_home_v1.schema.json",
    typeName: "WorkspaceHomeV1",
    output: "workspace-home-v1.ts",
  },
  {
    schema: "calculation_history_v1.schema.json",
    typeName: "CalculationHistoryV1",
    output: "calculation-history-v1.ts",
  },
  {
    schema: "model_overview_v1.schema.json",
    typeName: "ModelOverviewV1",
    output: "model-overview-v1.ts",
  },
  {
    schema: "help_catalog_v1.schema.json",
    typeName: "HelpCatalogV1",
    output: "help-catalog-v1.ts",
  },
  {
    schema: "auth_session_v1.schema.json",
    typeName: "AuthSessionV1",
    output: "auth-session-v1.ts",
  },
  {
    schema: "admin_user_list_v1.schema.json",
    typeName: "AdminUserListV1",
    output: "admin-user-list-v1.ts",
  },
  {
    schema: "admin_user_detail_v1.schema.json",
    typeName: "AdminUserDetailV1",
    output: "admin-user-detail-v1.ts",
  },
  {
    schema: "admin_user_mutation_v1.schema.json",
    typeName: "AdminUserMutationV1",
    output: "admin-user-mutation-v1.ts",
  },
  {
    schema: "admin_role_catalog_v1.schema.json",
    typeName: "AdminRoleCatalogV1",
    output: "admin-role-catalog-v1.ts",
  },
  {
    schema: "admin_system_status_v1.schema.json",
    typeName: "AdminSystemStatusV1",
    output: "admin-system-status-v1.ts",
  },
  {
    schema: "admin_audit_log_v1.schema.json",
    typeName: "AdminAuditLogV1",
    output: "admin-audit-log-v1.ts",
  },
];

for (const contract of contracts) {
  const schemaPath = resolve(scriptDir, "../../contracts", contract.schema);
  const outputPath = resolve(
    scriptDir,
    "../src/shared/api/generated",
    contract.output,
  );
  const schema = JSON.parse(await readFile(schemaPath, "utf8"));
  const source = await compile(schema, contract.typeName, {
    bannerComment: `/* Generated from ../../contracts/${contract.schema}. Do not edit manually. */`,
    style: { singleQuote: false, semi: true, tabWidth: 2 },
  });
  await writeFile(outputPath, source, "utf8");
}
