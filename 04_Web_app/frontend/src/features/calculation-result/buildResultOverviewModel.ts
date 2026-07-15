import type {
  AllocationLine,
  OverviewArtifact,
  OverviewCampaign,
  OverviewScenario,
  QuantileMetric,
  ResultOverviewV1,
} from "../../entities/result-overview/types";
import {
  getAllocationActionCopy,
  getGateReasonCopy,
  getQualityCopy,
  getScenarioCopy,
  getStatusCopy,
  getWarningCopy,
  getWarningSeverityCopy,
  type ResultCopyTone,
  type ResultStatusCopy,
} from "./resultCopy";

export interface MetricViewModel {
  id: "turnover" | "roas" | "orders" | "basket-bridge";
  title: string;
  unit: string | null;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  note: string;
  available: boolean;
  tone?: "default" | "warning";
}

export interface ScenarioViewModel {
  id: string;
  number: string;
  title: string;
  description: string;
  badge: string | null;
  available: boolean;
  recommended: boolean;
  stableBenchmark: boolean;
  turnover: QuantileMetric | null;
  roas: QuantileMetric | null;
  orders: QuantileMetric | null;
  basketBridge: QuantileMetric | null;
  budget: {
    requestedRub: number;
    allocatedRub: number;
    unallocatedRub: number;
  };
  calculation: ResultStatusCopy;
  supportStatus: ResultStatusCopy;
  optimizer: ResultStatusCopy;
  quality: ResultStatusCopy;
  coverageShare: number | null;
  uncertaintyWidthShare: number | null;
  support: {
    elevated: number;
    strong: number;
    hard: number;
    policyViolations: number;
  };
}

export interface WarningViewModel {
  id: string;
  title: string;
  meaning: string;
  action: string;
  severityLabel: string;
  tone: ResultCopyTone;
}

export interface AllocationViewModel {
  id: string;
  segment: string;
  geo: string;
  channel: string;
  uploadedBudgetRub: number;
  recommendedBudgetRub: number;
  deltaBudgetRub: number;
  uploadedBudgetShare: number;
  recommendedBudgetShare: number;
  action: ResultStatusCopy;
  restriction: {
    label: string;
    meaning: string;
    action: string;
    tone: ResultCopyTone;
  } | null;
}

export interface DownloadViewModel {
  kind: "report" | "media-plan";
  title: string;
  description: string;
  sizeBytes: number;
  downloadPath: string;
}

export interface ResultOverviewViewModel {
  demoData: boolean;
  campaign: {
    name: string;
    segment: string;
    sourceStartDate: string;
    sourceEndDate: string;
    budgetRub: number;
    channelsCount: number;
    geographiesCount: number;
  };
  coverage: {
    partial: boolean;
    status: ResultStatusCopy;
    uploadedBudgetRub: number;
    modelInputBudgetRub: number;
    calculatedBudgetRub: number;
    unmodeledBudgetRub: number;
    unallocatedBudgetRub: number;
    modelCoverageShare: number;
  };
  recommendation: {
    title: string;
    reason: string;
    scenarioId: string;
    scenarioName: string;
    type: ResultStatusCopy;
    plan: ResultStatusCopy;
    quality: ResultStatusCopy;
    optimizerAvailable: boolean;
    movedBudgetRub: number;
    deltaTurnoverP50Rub: number | null;
    deltaTurnoverP50Share: number | null;
    allocationOnlyNotice: string;
  };
  recommendedScenario: ScenarioViewModel;
  benchmarkScenario: ScenarioViewModel;
  metrics: MetricViewModel[];
  statuses: Array<{ id: string; title: string; copy: ResultStatusCopy }>;
  scenarios: ScenarioViewModel[];
  search: {
    status: ResultStatusCopy;
    attemptsEvaluated: number;
    candidatesScored: number;
    candidatesRejected: number;
    finalists: number;
    rawDiffersFromSafe: boolean;
    bestRaw: {
      available: boolean;
      eligible: boolean;
      turnover: QuantileMetric | null;
      roas: QuantileMetric | null;
    };
    bestSafe: {
      available: boolean;
      eligible: boolean;
      turnover: QuantileMetric | null;
      roas: QuantileMetric | null;
    };
  };
  s6: {
    available: boolean;
    message: string;
  };
  warnings: WarningViewModel[];
  allocations: AllocationViewModel[];
  downloads: DownloadViewModel[];
}

export class ResultPresentationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ResultPresentationError";
  }
}

function requireScenario(
  campaign: OverviewCampaign,
  scenarioId: string,
): OverviewScenario {
  const scenario = campaign.scenarios.find(
    (candidate) => candidate.scenario_id === scenarioId,
  );
  if (!scenario) {
    throw new ResultPresentationError(
      "В обзоре отсутствует один из обязательных сценариев.",
    );
  }
  return scenario;
}

function scenarioToViewModel(
  scenario: OverviewScenario,
  recommendedId: string,
): ScenarioViewModel {
  const copy = getScenarioCopy(scenario.scenario_id, scenario.available);
  return {
    id: scenario.scenario_id,
    number: copy.number,
    title: copy.title,
    description: copy.description,
    badge: copy.badge,
    available: scenario.available,
    recommended: scenario.scenario_id === recommendedId,
    stableBenchmark: scenario.scenario_id === "S05",
    turnover: scenario.metrics.incremental_turnover,
    roas: scenario.metrics.turnover_roas,
    orders: scenario.metrics.incremental_orders,
    basketBridge: scenario.metrics.avg_basket_turnover_bridge,
    budget: {
      requestedRub: scenario.budget.requested_budget_rub,
      allocatedRub: scenario.budget.allocated_budget_rub,
      unallocatedRub: scenario.budget.unallocated_budget_rub,
    },
    calculation: getStatusCopy("calculation", scenario.calculation_status.code),
    supportStatus: getStatusCopy("cellSupport", scenario.cell_support_status.code),
    optimizer: getStatusCopy("optimizer", scenario.optimizer_status.code),
    quality: getQualityCopy(scenario.quality.status.code),
    coverageShare: scenario.quality.coverage_share,
    uncertaintyWidthShare: scenario.quality.uncertainty_width_share,
    support: {
      elevated: scenario.support.elevated_warnings,
      strong: scenario.support.strong_warnings,
      hard: scenario.support.hard_warnings,
      policyViolations: scenario.support.policy_violations,
    },
  };
}

function metricViewModel(
  id: MetricViewModel["id"],
  title: string,
  metric: QuantileMetric | null,
  note: string,
  tone?: MetricViewModel["tone"],
): MetricViewModel {
  return {
    id,
    title,
    unit: metric?.unit === "RUB" || metric?.unit === "turnover_bridge_from_avg_basket_rub"
      ? "RUB"
      : null,
    p10: metric?.p10 ?? null,
    p50: metric?.p50 ?? null,
    p90: metric?.p90 ?? null,
    note,
    available: metric !== null,
    ...(tone ? { tone } : {}),
  };
}

function allocationToViewModel(
  line: AllocationLine,
  index: number,
): AllocationViewModel {
  const firstGateReason = line.gate_reason_codes[0];
  const restriction = firstGateReason ? getGateReasonCopy(firstGateReason) : null;
  return {
    id: `${index}:${line.segment}:${line.geo}:${line.channel}`,
    segment: line.segment,
    geo: line.geo,
    channel: line.channel,
    uploadedBudgetRub: line.uploaded_budget_rub,
    recommendedBudgetRub: line.recommended_budget_rub,
    deltaBudgetRub: line.delta_budget_rub,
    uploadedBudgetShare: line.uploaded_budget_share,
    recommendedBudgetShare: line.recommended_budget_share,
    action: getAllocationActionCopy(line.action),
    restriction: restriction
      ? {
          label: restriction.label,
          meaning: restriction.meaning,
          action: restriction.action,
          tone: restriction.tone,
        }
      : null,
  };
}

function downloadFromArtifact(
  artifact: OverviewArtifact | undefined,
  kind: DownloadViewModel["kind"],
): DownloadViewModel | null {
  if (!artifact) return null;
  return {
    kind,
    title: kind === "report" ? "Отчет для маркетолога" : "Рекомендованный медиаплан",
    description: kind === "report"
      ? "Excel-файл с результатами расчета и пояснениями."
      : "CSV-файл с рекомендованным распределением бюджета.",
    sizeBytes: artifact.size_bytes,
    downloadPath: artifact.download_path,
  };
}

export function buildResultOverviewModel(
  result: ResultOverviewV1,
  campaign: OverviewCampaign,
): ResultOverviewViewModel {
  const recommendedSource = requireScenario(
    campaign,
    campaign.recommendation.scenario_id,
  );
  const benchmarkSource = requireScenario(campaign, "S05");
  const s6Source = requireScenario(campaign, "S06");
  const scenarios = campaign.scenarios.map((scenario) =>
    scenarioToViewModel(scenario, campaign.recommendation.scenario_id),
  );
  const recommendedScenario = scenarioToViewModel(
    recommendedSource,
    campaign.recommendation.scenario_id,
  );
  const benchmarkScenario = scenarioToViewModel(
    benchmarkSource,
    campaign.recommendation.scenario_id,
  );
  const recommendationType = getStatusCopy(
    "recommendationType",
    campaign.recommendation.recommendation_type.code,
  );
  const plan = getStatusCopy("plan", campaign.recommendation.plan_status.code);
  const quality = getQualityCopy(campaign.quality.status.code);
  const calculation = getStatusCopy(
    "calculation",
    campaign.statuses.calculation_status.code,
  );
  const warnings = [...campaign.warnings, ...result.warnings].map(
    (warning, index): WarningViewModel => {
      const copy = getWarningCopy(warning.code);
      const severity = getWarningSeverityCopy(warning.severity);
      return {
        id: `${index}:${warning.code}`,
        title: copy.title,
        meaning: copy.meaning,
        action: copy.action,
        severityLabel: severity.label,
        tone: copy.tone === "neutral" ? severity.tone : copy.tone,
      };
    },
  );
  const reportDownload = downloadFromArtifact(
    result.artifacts.find((artifact) => artifact.kind === "marketer_report_xlsx"),
    "report",
  );
  const planDownload = downloadFromArtifact(
    result.artifacts.find((artifact) => artifact.kind === "best_plan_csv"),
    "media-plan",
  );
  const metrics = campaign.recommendation.metrics;
  const partial =
    campaign.statuses.calculation_status.code === "partially_calculated" ||
    campaign.budget.model_coverage_share < 1 ||
    campaign.budget.unmodeled_budget_rub > 0 ||
    campaign.budget.unallocated_budget_rub > 0;

  return {
    demoData: result.result_origin === "sanitized_fixture",
    campaign: {
      name: campaign.passport.campaign_name,
      segment: campaign.passport.segments.join(", ") || "Нет данных",
      sourceStartDate: campaign.passport.source_start_date,
      sourceEndDate: campaign.passport.source_end_date,
      budgetRub: campaign.budget.uploaded_budget_rub,
      channelsCount: campaign.passport.source_channels.length,
      geographiesCount: campaign.passport.geographies.length,
    },
    coverage: {
      partial,
      status: calculation,
      uploadedBudgetRub: campaign.budget.uploaded_budget_rub,
      modelInputBudgetRub: campaign.budget.model_input_budget_rub,
      calculatedBudgetRub: campaign.budget.calculated_budget_rub,
      unmodeledBudgetRub: campaign.budget.unmodeled_budget_rub,
      unallocatedBudgetRub: campaign.budget.unallocated_budget_rub,
      modelCoverageShare: campaign.budget.model_coverage_share,
    },
    recommendation: {
      title: recommendationType.label,
      reason: recommendationType.description,
      scenarioId: campaign.recommendation.scenario_id,
      scenarioName: recommendedScenario.title,
      type: recommendationType,
      plan,
      quality,
      optimizerAvailable: campaign.recommendation.optimizer_available,
      movedBudgetRub: campaign.recommendation.versus_uploaded_plan.moved_budget_rub,
      deltaTurnoverP50Rub:
        campaign.recommendation.versus_uploaded_plan.delta_incremental_turnover_p50_rub,
      deltaTurnoverP50Share:
        campaign.recommendation.versus_uploaded_plan.delta_incremental_turnover_p50_share,
      allocationOnlyNotice:
        "Рекомендация относится только к распределению бюджета и не является решением запускать или отменять кампанию.",
    },
    recommendedScenario,
    benchmarkScenario,
    metrics: [
      metricViewModel(
        "turnover",
        "Дополнительный оборот",
        metrics.incremental_turnover,
        "Готовый диапазон результата из сервиса расчета.",
      ),
      metricViewModel(
        "roas",
        "ROAS по обороту",
        metrics.turnover_roas,
        "Отношение дополнительного оборота к бюджету.",
      ),
      metricViewModel(
        "orders",
        "Дополнительные заказы",
        metrics.incremental_orders,
        "Диагностическая оценка без нормализации на 100 000 пользователей.",
        "warning",
      ),
      metricViewModel(
        "basket-bridge",
        "Вклад среднего чека в оборот",
        metrics.avg_basket_turnover_bridge,
        "Это вклад в дополнительный оборот, а не изменение среднего чека.",
      ),
    ],
    statuses: [
      { id: "calculation", title: "Расчет", copy: calculation },
      {
        id: "campaign-scale",
        title: "Масштаб кампании",
        copy: getStatusCopy("campaignScale", campaign.statuses.campaign_scale_status.code),
      },
      {
        id: "cell-support",
        title: "Надежность связок",
        copy: getStatusCopy("cellSupport", campaign.statuses.cell_support_status.code),
      },
      {
        id: "optimizer",
        title: "Автоматическое распределение",
        copy: getStatusCopy("optimizer", campaign.statuses.optimizer_status.code),
      },
      {
        id: "business-decision",
        title: "Бизнес-решение",
        copy: getStatusCopy("businessDecision", campaign.statuses.business_decision_status.code),
      },
    ],
    scenarios,
    search: {
      status: getStatusCopy("scenario6Run", campaign.scenario6.audit.run_status.code),
      attemptsEvaluated: campaign.scenario6.audit.attempts_evaluated,
      candidatesScored: campaign.scenario6.audit.candidates_scored,
      candidatesRejected: campaign.scenario6.audit.candidates_rejected,
      finalists: campaign.scenario6.audit.finalists,
      rawDiffersFromSafe: campaign.scenario6.raw_differs_from_safe,
      bestRaw: {
        available: campaign.scenario6.best_raw !== null,
        eligible:
          campaign.scenario6.best_raw?.eligible_for_automatic_recommendation ?? false,
        turnover: campaign.scenario6.best_raw?.incremental_turnover ?? null,
        roas: campaign.scenario6.best_raw?.turnover_roas ?? null,
      },
      bestSafe: {
        available: campaign.scenario6.best_safe !== null,
        eligible:
          campaign.scenario6.best_safe?.eligible_for_automatic_recommendation ?? false,
        turnover: campaign.scenario6.best_safe?.incremental_turnover ?? null,
        roas: campaign.scenario6.best_safe?.turnover_roas ?? null,
      },
    },
    s6: {
      available: s6Source.available,
      message: getScenarioCopy("S06", s6Source.available).description,
    },
    warnings,
    allocations: campaign.allocation_comparison.map(allocationToViewModel),
    downloads: [reportDownload, planDownload].filter(
      (download): download is DownloadViewModel => download !== null,
    ),
  };
}
