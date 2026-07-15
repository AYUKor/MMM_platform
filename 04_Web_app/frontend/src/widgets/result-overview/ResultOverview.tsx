import type {
  CampaignResult,
  DecisionResultV1,
} from "../../entities/decision-result/types";
import {
  buildResultOverviewModel,
  ResultPresentationError,
} from "../../features/calculation-result/buildResultOverviewModel";
import { ErrorState } from "../../shared/ui/ErrorState";
import { Tabs } from "../../shared/ui/Tabs";
import { BenchmarkPanel } from "./BenchmarkPanel";
import { CampaignHeader } from "./CampaignHeader";
import { Caveats } from "./Caveats";
import { DataGapPanel } from "./DataGapPanel";
import { MetricsGrid } from "./MetricsGrid";
import { RecommendationPanel } from "./RecommendationPanel";
import { SearchStats } from "./SearchStats";
import styles from "./result-overview.module.css";

interface ResultOverviewProps {
  result: DecisionResultV1;
  campaign: CampaignResult;
}

const resultTabs = [
  { id: "overview", label: "Обзор" },
  { id: "scenarios", label: "Сценарии и надёжность", disabled: true },
  { id: "plan", label: "Медиаплан", disabled: true },
  { id: "report", label: "Отчёт", disabled: true },
];

export function ResultOverview({ result, campaign }: ResultOverviewProps) {
  let model;
  try {
    model = buildResultOverviewModel(result, campaign);
  } catch (error) {
    return (
      <ErrorState
        title="Результат не соответствует contract"
        description={error instanceof ResultPresentationError ? error.message : "Не удалось подготовить представление результата."}
      />
    );
  }

  const reportArtifactId =
    result.artifacts.find((artifact) => artifact.kind === "marketer_report_xlsx")
      ?.artifact_id ?? null;

  return (
    <div className={styles.page}>
      <CampaignHeader model={model} reportArtifactId={reportArtifactId} />
      <Tabs items={resultTabs} activeId="overview" />
      <section id="overview-panel" role="tabpanel" className={styles.overviewPanel}>
        <section className={styles.decisionGrid} aria-label="Рекомендация и benchmark">
          <RecommendationPanel model={model} />
          <BenchmarkPanel scenario={model.benchmarkScenario} />
        </section>
        <MetricsGrid metrics={model.metrics} />
        <section className={styles.explanationGrid}>
          <section className={styles.whySection}>
            <div className={styles.sectionHeading}><h2>Почему выбран этот план</h2></div>
            <ol className={styles.reasons}>
              <li><span>1</span><p>{model.recommendation.reason}</p></li>
              <li><span>2</span><p>{model.recommendation.planStatus}</p></li>
              <li><span>3</span><p>{model.recommendation.qualityStatus}</p></li>
            </ol>
          </section>
          <SearchStats model={model} />
        </section>
        <DataGapPanel />
        <Caveats caveats={model.caveats} />
        <footer className={styles.demoFooter}>
          {model.demoData ? "Sanitized fixture · не production evidence" : "DecisionResult v1"}
        </footer>
      </section>
    </div>
  );
}
