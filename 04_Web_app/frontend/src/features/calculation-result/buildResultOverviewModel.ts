import type {
  CampaignResult,
  DecisionResultV1,
  ScenarioResult,
} from "../../entities/decision-result/types";

export interface MetricViewModel {
  id: "turnover" | "roas" | "orders-per-100k" | "basket-delta";
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
  name: string;
  description: string;
  available: boolean;
  turnover: { unit: string; p10: number; p50: number; p90: number } | null;
  roasP50: number | null;
  quality: string;
  explanation: string;
}

export interface ResultOverviewViewModel {
  demoData: boolean;
  campaign: {
    id: string;
    name: string;
    segment: string;
    dateRange: string;
    budgetRub: number;
    channelsCount: number;
    geographiesCount: number;
  };
  recommendation: {
    title: string;
    scenarioName: string;
    reason: string;
    planStatus: string;
    qualityStatus: string;
    reliability: null;
    allocationOnlyNotice: string;
  };
  recommendedScenario: ScenarioViewModel;
  benchmarkScenario: ScenarioViewModel;
  metrics: MetricViewModel[];
  search: {
    status: string;
    attemptsEvaluated: number;
    candidatesScored: number;
    candidatesRejected: number;
    finalists: number;
    explanation: string;
  };
  s6: {
    available: boolean;
    explanation: string;
  };
  caveats: string[];
}

export class ResultPresentationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ResultPresentationError";
  }
}

function scenarioToViewModel(scenario: ScenarioResult): ScenarioViewModel {
  const metrics = scenario.metrics;
  return {
    id: scenario.scenario_id,
    name: scenario.name,
    description: scenario.description,
    available: scenario.available,
    turnover: metrics?.incremental_turnover ?? null,
    roasP50: metrics?.roas_p50 ?? null,
    quality: scenario.quality.status.display_text,
    explanation: scenario.quality.explanation,
  };
}

function requireScenario(
  campaign: CampaignResult,
  scenarioId: string,
): ScenarioResult {
  const scenario = campaign.scenarios.find(
    (candidate) => candidate.scenario_id === scenarioId,
  );
  if (!scenario) {
    throw new ResultPresentationError(
      `В результате отсутствует рекомендованный сценарий ${scenarioId}.`,
    );
  }
  return scenario;
}

function buildMetrics(campaign: CampaignResult): MetricViewModel[] {
  const recommendationMetrics = campaign.recommendation.metrics;
  const turnover = recommendationMetrics.incremental_turnover;

  return [
    {
      id: "turnover",
      title: "Дополнительный оборот",
      unit: turnover?.unit ?? "RUB",
      p10: turnover?.p10 ?? null,
      p50: turnover?.p50 ?? null,
      p90: turnover?.p90 ?? null,
      note: "Contract-backed incremental effect",
      available: turnover !== null,
    },
    {
      id: "roas",
      title: "ROAS по обороту",
      unit: null,
      p10: null,
      p50: recommendationMetrics.roas_p50,
      p90: null,
      note: "В contract доступен только p50",
      available: recommendationMetrics.roas_p50 !== null,
    },
    {
      id: "orders-per-100k",
      title: "Заказы на 100 000 пользователей",
      unit: null,
      p10: null,
      p50: null,
      p90: null,
      note: "Нет denominator в текущем contract",
      available: false,
      tone: "warning",
    },
    {
      id: "basket-delta",
      title: "Изменение среднего чека",
      unit: null,
      p10: null,
      p50: null,
      p90: null,
      note: "avg_basket_bridge не является basket delta",
      available: false,
    },
  ];
}

export function buildResultOverviewModel(
  result: DecisionResultV1,
  campaign: CampaignResult,
): ResultOverviewViewModel {
  const recommended = requireScenario(
    campaign,
    campaign.recommendation.scenario_id,
  );
  const benchmarkId = recommended.scenario_id === "S05" ? "S01" : "S05";
  const benchmark = requireScenario(campaign, benchmarkId);
  const s6 = requireScenario(campaign, "S06");

  const caveats = [...campaign.warnings, ...result.warnings]
    .map((warning) => warning.display_text)
    .slice(0, 4);

  return {
    demoData: result.result_origin === "sanitized_fixture",
    campaign: {
      id: campaign.campaign_id,
      name: campaign.passport.campaign_name,
      segment: campaign.passport.segments.join(", ") || "Нет данных",
      dateRange: `${campaign.passport.source_start_date} — ${campaign.passport.source_end_date}`,
      budgetRub: campaign.budget.uploaded_budget_rub,
      channelsCount: campaign.passport.source_channels.length,
      geographiesCount: campaign.passport.geographies.length,
    },
    recommendation: {
      title: campaign.recommendation.recommendation_type.display_text,
      scenarioName: campaign.recommendation.scenario_name,
      reason: campaign.recommendation.reason,
      planStatus: campaign.recommendation.plan_status.display_text,
      qualityStatus: campaign.quality.status.display_text,
      reliability: null,
      allocationOnlyNotice:
        "Рекомендация относится к распределению бюджета и не является решением запускать или отменять кампанию.",
    },
    recommendedScenario: scenarioToViewModel(recommended),
    benchmarkScenario: scenarioToViewModel(benchmark),
    metrics: buildMetrics(campaign),
    search: {
      status: campaign.scenario6.run_status.display_text,
      attemptsEvaluated: campaign.scenario6.attempts_evaluated,
      candidatesScored: campaign.scenario6.candidates_scored,
      candidatesRejected: campaign.scenario6.candidates_rejected,
      finalists: campaign.scenario6.finalists,
      explanation: campaign.scenario6.explanation,
    },
    s6: {
      available: s6.available,
      explanation: s6.available
        ? campaign.scenario6.explanation
        : s6.quality.explanation || campaign.scenario6.explanation,
    },
    caveats,
  };
}
