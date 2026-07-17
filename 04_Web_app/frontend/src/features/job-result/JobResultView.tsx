import { Link } from "react-router-dom";
import type { JobResultViewV1, ScenarioId } from "../../shared/api/generated/job-result-view-v1";
import type { ScenarioMediaPlanV1 } from "../../shared/api/generated/scenario-media-plan-v1";
import { resolveArtifactDownloadUrl } from "../../shared/api/job-result-client";
import { formatInteger, formatPercent, formatRub } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import { Tabs } from "../../shared/ui/Tabs";
import { MediaPlanTab, type MediaPlanControls } from "./MediaPlanTab";
import { OverviewTab } from "./OverviewTab";
import { ReportTab } from "./ReportTab";
import { ScenariosReliabilityTab } from "./ScenariosReliabilityTab";
import { campaignPeriod, type ResultMetricId } from "./jobResultFormatting";
import { RESULT_TABS, type ResultTabId } from "./jobResultModel";
import styles from "./job-result.module.css";

export interface JobResultViewProps {
  result: JobResultViewV1;
  activeTab: ResultTabId;
  metricId: ResultMetricId;
  mediaPlan: ScenarioMediaPlanV1 | undefined;
  mediaScenarioId: ScenarioId | null;
  mediaControls: MediaPlanControls;
  mediaLoading: boolean;
  mediaError: unknown;
  refreshNotice: string | null;
  onTabChange: (tab: ResultTabId) => void;
  onMetricChange: (metricId: ResultMetricId) => void;
  onMediaScenarioChange: (scenarioId: ScenarioId) => void;
  onMediaControlsChange: (controls: MediaPlanControls) => void;
  onMediaPageChange: (page: number) => void;
  onMediaRetry: () => void;
  onRefresh: () => void;
  canDownload?: boolean;
}

export function JobResultView({
  result,
  activeTab,
  metricId,
  mediaPlan,
  mediaScenarioId,
  mediaControls,
  mediaLoading,
  mediaError,
  refreshNotice,
  onTabChange,
  onMetricChange,
  onMediaScenarioChange,
  onMediaControlsChange,
  onMediaPageChange,
  onMediaRetry,
  onRefresh,
  canDownload = true,
}: JobResultViewProps) {
  const recommendationStatus = result.recommendation.status === "recommended"
    ? { label: "Рекомендация готова", tone: "accent" as const }
    : result.recommendation.status === "no_safe_recommendation"
      ? { label: "Автоматической рекомендации нет", tone: "warning" as const }
      : { label: "Рекомендация недоступна", tone: "neutral" as const };
  let reportDownloadUrl: string | null = null;
  if (result.report.status === "ready" && result.report.artifact !== null) {
    try {
      reportDownloadUrl = resolveArtifactDownloadUrl(result.report.artifact.download_path);
    } catch {
      reportDownloadUrl = null;
    }
  }

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
            {result.record_origin === "sanitized_fixture" ? (
              <span className={styles.demoBadge}>Демонстрационные данные</span>
            ) : null}
          </div>
          <h1>{result.campaign.campaign_name}</h1>
        </div>
        <div className={styles.headerAside}>
          <div className={styles.campaignStatus}>
            <StatusBadge tone={recommendationStatus.tone}>{recommendationStatus.label}</StatusBadge>
          </div>
          <div className={styles.headerActions}>
            <Link className={styles.secondaryLink} to="/calculations">Все расчеты</Link>
            {reportDownloadUrl && canDownload ? (
              <a className={styles.headerDownload} href={reportDownloadUrl} download>
                Скачать отчет
              </a>
            ) : null}
          </div>
        </div>

        <dl className={styles.campaignMeta}>
          <div><dt>Период</dt><dd>{campaignPeriod(result.campaign.start_date, result.campaign.end_date)}</dd></div>
          <div><dt>Сегменты</dt><dd>{result.campaign.segments.join(", ")}</dd></div>
          <div><dt>Бюджет</dt><dd>{formatRub(result.campaign.total_budget_rub)}</dd></div>
          <div><dt>Каналы</dt><dd>{formatInteger(result.campaign.channels_n)}</dd></div>
          <div><dt>Географии</dt><dd>{formatInteger(result.campaign.geographies_n)}</dd></div>
          <div><dt>Покрытие модели</dt><dd>{formatPercent(result.campaign.model_coverage_share)}</dd></div>
        </dl>
      </header>

      {refreshNotice ? (
        <div className={styles.refreshNotice} role="status">
          <span>{refreshNotice}</span>
          <Button onClick={onRefresh}>Повторить</Button>
        </div>
      ) : null}

      <div className={styles.tabsFrame}>
        <Tabs
          items={[...RESULT_TABS]}
          activeId={activeTab}
          onChange={(tab) => onTabChange(tab as ResultTabId)}
        />
      </div>

      <section
        id={`${activeTab}-panel`}
        role="tabpanel"
        aria-labelledby={`${activeTab}-tab`}
        tabIndex={0}
        className={styles.tabPanel}
      >
        {activeTab === "overview" ? (
          <OverviewTab
            result={result}
            metricId={metricId}
            onMetricChange={onMetricChange}
            onOpenMediaPlan={() => onTabChange("media-plan")}
          />
        ) : null}
        {activeTab === "scenarios" ? (
          <ScenariosReliabilityTab
            result={result}
            metricId={metricId}
            onMetricChange={onMetricChange}
          />
        ) : null}
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
        {activeTab === "report" ? <ReportTab result={result} canDownload={canDownload} /> : null}
      </section>
    </div>
  );
}
