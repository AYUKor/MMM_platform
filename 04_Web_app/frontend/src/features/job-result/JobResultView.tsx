import { Link } from "react-router-dom";
import type { JobResultViewV2 } from "../../shared/api/generated/job-result-view-v2";
import type { ScenarioId, ScenarioMediaPlanV2 } from "../../shared/api/generated/scenario-media-plan-v2";
import { formatInteger, formatRub } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import { Tabs } from "../../shared/ui/Tabs";
import { MediaPlanTab, type MediaPlanControls } from "./MediaPlanTab";
import { OverviewTab } from "./OverviewTab";
import { ReportTab } from "./ReportTab";
import { ScenariosReliabilityTab } from "./ScenariosReliabilityTab";
import { campaignPeriod, decisionLabel, decisionTone, reviewLabel } from "./jobResultFormatting";
import { RESULT_TABS, type ResultTabId } from "./jobResultModel";
import styles from "./job-result.module.css";

export interface JobResultViewProps {
  result: JobResultViewV2;
  activeTab: ResultTabId;
  mediaPlan: ScenarioMediaPlanV2 | undefined;
  mediaScenarioId: ScenarioId | null;
  mediaControls: MediaPlanControls;
  mediaLoading: boolean;
  mediaError: unknown;
  refreshNotice: string | null;
  onTabChange: (tab: ResultTabId) => void;
  onMediaScenarioChange: (scenarioId: ScenarioId) => void;
  onMediaControlsChange: (controls: MediaPlanControls) => void;
  onMediaPageChange: (page: number) => void;
  onMediaRetry: () => void;
  onRefresh: () => void;
}

export function JobResultView({
  result,
  activeTab,
  mediaPlan,
  mediaScenarioId,
  mediaControls,
  mediaLoading,
  mediaError,
  refreshNotice,
  onTabChange,
  onMediaScenarioChange,
  onMediaControlsChange,
  onMediaPageChange,
  onMediaRetry,
  onRefresh,
}: JobResultViewProps) {
  return (
    <div className={styles.page}>
      <nav className={styles.breadcrumbs} aria-label="Хлебные крошки">
        <Link to="/calculations">Мои расчеты</Link>
        <span aria-hidden="true">/</span>
        <span>Результат</span>
      </nav>

      <header className={styles.campaignHeader}>
        <div className={styles.campaignTitle}>
          <div className={styles.headerLabels}>
            <span className={styles.eyebrow}>Результат расчета</span>
            {result.record_origin === "sanitized_fixture" ? <span className={styles.demoBadge}>Демонстрационные данные</span> : null}
          </div>
          <h1>{result.campaign.campaign_name}</h1>
        </div>
        <div className={styles.headerAside}>
          <div className={styles.campaignStatus}>
            <StatusBadge tone={decisionTone(result.recommendation.decision_status)}>
              {decisionLabel(result.recommendation.decision_status)}
            </StatusBadge>
          </div>
          {result.recommendation.review_status === "manual_review_required" ? (
            <StatusBadge tone="warning">{reviewLabel(result.recommendation.review_status)}</StatusBadge>
          ) : null}
          <Link className={styles.secondaryLink} to="/calculations">Все расчеты</Link>
        </div>
        <dl className={styles.campaignMeta}>
          <div><dt>Период</dt><dd>{campaignPeriod(result.campaign.start_date, result.campaign.end_date)}</dd></div>
          <div><dt>Сегменты</dt><dd>{result.campaign.segments.join(", ")}</dd></div>
          <div><dt>Запрошенный бюджет</dt><dd>{formatRub(result.campaign.requested_budget_rub)}</dd></div>
          <div><dt>Каналы</dt><dd>{formatInteger(result.campaign.channels.length)}</dd></div>
          <div><dt>Географии</dt><dd>{formatInteger(result.campaign.geographies_n)}</dd></div>
        </dl>
      </header>

      {refreshNotice ? (
        <div className={styles.refreshNotice} role="status"><span>{refreshNotice}</span><Button onClick={onRefresh}>Повторить</Button></div>
      ) : null}

      <div className={styles.tabsFrame}>
        <Tabs items={[...RESULT_TABS]} activeId={activeTab} onChange={(tab) => onTabChange(tab as ResultTabId)} />
      </div>

      <section id={`${activeTab}-panel`} role="tabpanel" aria-labelledby={`${activeTab}-tab`} tabIndex={0} className={styles.tabPanel}>
        {activeTab === "overview" ? <OverviewTab result={result} onOpenMediaPlan={() => onTabChange("media-plan")} /> : null}
        {activeTab === "scenarios" ? <ScenariosReliabilityTab result={result} /> : null}
        {activeTab === "media-plan" ? (
          <MediaPlanTab
            result={result}
            plan={mediaPlan}
            selectedScenarioId={mediaScenarioId}
            controls={mediaControls}
            loading={mediaLoading}
            error={mediaError}
            onScenarioChange={onMediaScenarioChange}
            onControlsChange={onMediaControlsChange}
            onPageChange={onMediaPageChange}
            onRetry={onMediaRetry}
          />
        ) : null}
        {activeTab === "report" ? <ReportTab /> : null}
      </section>
    </div>
  );
}
