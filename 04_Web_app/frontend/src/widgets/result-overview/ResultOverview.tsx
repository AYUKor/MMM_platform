import { useState } from "react";
import type {
  OverviewCampaign,
  ResultOverviewV1,
} from "../../entities/result-overview/types";
import {
  buildResultOverviewModel,
  ResultPresentationError,
} from "../../features/calculation-result/buildResultOverviewModel";
import { ErrorState } from "../../shared/ui/ErrorState";
import { Tabs } from "../../shared/ui/Tabs";
import { BenchmarkPanel } from "./BenchmarkPanel";
import { CampaignHeader } from "./CampaignHeader";
import { Caveats } from "./Caveats";
import { CoveragePanel } from "./DataGapPanel";
import { MediaPlanPanel } from "./MediaPlanPanel";
import { MetricsGrid } from "./MetricsGrid";
import { RecommendationPanel } from "./RecommendationPanel";
import { ReliabilityPanel } from "./ReliabilityPanel";
import { ReportPanel } from "./ReportPanel";
import { ScenarioComparisonPanel } from "./ScenarioComparisonPanel";
import { SearchStats } from "./SearchStats";
import styles from "./result-overview.module.css";

interface ResultOverviewProps {
  result: ResultOverviewV1;
  campaign: OverviewCampaign;
}

type ResultTabId = "overview" | "scenarios" | "reliability" | "plan" | "report";

const resultTabs: Array<{ id: ResultTabId; label: string }> = [
  { id: "overview", label: "Обзор" },
  { id: "scenarios", label: "Сценарии" },
  { id: "reliability", label: "Надежность" },
  { id: "plan", label: "Медиаплан" },
  { id: "report", label: "Отчет" },
];

export function ResultOverview({ result, campaign }: ResultOverviewProps) {
  const [activeTab, setActiveTab] = useState<ResultTabId>("overview");
  let model;
  try {
    model = buildResultOverviewModel(result, campaign);
  } catch (error) {
    return (
      <ErrorState
        title="Результат не соответствует контракту"
        description={error instanceof ResultPresentationError ? error.message : "Не удалось подготовить представление результата."}
      />
    );
  }

  const reportDownload = model.downloads.find((download) => download.kind === "report") ?? null;

  return (
    <div className={styles.page}>
      <CampaignHeader model={model} reportDownload={reportDownload} />
      <Tabs
        items={resultTabs}
        activeId={activeTab}
        onChange={(id) => setActiveTab(id as ResultTabId)}
      />

      {activeTab === "overview" ? (
        <section
          id="overview-panel"
          role="tabpanel"
          aria-labelledby="overview-tab"
          className={styles.overviewPanel}
        >
          <section className={styles.decisionGrid} aria-label="Рекомендация и benchmark">
            <RecommendationPanel model={model} />
            <BenchmarkPanel scenario={model.benchmarkScenario} />
          </section>
          <MetricsGrid metrics={model.metrics} />
          <CoveragePanel model={model} />
          <section className={styles.explanationGrid}>
            <section className={styles.whySection}>
              <div className={styles.sectionHeading}><h2>Почему показан этот план</h2></div>
              <ol className={styles.reasons}>
                <li><span>1</span><p>{model.recommendation.reason}</p></li>
                <li><span>2</span><p>{model.recommendation.plan.description}</p></li>
                <li><span>3</span><p>{model.recommendation.quality.description}</p></li>
              </ol>
            </section>
            <SearchStats model={model} />
          </section>
          <Caveats warnings={model.warnings} limit={3} />
          <footer className={styles.demoFooter}>
            {model.demoData
              ? "Демонстрационный режим · не использовать для бизнес-решений"
              : "Значения получены из готового результата расчета"}
          </footer>
        </section>
      ) : null}

      {activeTab === "scenarios" ? (
        <div id="scenarios-panel" role="tabpanel" aria-labelledby="scenarios-tab" className={styles.tabPanel}>
          <ScenarioComparisonPanel model={model} />
        </div>
      ) : null}
      {activeTab === "reliability" ? (
        <div id="reliability-panel" role="tabpanel" aria-labelledby="reliability-tab" className={styles.tabPanel}>
          <ReliabilityPanel model={model} />
        </div>
      ) : null}
      {activeTab === "plan" ? (
        <div id="plan-panel" role="tabpanel" aria-labelledby="plan-tab" className={styles.tabPanel}>
          <MediaPlanPanel model={model} />
        </div>
      ) : null}
      {activeTab === "report" ? (
        <div id="report-panel" role="tabpanel" aria-labelledby="report-tab" className={styles.tabPanel}>
          <ReportPanel model={model} />
        </div>
      ) : null}
    </div>
  );
}
