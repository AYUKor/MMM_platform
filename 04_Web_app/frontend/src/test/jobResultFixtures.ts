import type {
  ArtifactAvailability,
  BudgetComparison,
  HeadlineMetric,
  JobResultViewV1,
  QuantileMetric,
  Reliability,
  Scenario,
  ScenarioId,
} from "../shared/api/generated/job-result-view-v1";
import type {
  ChannelAggregate,
  GeoChannelAggregate,
  MediaPlanRow,
  ScenarioMediaPlanV1,
} from "../shared/api/generated/scenario-media-plan-v1";

const JOB_ID = "job_1234567890ab";
const RESULT_ID = "result_1234567890ab";
const CAMPAIGN_ID = "campaign_1234567890ab";
const SOURCE_OVERVIEW_ID = "overview_1234567890ab";
const SOURCE_ARTIFACT_ID = "artifact_1234567890ab";
const REPORT_ARTIFACT_ID = "artifact_abcdef123456";
const TOTAL_BUDGET_RUB = 12_000_000;

export const JOB_RESULT_FIXTURE_IDS = {
  jobId: JOB_ID,
  resultId: RESULT_ID,
  campaignId: CAMPAIGN_ID,
  sourceOverviewId: SOURCE_OVERVIEW_ID,
} as const;

export type JobResultFixtureOptions = {
  recommendationStatus?: JobResultViewV1["recommendation"]["status"];
  recommendedScenarioId?: ScenarioId;
  bestRawAvailable?: boolean;
  unavailableScenarioIds?: readonly ScenarioId[];
  modelCoverageShare?: number;
  reportStatus?: JobResultViewV1["report"]["status"];
};

export type ScenarioMediaPlanFixtureOptions = {
  scenarioId?: ScenarioId;
  resultView?: JobResultViewV1;
  channel?: string | null;
  geo?: string | null;
  page?: number;
  pageSize?: number;
};

type ScenarioSeed = {
  scenarioId: ScenarioId;
  title: string;
  description: string;
  role: Scenario["role"];
  allocatedBudgetRub: number;
  turnoverP50: number;
  safeRank: number | null;
  rawRank: number | null;
  qualityStatus: Scenario["quality_status"];
};

const SCENARIO_SEEDS: readonly ScenarioSeed[] = [
  {
    scenarioId: "S01",
    title: "Как загружено",
    description: "Бюджет, каналы и географии сохранены в исходном распределении.",
    role: "source",
    allocatedBudgetRub: 12_000_000,
    turnoverP50: 18_400_000,
    safeRank: 5,
    rawRank: 6,
    qualityStatus: "caution",
  },
  {
    scenarioId: "S02",
    title: "Ровно по связкам",
    description: "Бюджет поровну распределен между исходными связками география × канал.",
    role: "control",
    allocatedBudgetRub: 12_000_000,
    turnoverP50: 19_100_000,
    safeRank: 4,
    rawRank: 5,
    qualityStatus: "caution",
  },
  {
    scenarioId: "S03",
    title: "Каналы как были, географии ровно",
    description: "Бюджет каждого канала сохранен и поровну распределен между его географиями.",
    role: "control",
    allocatedBudgetRub: 12_000_000,
    turnoverP50: 19_700_000,
    safeRank: 3,
    rawRank: 4,
    qualityStatus: "safe",
  },
  {
    scenarioId: "S04",
    title: "Географии как были, каналы ровно",
    description: "Бюджет каждой географии сохранен и поровну распределен между ее каналами.",
    role: "control",
    allocatedBudgetRub: 12_000_000,
    turnoverP50: 20_100_000,
    safeRank: 6,
    rawRank: 3,
    qualityStatus: "caution",
  },
  {
    scenarioId: "S05",
    title: "Устойчивый ориентир",
    description: "Бюджет распределен ближе к уровням активности, которые модель наблюдала в истории.",
    role: "benchmark",
    allocatedBudgetRub: 11_800_000,
    turnoverP50: 20_600_000,
    safeRank: 2,
    rawRank: 2,
    qualityStatus: "safe",
  },
  {
    scenarioId: "S06",
    title: "Адаптивное распределение",
    description: "Система перебрала варианты и проверила их по эффекту и ограничениям качества.",
    role: "adaptive",
    allocatedBudgetRub: 11_500_000,
    turnoverP50: 21_300_000,
    safeRank: 1,
    rawRank: 1,
    qualityStatus: "safe",
  },
] as const;

function availableMetric(
  unit: QuantileMetric["unit"],
  p50: number,
  spread: number,
  usage: QuantileMetric["usage"] = "primary",
  displayText = "Оценка получена из опубликованного результата расчета.",
): QuantileMetric {
  return {
    status: "available",
    unit,
    p10: p50 - spread,
    p50,
    p90: p50 + spread,
    usage,
    display_text: displayText,
    formula_version:
      unit === "orders_per_100k_RUB"
        ? "orders_quantile_divided_by_deterministic_budget_v1"
        : null,
  };
}

function unavailableMetric(
  unit: QuantileMetric["unit"],
  usage: QuantileMetric["usage"] = "unavailable",
  displayText = "Показатель пока недоступен.",
  formulaVersion: string | null = null,
): QuantileMetric {
  return {
    status: "unavailable",
    unit,
    p10: null,
    p50: null,
    p90: null,
    usage,
    display_text: displayText,
    formula_version: formulaVersion,
  };
}

function createReliability(status: "good" | "caution" | "poor" = "caution"): Reliability {
  return {
    score: null,
    status: "unavailable",
    display_text: "Единая числовая шкала надежности пока не утверждена.",
    components: [
      {
        component_id: "historical_support",
        title: "Историческая поддержка",
        status,
        score: null,
        observed_value: "82% бюджета в наблюдавшемся диапазоне",
        display_text: "Большая часть плана опирается на исторически наблюдавшиеся уровни активности.",
      },
      {
        component_id: "model_support",
        title: "Модельный статус",
        status: "good",
        score: null,
        observed_value: "research/preprod",
        display_text: "Результат подготовлен исследовательской моделью перед промышленным запуском.",
      },
      {
        component_id: "extrapolation",
        title: "Экстраполяция",
        status,
        score: null,
        observed_value: 0.18,
        display_text: "Часть распределения выходит за наиболее плотную область исторических наблюдений.",
      },
      {
        component_id: "posterior_uncertainty",
        title: "Неопределенность оценки",
        status: "unavailable",
        score: null,
        observed_value: null,
        display_text: "Диапазон P10–P90 нужно учитывать при сравнении сценариев.",
      },
      {
        component_id: "business_constraints",
        title: "Бизнес-ограничения",
        status: "good",
        score: null,
        observed_value: "Ограничения соблюдены",
        display_text: "Опубликованный вариант прошел доступные ограничения распределения бюджета.",
      },
      {
        component_id: "data_completeness",
        title: "Полнота рассчитанного бюджета",
        status: "caution",
        score: null,
        observed_value: 0.92,
        display_text: "Непокрытая моделью часть бюджета не считается нулевым эффектом.",
      },
    ],
  };
}

function createScenario(
  seed: ScenarioSeed,
  recommendedScenarioId: ScenarioId | null,
  unavailable: boolean,
): Scenario {
  const isAvailable = !unavailable;
  const turnover = isAvailable
    ? availableMetric("RUB", seed.turnoverP50, 3_200_000)
    : unavailableMetric("RUB", "primary");
  return {
    scenario_id: seed.scenarioId,
    title: seed.title,
    description: seed.description,
    role: seed.role,
    status: isAvailable ? "completed" : "unavailable",
    is_recommended: isAvailable && seed.scenarioId === recommendedScenarioId,
    is_best_safe: isAvailable && seed.scenarioId === recommendedScenarioId && seed.scenarioId === "S06",
    is_best_raw: false,
    safe_rank: isAvailable ? seed.safeRank : null,
    raw_rank: isAvailable ? seed.rawRank : null,
    quality_status: isAvailable ? seed.qualityStatus : "unavailable",
    quality_display_text: isAvailable
      ? seed.qualityStatus === "safe"
        ? "Сценарий прошел опубликованные проверки качества."
        : "Сценарий требует внимательной проверки ограничений."
      : "Сценарий не рассчитан.",
    budget: {
      requested_budget_rub: TOTAL_BUDGET_RUB,
      allocated_budget_rub: seed.allocatedBudgetRub,
      unallocated_budget_rub: TOTAL_BUDGET_RUB - seed.allocatedBudgetRub,
    },
    metrics: {
      incremental_turnover_rub: turnover,
      incremental_orders: isAvailable
        ? availableMetric("orders", seed.turnoverP50 / 1_500, 1_800, "diagnostic_only")
        : unavailableMetric("orders", "diagnostic_only"),
      orders_per_100k_rub: isAvailable
        ? availableMetric("orders_per_100k_RUB", 118 + Number(seed.scenarioId.slice(1)), 14, "diagnostic_only")
        : unavailableMetric(
            "orders_per_100k_RUB",
            "diagnostic_only",
            "Показатель пока недоступен.",
            "orders_quantile_divided_by_deterministic_budget_v1",
          ),
      avg_basket_delta_rub: unavailableMetric(
        "RUB_per_order",
        "unavailable",
        "Изменение среднего чека пока недоступно.",
      ),
      avg_basket_turnover_bridge_rub: isAvailable
        ? availableMetric(
            "turnover_bridge_from_avg_basket_rub",
            seed.turnoverP50 * 0.22,
            950_000,
            "diagnostic_only",
            "Вклад механизма среднего чека в дополнительный оборот.",
          )
        : unavailableMetric("turnover_bridge_from_avg_basket_rub", "diagnostic_only"),
      roas: isAvailable
        ? availableMetric("ratio", seed.turnoverP50 / seed.allocatedBudgetRub, 0.22)
        : unavailableMetric("ratio", "primary"),
    },
    reliability: createReliability(seed.qualityStatus === "safe" ? "good" : "caution"),
  };
}

function deltaPct(source: number, selected: number): number | null {
  return source === 0 ? null : ((selected - source) / source) * 100;
}

function quantileHeadline(
  metricId: Extract<
    HeadlineMetric["metric_id"],
    "incremental_turnover_rub" | "incremental_orders" | "orders_per_100k_rub" | "avg_basket_delta_rub"
  >,
  title: string,
  metric: QuantileMetric,
  unit: HeadlineMetric["unit"],
): HeadlineMetric {
  return {
    metric_id: metricId,
    title,
    status: metric.status,
    unit,
    p10: metric.p10,
    p50: metric.p50,
    p90: metric.p90,
    value: null,
    display_text: metric.display_text,
  };
}

function comparison(
  dimension: { channel?: string; geo?: string },
  source: number,
  selected: number,
): BudgetComparison {
  return {
    ...dimension,
    source_budget_rub: source,
    selected_budget_rub: selected,
    delta_rub: selected - source,
    delta_pct: deltaPct(source, selected),
    quality_status: "safe",
    quality_display_text: "Распределение доступно для сравнения.",
  };
}

function selectedShares(scenarioId: ScenarioId): readonly [number, number] {
  const shareByScenario: Record<ScenarioId, readonly [number, number]> = {
    S01: [7 / 12, 5 / 12],
    S02: [0.5, 0.5],
    S03: [0.55, 0.45],
    S04: [0.52, 0.48],
    S05: [0.58, 0.42],
    S06: [0.61, 0.39],
  };
  return shareByScenario[scenarioId];
}

function createOverviewComparisons(scenario: Scenario): Pick<
  JobResultViewV1["overview"],
  "channel_summary" | "geo_summary" | "geo_channel_summary"
> {
  const selected = scenario.budget.allocated_budget_rub;
  const [firstShare] = selectedShares(scenario.scenario_id);
  const first = selected * firstShare;
  const second = selected - first;
  return {
    channel_summary: [
      comparison({ channel: "Онлайн-видео" }, 7_000_000, first),
      comparison({ channel: "Наружная реклама" }, 5_000_000, second),
    ],
    geo_summary: [
      comparison({ geo: "Москва" }, 7_000_000, first),
      comparison({ geo: "Санкт-Петербург" }, 5_000_000, second),
    ],
    geo_channel_summary: [
      comparison({ geo: "Москва", channel: "Онлайн-видео" }, 4_000_000, first * (4 / 7)),
      comparison({ geo: "Москва", channel: "Наружная реклама" }, 3_000_000, first * (3 / 7)),
      comparison({ geo: "Санкт-Петербург", channel: "Онлайн-видео" }, 3_000_000, second * 0.6),
      comparison({ geo: "Санкт-Петербург", channel: "Наружная реклама" }, 2_000_000, second * 0.4),
    ],
  };
}

function unavailableWorkingPlan(): ArtifactAvailability {
  return {
    status: "unavailable",
    display_text: "Отдельный рабочий медиаплан XLSX пока недоступен.",
    artifact: null,
  };
}

function createReport(status: JobResultViewV1["report"]["status"]): JobResultViewV1["report"] {
  if (status !== "ready") {
    return {
      status,
      display_text: status === "failed" ? "Отчет не сформирован." : "Отчет пока недоступен.",
      generated_at_utc: null,
      artifact: null,
      sheets: [],
      working_media_plan: unavailableWorkingPlan(),
    };
  }
  return {
    status: "ready",
    display_text: "Excel-отчет готов.",
    generated_at_utc: "2026-07-16T12:30:00Z",
    artifact: {
      artifact_id: REPORT_ARTIFACT_ID,
      display_name: "mmm_campaign_result.xlsx",
      media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      size_bytes: 248_320,
      sha256: "b".repeat(64),
      download_path: `/api/v1/artifacts/${REPORT_ARTIFACT_ID}/download`,
    },
    sheets: [
      {
        sheet_name: "Summary",
        title: "Краткий итог",
        description: "Рекомендация, эффект и ключевые ограничения.",
      },
      {
        sheet_name: "Scenarios",
        title: "Сценарии",
        description: "Сравнение шести рассчитанных вариантов.",
      },
      {
        sheet_name: "Media plan",
        title: "Медиаплан",
        description: "Распределение бюджета по географиям и каналам.",
      },
    ],
    working_media_plan: unavailableWorkingPlan(),
  };
}

export function createJobResultViewFixture(
  options: JobResultFixtureOptions = {},
): JobResultViewV1 {
  const recommendationStatus = options.recommendationStatus ?? "recommended";
  const recommendedScenarioId =
    recommendationStatus === "recommended" ? (options.recommendedScenarioId ?? "S06") : null;
  const unavailableIds = new Set(options.unavailableScenarioIds ?? []);
  const scenarios = SCENARIO_SEEDS.map((seed) =>
    createScenario(seed, recommendedScenarioId, unavailableIds.has(seed.scenarioId)),
  ) as JobResultViewV1["scenarios"];
  const selectedScenarioId = recommendedScenarioId ?? "S01";
  const selectedScenario = scenarios.find((scenario) => scenario.scenario_id === selectedScenarioId) ?? scenarios[0];
  const selectedMetrics = selectedScenario.metrics;
  const comparisons = createOverviewComparisons(selectedScenario);
  const hasBestSafe = recommendationStatus === "recommended" && recommendedScenarioId === "S06";
  const bestRawAvailable = options.bestRawAvailable ?? false;
  const modelCoverageShare = options.modelCoverageShare ?? 0.92;

  if (recommendationStatus !== "recommended") {
    for (const scenario of scenarios) {
      scenario.is_recommended = false;
      scenario.is_best_safe = false;
    }
  }
  if (bestRawAvailable && recommendationStatus !== "recommended") {
    const adaptive = scenarios[5];
    adaptive.is_best_raw = true;
    adaptive.raw_rank = 1;
    adaptive.safe_rank = null;
  }
  if (bestRawAvailable && recommendationStatus === "recommended" && recommendedScenarioId === "S06") {
    const publishedRawRanks = [7, 6, 5, 4, 3, 2] as const;
    scenarios.forEach((scenario, index) => {
      if (scenario.status === "completed") scenario.raw_rank = publishedRawRanks[index];
    });
  }

  return {
    contract_name: "job_result_view_v1",
    schema_version: "1.0.0",
    record_origin: "sanitized_fixture",
    job_id: JOB_ID,
    result_id: RESULT_ID,
    source_overview_id: SOURCE_OVERVIEW_ID,
    updated_at_utc: "2026-07-16T12:30:00Z",
    campaign: {
      campaign_id: CAMPAIGN_ID,
      campaign_name: "Демонстрационная кампания — летнее продвижение",
      segments: ["Супермаркеты", "Гипермаркеты"],
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      total_budget_rub: TOTAL_BUDGET_RUB,
      channels_n: 2,
      geographies_n: 2,
      model_coverage_share: modelCoverageShare,
    },
    recommendation: {
      status: recommendationStatus,
      scenario_id: recommendedScenarioId,
      title:
        recommendationStatus === "recommended"
          ? "Рекомендуемое распределение бюджета"
          : recommendationStatus === "no_safe_recommendation"
            ? "Автоматическая рекомендация недоступна"
            : "Рекомендация недоступна",
      display_text:
        recommendationStatus === "recommended"
          ? "Использовать распределение с подтвержденным содержательным улучшением."
          : recommendationStatus === "no_safe_recommendation"
            ? "Автоматическое перераспределение не предложено. Исходный план остается точкой отсчета для ручного решения."
            : "Рекомендация недоступна, потому что расчет не завершен.",
      decision_scope_text:
        "Рекомендация относится к распределению бюджета, а не к решению о запуске кампании.",
      safe_rank: recommendedScenarioId ? selectedScenario.safe_rank : null,
      raw_rank: recommendedScenarioId ? selectedScenario.raw_rank : null,
      best_safe: {
        available: hasBestSafe,
        scenario_id: hasBestSafe ? "S06" : null,
        safe_rank: hasBestSafe ? selectedScenario.safe_rank : null,
        raw_rank: hasBestSafe ? selectedScenario.raw_rank : null,
        display_text: hasBestSafe
          ? "Лучший вариант, прошедший проверки для автоматического перераспределения."
          : "Отдельный лучший безопасный вариант не опубликован.",
      },
    },
    overview: {
      selected_scenario_id: selectedScenarioId,
      source_scenario_id: "S01",
      benchmark_scenario_id: "S05",
      headline_metrics: [
        quantileHeadline(
          "incremental_turnover_rub",
          "Дополнительный оборот",
          selectedMetrics.incremental_turnover_rub,
          "RUB",
        ),
        quantileHeadline(
          "incremental_orders",
          "Дополнительные заказы",
          selectedMetrics.incremental_orders,
          "orders",
        ),
        quantileHeadline(
          "orders_per_100k_rub",
          "Заказы на 100 000 рублей",
          selectedMetrics.orders_per_100k_rub,
          "orders_per_100k_RUB",
        ),
        quantileHeadline(
          "avg_basket_delta_rub",
          "Изменение среднего чека",
          selectedMetrics.avg_basket_delta_rub,
          "RUB_per_order",
        ),
        {
          metric_id: "total_budget_rub",
          title: "Бюджет сценария",
          status: "available",
          unit: "RUB",
          p10: null,
          p50: null,
          p90: null,
          value: selectedScenario.budget.allocated_budget_rub,
          display_text: "Бюджет, распределенный в выбранном для показа сценарии.",
        },
        {
          metric_id: "reliability_score",
          title: "Оценка надежности",
          status: "unavailable",
          unit: "score_1_10",
          p10: null,
          p50: null,
          p90: null,
          value: null,
          display_text: "Единая шкала надежности пока не утверждена.",
        },
        {
          metric_id: "safe_rank",
          title: "Место среди проверенных вариантов",
          status: selectedScenario.safe_rank === null ? "unavailable" : "available",
          unit: "rank",
          p10: null,
          p50: null,
          p90: null,
          value: selectedScenario.safe_rank,
          display_text: "Порядок среди проверенных распределений с учетом ограничений.",
        },
      ],
      scenario_range: {
        metric_id: "incremental_turnover_rub",
        unit: "RUB",
        rows: scenarios
          .filter((scenario) => scenario.metrics.incremental_turnover_rub.status === "available")
          .map((scenario) => ({
            scenario_id: scenario.scenario_id,
            p10: scenario.metrics.incremental_turnover_rub.p10 as number,
            p50: scenario.metrics.incremental_turnover_rub.p50 as number,
            p90: scenario.metrics.incremental_turnover_rub.p90 as number,
            quality_status: scenario.quality_status,
          })) as JobResultViewV1["overview"]["scenario_range"]["rows"],
      },
      ...comparisons,
    },
    scenarios,
    reliability: selectedScenario.reliability,
    warnings: [
      ...(modelCoverageShare < 1
        ? [
            {
              code: "partial_model_coverage",
              severity: "manual_review" as const,
              title: "Рассчитана только часть бюджета",
              display_text: `Модель покрывает ${(modelCoverageShare * 100).toFixed(0)}% загруженного бюджета. Непокрытая часть не считается нулевым эффектом.`,
              recommended_action: "Отдельно проверьте каналы и бюджет, которые не вошли в расчет.",
              scope: "campaign" as const,
            },
          ]
        : []),
      ...(recommendationStatus === "no_safe_recommendation"
        ? [
            {
              code: "automatic_reallocation_unavailable",
              severity: "manual_review" as const,
              title: "Автоматическое перераспределение не предложено",
              display_text: "Расчет не подтвердил вариант для автоматического перераспределения бюджета.",
              recommended_action: "Используйте исходный план как точку отсчета и принимайте изменение вручную.",
              scope: "recommendation" as const,
            },
          ]
        : []),
      {
        code: "campaign_launch_threshold_unavailable",
        severity: "info",
        title: "Решение о запуске остается за бизнесом",
        display_text: "Утвержденный порог для решения о запуске или отмене кампании не настроен.",
        recommended_action: "Используйте результат только для сравнения и распределения бюджета.",
        scope: "campaign",
      },
    ],
    best_raw: bestRawAvailable
      ? {
          available: true,
          scenario_id: "S06",
          raw_rank: 1,
          safe_rank: null,
          reason_not_recommended:
            "Вариант показан для сравнения, но не прошел все проверки для автоматической рекомендации.",
          metrics: {
            incremental_turnover_rub: availableMetric("RUB", 23_100_000, 4_800_000, "audit_only"),
            roas: availableMetric("ratio", 2.01, 0.35, "audit_only"),
          },
          blocking_cells_status: "available",
          blocking_cells: [
            {
              segment: "Супермаркеты",
              geo: "Москва",
              channel: "Онлайн-видео",
              reason: "Связка не прошла проверку для автоматического увеличения бюджета.",
            },
          ],
        }
      : {
          available: false,
          scenario_id: null,
          raw_rank: null,
          safe_rank: null,
          reason_not_recommended: null,
          metrics: null,
          blocking_cells_status: "not_applicable",
          blocking_cells: [],
        },
    media_plan: {
      endpoint: `/api/v1/jobs/${JOB_ID}/media-plan`,
      selected_scenario_id: selectedScenarioId,
      grain: "geo_channel_total",
      scenario_options: scenarios.map((scenario) => ({
        scenario_id: scenario.scenario_id,
        title: scenario.title,
        status: scenario.status,
      })) as JobResultViewV1["media_plan"]["scenario_options"],
      daily_plan: {
        status: "unavailable",
        display_text: "Дневная разбивка сценариев не публикуется текущими результатами.",
      },
      map: {
        status: "unavailable",
        display_text: "Данные для карты пока недоступны.",
        geo_points: null,
        coordinate_catalog_version: null,
      },
      working_media_plan: unavailableWorkingPlan(),
    },
    report: createReport(options.reportStatus ?? "ready"),
    limitations: [
      {
        code: "incremental_effect_only",
        display_text: "Результат показывает дополнительный эффект кампании, а не полный прогноз оборота.",
      },
      {
        code: "turnover_roas_not_profit",
        display_text: "ROAS рассчитан по дополнительному обороту и не является оценкой прибыли.",
      },
      {
        code: "daily_plan_unavailable",
        display_text: "Медиаплан доступен без дневной разбивки.",
      },
    ],
  };
}

export function createRecommendedJobResultFixture(): JobResultViewV1 {
  return createJobResultViewFixture();
}

export function createNoSafeJobResultFixture(): JobResultViewV1 {
  return createJobResultViewFixture({
    recommendationStatus: "no_safe_recommendation",
    bestRawAvailable: true,
  });
}

export function createBestRawJobResultFixture(): JobResultViewV1 {
  return createJobResultViewFixture({ bestRawAvailable: true });
}

export function createUnavailableJobResultFixture(): JobResultViewV1 {
  return createJobResultViewFixture({
    recommendationStatus: "unavailable",
    unavailableScenarioIds: ["S06"],
    reportStatus: "unavailable",
  });
}

export function createPartialCoverageJobResultFixture(): JobResultViewV1 {
  return createJobResultViewFixture({ modelCoverageShare: 0.64 });
}

export function createReportReadyJobResultFixture(): JobResultViewV1 {
  return createJobResultViewFixture({ reportStatus: "ready" });
}

export function createReportFailedJobResultFixture(): JobResultViewV1 {
  return createJobResultViewFixture({ reportStatus: "failed" });
}

export function createReportUnavailableJobResultFixture(): JobResultViewV1 {
  return createJobResultViewFixture({ reportStatus: "unavailable" });
}

function aggregateValues(
  source: number,
  selected: number,
): Omit<ChannelAggregate, "channel"> {
  return {
    source_budget_rub: source,
    selected_budget_rub: selected,
    delta_rub: selected - source,
    delta_pct: deltaPct(source, selected),
    quality_status: "safe",
    quality_display_text: "Строка прошла опубликованные проверки качества.",
  };
}

function createPlanRows(
  scenarioId: ScenarioId,
  campaignId: string,
  selected: number,
  sourceTotal: number,
): MediaPlanRow[] {
  const [firstShare] = selectedShares(scenarioId);
  const first = selected * firstShare;
  const second = selected - first;
  const sourceScale = sourceTotal / TOTAL_BUDGET_RUB;
  const seeds = [
    ["Супермаркеты", "Москва", "Онлайн-видео", 4_000_000 * sourceScale, first * (4 / 7)],
    ["Супермаркеты", "Москва", "Наружная реклама", 3_000_000 * sourceScale, first * (3 / 7)],
    ["Супермаркеты", "Санкт-Петербург", "Онлайн-видео", 3_000_000 * sourceScale, second * 0.6],
    ["Супермаркеты", "Санкт-Петербург", "Наружная реклама", 2_000_000 * sourceScale, second * 0.4],
  ] as const;
  return seeds
    .map(([segment, geo, channel, source, selectedBudget]) => ({
      scenario_id: scenarioId,
      campaign_id: campaignId,
      segment,
      geo,
      channel,
      date: null,
      source_budget_rub: source,
      selected_budget_rub: selectedBudget,
      delta_rub: selectedBudget - source,
      delta_pct: deltaPct(source, selectedBudget),
      source_budget_share: sourceTotal === 0 ? 0 : source / sourceTotal,
      selected_budget_share: selected === 0 ? 0 : selectedBudget / selected,
      quality_status: "safe" as const,
      quality_display_text: "Строка прошла опубликованные проверки качества.",
    }))
    .sort((left, right) =>
      [left.segment, left.geo, left.channel].join("|").localeCompare(
        [right.segment, right.geo, right.channel].join("|"),
        "ru",
      ),
    );
}

export function createScenarioMediaPlanFixture(
  options: ScenarioMediaPlanFixtureOptions = {},
): ScenarioMediaPlanV1 {
  const resultView = options.resultView ?? createJobResultViewFixture();
  const scenarioId = options.scenarioId ?? "S06";
  const resultScenario = resultView.scenarios.find((scenario) => scenario.scenario_id === scenarioId);
  if (!resultScenario || resultScenario.status !== "completed") {
    throw new Error(`Cannot create a media-plan fixture for unavailable scenario ${scenarioId}`);
  }
  const sourceTotal = resultView.scenarios[0].budget.allocated_budget_rub;
  const selected = resultScenario.budget.allocated_budget_rub;
  const allRows = createPlanRows(
    scenarioId,
    resultView.campaign.campaign_id,
    selected,
    sourceTotal,
  );
  const filteredRows = allRows.filter(
    (row) =>
      (options.channel == null || row.channel === options.channel) &&
      (options.geo == null || row.geo === options.geo),
  );
  const page = options.page ?? 1;
  const pageSize = options.pageSize ?? 100;
  const pageRows = filteredRows.slice((page - 1) * pageSize, page * pageSize);
  const [firstShare] = selectedShares(scenarioId);
  const first = selected * firstShare;
  const second = selected - first;
  const filteredSource = filteredRows.reduce((total, row) => total + row.source_budget_rub, 0);
  const filteredSelected = filteredRows.reduce((total, row) => total + row.selected_budget_rub, 0);
  const byGeoChannel = allRows.map((row) =>
    ({
      geo: row.geo,
      channel: row.channel,
      ...aggregateValues(row.source_budget_rub, row.selected_budget_rub),
    }),
  ) as [GeoChannelAggregate, ...GeoChannelAggregate[]];

  return {
    contract_name: "scenario_media_plan_v1",
    schema_version: "1.0.0",
    record_origin: resultView.record_origin,
    job_id: resultView.job_id,
    result_id: resultView.result_id,
    campaign_id: resultView.campaign.campaign_id,
    scenario: {
      scenario_id: scenarioId,
      title: resultScenario.title,
      status: "completed",
      is_selected: resultScenario.is_recommended,
      safe_rank: resultScenario.safe_rank,
      raw_rank: resultScenario.raw_rank,
      quality_status: resultScenario.quality_status,
      quality_display_text: resultScenario.quality_display_text,
    },
    source_artifact: {
      artifact_id: SOURCE_ARTIFACT_ID,
      kind: "recommended_allocations_csv",
      sha256: "a".repeat(64),
    },
    grain: "geo_channel_total",
    filters: {
      channel: options.channel ?? null,
      geo: options.geo ?? null,
      date: null,
    },
    pagination: {
      page,
      page_size: pageSize,
      total_rows: filteredRows.length,
      total_pages: filteredRows.length === 0 ? 0 : Math.ceil(filteredRows.length / pageSize),
    },
    totals: {
      requested_budget_rub: resultScenario.budget.requested_budget_rub,
      source_budget_rub: sourceTotal,
      selected_budget_rub: selected,
      unallocated_budget_rub: resultScenario.budget.unallocated_budget_rub,
      delta_rub: selected - sourceTotal,
      reconciliation_status: "reconciled",
    },
    filtered_totals: {
      source_budget_rub: filteredSource,
      selected_budget_rub: filteredSelected,
      delta_rub: filteredSelected - filteredSource,
    },
    rows: pageRows,
    aggregates: {
      by_channel: [
        { channel: "Онлайн-видео", ...aggregateValues(sourceTotal * (7 / 12), first) },
        { channel: "Наружная реклама", ...aggregateValues(sourceTotal * (5 / 12), second) },
      ],
      by_geo: [
        { geo: "Москва", ...aggregateValues(sourceTotal * (7 / 12), first) },
        { geo: "Санкт-Петербург", ...aggregateValues(sourceTotal * (5 / 12), second) },
      ],
      by_geo_channel: byGeoChannel,
      by_date: {
        status: "unavailable",
        display_text: "Дневная разбивка не опубликована.",
        rows: null,
      },
      channel_date_matrix: {
        status: "unavailable",
        display_text: "Матрица канал × дата недоступна без дневной разбивки.",
        rows: null,
      },
      geo_channel_matrix: {
        status: "ready",
        display_text: "Матрица география × канал готова.",
        rows: byGeoChannel,
      },
    },
    map: {
      status: "unavailable",
      display_text: "Данные для карты пока недоступны.",
      geo_points: null,
      coordinate_catalog_version: null,
    },
    working_media_plan: {
      status: "unavailable",
      display_text: "Отдельный рабочий медиаплан XLSX пока недоступен.",
      artifact: null,
    },
    limitations: [
      {
        code: "daily_plan_unavailable",
        display_text: "Медиаплан опубликован без дневной разбивки.",
      },
    ],
    updated_at_utc: "2026-07-16T12:30:00Z",
  };
}
