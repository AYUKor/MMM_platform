import type {
  JobResultViewV2,
  Quantiles,
  RiskBudget,
  Scenario,
} from "../shared/api/generated/job-result-view-v2";
import type {
  ScenarioId,
  ScenarioMediaPlanV2,
} from "../shared/api/generated/scenario-media-plan-v2";
import type { ValidationResultV2 } from "../shared/api/generated/validation-result-v2";

export const CONTROL_REQUESTED_BUDGET = 267_818_706;
export const CONTROL_S5_ALLOCATED_BUDGET = 173_912_510.62947646;
export const CONTROL_S5_UNALLOCATED_BUDGET = 93_906_195.37052354;
export const TEST_JOB_ID = "job_eeeeeeeeeeeeeeeeeeee";
export const TEST_VALIDATION_ID = "validation_eeeeeeeeeeeeeeeeeeee";
export const TEST_RESULT_ID = "result_eeeeeeeeeeeeeeeeeeee";
export const TEST_CAMPAIGN_ID = "campaign_eeeeeeeeeeeeeeeeeeee";

export const TEST_CHANNELS = [
  { channel_id: "Digital_Performance", channel_display_name: "Цифровая реклама" },
  { channel_id: "OOH_Total", channel_display_name: "Наружная реклама" },
  { channel_id: "Радио", channel_display_name: "Радио" },
] as const;

export const TEST_GEOS = Array.from({ length: 15 }, (_, index) => ({
  geo_id: `geo_${(index + 1).toString(16).padStart(16, "0")}`,
  geo_display_name: `География ${String(index + 1).padStart(2, "0")}`,
}));

function available(unit: string, p50: number, displayText: string): Quantiles {
  return {
    status: "available",
    unit,
    p10: p50 * 0.9,
    p50,
    p90: p50 * 1.1,
    display_text: displayText,
  };
}

function unavailable(unit: string, displayText: string): Quantiles {
  return { status: "unavailable", unit, p10: null, p50: null, p90: null, display_text: displayText };
}

function risk(allocated: number, mode: "mixed" | "safe" | "empty"): RiskBudget {
  if (mode === "empty") {
    return {
      within_support_budget_rub: 0,
      within_support_share: null,
      controlled_extrapolation_budget_rub: 0,
      controlled_extrapolation_share: null,
      high_risk_budget_rub: 0,
      high_risk_share: null,
      within_support_cells_n: 0,
      controlled_extrapolation_cells_n: 0,
      high_risk_cells_n: 0,
    };
  }
  if (mode === "safe") {
    return {
      within_support_budget_rub: allocated,
      within_support_share: 1,
      controlled_extrapolation_budget_rub: 0,
      controlled_extrapolation_share: 0,
      high_risk_budget_rub: 0,
      high_risk_share: 0,
      within_support_cells_n: 30,
      controlled_extrapolation_cells_n: 0,
      high_risk_cells_n: 0,
    };
  }
  const within = allocated * 0.72;
  const controlled = allocated * 0.23;
  const high = allocated - within - controlled;
  return {
    within_support_budget_rub: within,
    within_support_share: within / allocated,
    controlled_extrapolation_budget_rub: controlled,
    controlled_extrapolation_share: controlled / allocated,
    high_risk_budget_rub: high,
    high_risk_share: high / allocated,
    within_support_cells_n: 28,
    controlled_extrapolation_cells_n: 14,
    high_risk_cells_n: 3,
  };
}

function scenario(
  id: ScenarioId,
  options: {
    name: string;
    kind: Scenario["scenario_kind"];
    variant: string;
    status?: Scenario["status"];
    allocated?: number;
    turnover?: number;
    decision?: Scenario["decision_status"];
    review?: Scenario["review_status"];
    recommended?: boolean;
    reliability?: Scenario["reliability"]["status"];
    constraints?: string[];
  },
): Scenario {
  const status = options.status ?? "completed";
  const allocated = options.allocated ?? CONTROL_REQUESTED_BUDGET;
  const turnover = options.turnover ?? 330_000_000;
  const completed = status === "completed";
  const partial = id === "S05" && options.variant === "safe_partial";
  return {
    scenario_id: id,
    name: options.name,
    description: `Демонстрационное описание сценария ${Number(id.slice(1))}.`,
    scenario_kind: options.kind,
    scenario_variant: options.variant,
    status,
    is_recommended: options.recommended ?? false,
    decision_status: options.decision ?? "unavailable",
    review_status: options.review ?? "manual_review_required",
    budget: {
      requested_budget_rub: CONTROL_REQUESTED_BUDGET,
      allocated_budget_rub: allocated,
      unallocated_budget_rub: CONTROL_REQUESTED_BUDGET - allocated,
      allocation_share: allocated / CONTROL_REQUESTED_BUDGET,
    },
    incremental_turnover: completed
      ? available("RUB", turnover, "Дополнительный оборот относительно варианта без кампании.")
      : unavailable("RUB", "Показатель недоступен, потому что полный план не сформирован."),
    roas: {
      allocated_budget: completed
        ? available("ratio", partial ? 1.9817393657528313 : turnover / allocated, "Дополнительный оборот относительно распределенной части бюджета.")
        : unavailable("ratio", "Показатель недоступен, потому что полный план не сформирован."),
      requested_budget: completed
        ? available("ratio", partial ? 1.2868752659545044 : turnover / CONTROL_REQUESTED_BUDGET, "Дополнительный оборот относительно всего запрошенного бюджета.")
        : unavailable("ratio", "Показатель недоступен, потому что полный план не сформирован."),
      primary_denominator_kind: partial ? "allocated_budget" : "requested_budget",
      primary_denominator_budget_rub: partial ? allocated : CONTROL_REQUESTED_BUDGET,
    },
    risk_budget: risk(allocated, status === "infeasible" ? "empty" : partial ? "safe" : "mixed"),
    reliability: {
      status: options.reliability ?? (completed ? "manual_review" : "unavailable"),
      display_text: completed ? "Признаки надежности опубликованы для ручной проверки." : "Надежность недоступна, потому что полный план не сформирован.",
      evidence_codes: completed ? ["DEMO_EVIDENCE"] : ["SCENARIO_INFEASIBLE"],
      safe_rank: completed ? Number(id.slice(1)) : null,
      raw_rank: completed ? Number(id.slice(1)) : null,
    },
    limiting_constraints: options.constraints ?? [],
  };
}

export function buildJobResultViewV2(): JobResultViewV2 {
  return {
    contract_name: "job_result_view_v2",
    schema_version: "2.0.0",
    record_origin: "sanitized_fixture",
    job_id: TEST_JOB_ID,
    result_id: TEST_RESULT_ID,
    source_overview_id: "overview_eeeeeeeeeeeeeeeeeeee",
    updated_at_utc: "2026-07-18T10:00:00Z",
    campaign: {
      campaign_id: TEST_CAMPAIGN_ID,
      campaign_name: "Демонстрационная кампания",
      segments: ["Сегмент A"],
      start_date: "2026-08-01",
      end_date: "2026-08-15",
      requested_budget_rub: CONTROL_REQUESTED_BUDGET,
      channels: [...TEST_CHANNELS],
      geographies_n: TEST_GEOS.length,
      geographies: TEST_GEOS,
    },
    recommendation: {
      decision_status: "keep_uploaded_plan",
      review_status: "manual_review_required",
      scenario_id: "S01",
      title: "Исходный план сохранен для проверки",
      display_text: "Автоматическое перераспределение не подтвердило надежного улучшения. Исходный план сохранен как точка отсчета и требует ручной проверки.",
      decision_scope_text: "Рекомендация относится к распределению бюджета, а не к решению о запуске кампании.",
    },
    scenarios: [
      scenario("S01", { name: "Исходный план", kind: "uploaded_plan", variant: "uploaded_plan", decision: "keep_uploaded_plan", review: "manual_review_required", turnover: 345_000_000 }),
      scenario("S02", { name: "Равномерный план", kind: "benchmark_plan", variant: "benchmark_even", turnover: 320_000_000 }),
      scenario("S03", { name: "Исторический микс", kind: "benchmark_plan", variant: "benchmark_history", turnover: 338_000_000 }),
      scenario("S04", { name: "Контрольный план", kind: "benchmark_plan", variant: "benchmark_control", turnover: 350_000_000 }),
      scenario("S05", {
        name: "Безопасно распределяемая часть",
        kind: "conservative_plan",
        variant: "safe_partial",
        allocated: CONTROL_S5_ALLOCATED_BUDGET,
        turnover: 344_649_268.5113412,
        decision: "no_safe_recommendation",
        review: "manual_review_required",
        reliability: "within_support",
        constraints: ["Часть бюджета выходит за подтвержденные границы модели."],
      }),
      scenario("S06", {
        name: "План максимального эффекта",
        kind: "optimized_plan",
        variant: "infeasible",
        status: "infeasible",
        allocated: 0,
        decision: "unavailable",
        review: "manual_review_required",
        reliability: "unavailable",
        constraints: [
          "При текущих каналах и географиях полный бюджет распределить нельзя.",
          "Для полного плана нужно изменить границы кампании.",
        ],
      }),
    ],
    media_plan: {
      endpoint: `/api/v1/jobs/${TEST_JOB_ID}/media-plan-v2`,
      selected_scenario_id: "S01",
    },
    map: {
      status: "unavailable",
      display_text: "Утвержденный справочник координат пока не подключен.",
      coordinate_catalog_version: "geo_catalog_v1_unlocated_test",
      geo_points: TEST_GEOS.map((geo) => ({
        ...geo,
        latitude: null,
        longitude: null,
        coordinates_status: "unavailable" as const,
        region_id: null,
        region_display_name: null,
      })),
    },
    limitations: [
      { code: "RESEARCH_PREPROD", display_text: "Результат требует проверки перед бизнес-решением." },
    ],
  };
}

function splitTotal(total: number, count: number): number[] {
  const base = total / count;
  const values = Array.from({ length: count }, () => base);
  values[count - 1] = total - base * (count - 1);
  return values;
}

function aggregateRows(rows: ScenarioMediaPlanV2["rows"], kind: "channel" | "geo" | "geo-channel") {
  const groups = new Map<string, ScenarioMediaPlanV2["rows"]>();
  for (const row of rows) {
    const key = kind === "channel" ? row.channel_id : kind === "geo" ? row.geo_id : `${row.geo_id}\u0000${row.channel_id}`;
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return [...groups.values()].map((items) => {
    const first = items[0];
    const source = items.reduce((sum, item) => sum + item.source_budget_rub, 0);
    const selected = items.reduce((sum, item) => sum + item.selected_budget_rub, 0);
    return {
      ...(kind !== "channel" ? { geo_id: first.geo_id, geo_display_name: first.geo_display_name } : {}),
      ...(kind !== "geo" ? { channel_id: first.channel_id, channel_display_name: first.channel_display_name } : {}),
      source_budget_rub: source,
      selected_budget_rub: selected,
      delta_rub: selected - source,
      delta_pct: source === 0 ? null : (selected - source) / source * 100,
      quality_status: "safe",
      quality_display_text: "Внутри опубликованных границ.",
    };
  });
}

export function buildScenarioMediaPlanV2(
  scenarioId: ScenarioId = "S01",
  query: { page?: number; pageSize?: number; channel?: string | null; geo?: string | null } = {},
): ScenarioMediaPlanV2 {
  const result = buildJobResultViewV2();
  const selectedScenario = result.scenarios.find((item) => item.scenario_id === scenarioId) ?? result.scenarios[0];
  const selectedTotal = selectedScenario.budget.allocated_budget_rub;
  const sourceBudgets = splitTotal(CONTROL_REQUESTED_BUDGET, TEST_GEOS.length * TEST_CHANNELS.length);
  const selectedBudgets = splitTotal(selectedTotal, TEST_GEOS.length * TEST_CHANNELS.length);
  const allRows = TEST_GEOS.flatMap((geo, geoIndex) => TEST_CHANNELS.map((channel, channelIndex) => {
    const index = geoIndex * TEST_CHANNELS.length + channelIndex;
    const source = sourceBudgets[index];
    const selected = selectedBudgets[index];
    return {
      scenario_id: scenarioId,
      campaign_id: TEST_CAMPAIGN_ID,
      segment: "Сегмент A",
      ...geo,
      ...channel,
      date: null,
      source_budget_rub: source,
      selected_budget_rub: selected,
      delta_rub: selected - source,
      delta_pct: source === 0 ? null : (selected - source) / source * 100,
      source_budget_share: source / CONTROL_REQUESTED_BUDGET,
      selected_budget_share: selectedTotal === 0 ? 0 : selected / selectedTotal,
      quality_status: "safe",
      quality_display_text: "Внутри опубликованных границ.",
    };
  }));
  const filtered = allRows.filter((row) => (!query.channel || row.channel_id === query.channel) && (!query.geo || row.geo_display_name === query.geo));
  const page = query.page ?? 1;
  const pageSize = query.pageSize ?? 100;
  const rows = filtered.slice((page - 1) * pageSize, page * pageSize);
  const filteredSource = filtered.reduce((sum, row) => sum + row.source_budget_rub, 0);
  const filteredSelected = filtered.reduce((sum, row) => sum + row.selected_budget_rub, 0);
  const byChannel = aggregateRows(allRows, "channel") as ScenarioMediaPlanV2["aggregates"]["by_channel"];
  const byGeo = aggregateRows(allRows, "geo") as ScenarioMediaPlanV2["aggregates"]["by_geo"];
  const byGeoChannel = aggregateRows(allRows, "geo-channel") as ScenarioMediaPlanV2["aggregates"]["by_geo_channel"];
  return {
    contract_name: "scenario_media_plan_v2",
    schema_version: "2.0.0",
    record_origin: "sanitized_fixture",
    job_id: TEST_JOB_ID,
    result_id: TEST_RESULT_ID,
    campaign_id: TEST_CAMPAIGN_ID,
    scenario: {
      scenario_id: scenarioId,
      title: selectedScenario.name,
      status: "completed",
      is_selected: scenarioId === result.recommendation.scenario_id,
      safe_rank: selectedScenario.reliability.safe_rank,
      raw_rank: selectedScenario.reliability.raw_rank,
      quality_status: "safe",
      quality_display_text: selectedScenario.reliability.display_text,
    },
    source_artifact: {
      artifact_id: "artifact_eeeeeeeeeeeeeeeeeeee",
      kind: "recommended_allocations_csv",
      sha256: "e".repeat(64),
    },
    grain: "geo_channel_total",
    filters: { channel_id: query.channel ?? null, geo_display_name: query.geo ?? null, date: null },
    pagination: {
      page,
      page_size: pageSize,
      total_rows: filtered.length,
      total_pages: Math.ceil(filtered.length / pageSize),
    },
    totals: {
      requested_budget_rub: CONTROL_REQUESTED_BUDGET,
      source_budget_rub: CONTROL_REQUESTED_BUDGET,
      selected_budget_rub: selectedTotal,
      unallocated_budget_rub: selectedScenario.budget.unallocated_budget_rub,
      delta_rub: selectedTotal - CONTROL_REQUESTED_BUDGET,
      reconciliation_status: "reconciled",
    },
    filtered_totals: {
      source_budget_rub: filteredSource,
      selected_budget_rub: filteredSelected,
      delta_rub: filteredSelected - filteredSource,
    },
    rows,
    aggregates: {
      by_channel: byChannel,
      by_geo: byGeo,
      by_geo_channel: byGeoChannel,
      by_date: { status: "unavailable", display_text: "Дневная детализация недоступна.", rows: null },
      channel_date_matrix: { status: "unavailable", display_text: "Дневная матрица недоступна.", rows: null },
      geo_channel_matrix: { status: "ready", display_text: "Матрица готова.", rows: byGeoChannel },
    },
    map: {
      status: "unavailable",
      display_text: "Координаты пока недоступны.",
      geo_points: null,
      coordinate_catalog_version: null,
    },
    working_media_plan: { status: "unavailable", display_text: "Файл медиаплана пока недоступен.", artifact: null },
    limitations: [{ code: "MAP_UNAVAILABLE", display_text: "Карта пока недоступна." }],
    updated_at_utc: "2026-07-18T10:00:00Z",
  };
}

export function buildValidationResultV2(): ValidationResultV2 {
  const geoBudgets = splitTotal(CONTROL_REQUESTED_BUDGET, TEST_GEOS.length);
  return {
    contract_name: "validation_result_v2",
    schema_version: "2.0.0",
    validation_id: TEST_VALIDATION_ID,
    status: "warning",
    job_creation_allowed: true,
    file_validation: {
      status: "passed",
      rows_n: 45,
      campaigns_n: 1,
      geographies_n: 15,
      channels_n: 3,
      requested_budget_rub: CONTROL_REQUESTED_BUDGET,
      blocking_errors_n: 0,
      warnings_n: 0,
      checks: [
        { code: "FILE_STRUCTURE", status: "passed", display_text: "Структура файла корректна." },
        { code: "CAMPAIGN_COUNT", status: "passed", display_text: "В файле одна кампания." },
        { code: "BUDGET_RECONCILIATION", status: "passed", display_text: "Бюджет согласован по всем строкам." },
        { code: "DATES", status: "passed", display_text: "Даты заполнены корректно." },
      ],
    },
    model_limitations: [{
      target: "turnover",
      channel_id: "Digital_Performance",
      channel_display_name: "Цифровая реклама",
      limitation_type: "controlled_extrapolation",
      affected_geos_n: 15,
      affected_geos: TEST_GEOS.map((geo) => geo.geo_display_name),
      severity: "manual_review",
      allowed_use: "caution",
      blocks_calculation: false,
      what: "Для цифровой рекламы часть прогноза требует осторожной интерпретации.",
      why: "В этих географиях историческая поддержка ограничена.",
      recommended_action: "Проверьте отмеченные географии перед изменением бюджета.",
    }],
    map_coverage: {
      status: "unavailable",
      located_geographies_n: 0,
      unlocated_geographies_n: TEST_GEOS.length,
      unlocated_geographies: TEST_GEOS.map((geo) => ({ ...geo })),
      located_budget_rub: 0,
      unlocated_budget_rub: CONTROL_REQUESTED_BUDGET,
      unlocated_budget_share: 1,
    },
    geo_points: TEST_GEOS.map((geo, index) => ({
      ...geo,
      input_geo_name: geo.geo_display_name,
      canonical_geo_id: null,
      canonical_geo_display_name: null,
      normalization_status: "unknown" as const,
      normalization_rule: "synthetic_fixture_without_coordinates",
      latitude: null,
      longitude: null,
      coordinates_status: "unavailable" as const,
      region_id: null,
      region_display_name: null,
      budget_rub: geoBudgets[index],
      budget_share: geoBudgets[index] / CONTROL_REQUESTED_BUDGET,
      channels: [...TEST_CHANNELS],
      has_model_limitations: true,
      model_limitations_n: 1,
    })),
  };
}
