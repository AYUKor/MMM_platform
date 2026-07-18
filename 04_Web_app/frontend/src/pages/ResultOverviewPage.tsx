import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useAuth } from "../features/auth/AuthProvider";
import { JobResultView } from "../features/job-result/JobResultView";
import type { MediaPlanControls } from "../features/job-result/MediaPlanTab";
import {
  completedMediaScenario,
  resultSearchParams,
  resultTabFromSearch,
  type ResultTabId,
} from "../features/job-result/jobResultModel";
import {
  getJobResultViewV2,
  getScenarioMediaPlanV2,
} from "../shared/api/business-semantics-client";
import { getJobReportArtifacts } from "../shared/api/report-artifacts-client";
import { Button } from "../shared/ui/Button";
import styles from "../features/job-result/job-result.module.css";

const DEFAULT_MEDIA_CONTROLS: MediaPlanControls = {
  channel: null,
  geo: null,
  page: 1,
  pageSize: 25,
};

interface PageStateCopy {
  eyebrow: string;
  title: string;
  description: string;
  retryLabel: string | null;
  showProgressLink: boolean;
}

function errorStatus(error: unknown): number | null {
  return typeof error === "object" && error !== null && "status" in error && typeof error.status === "number"
    ? error.status
    : null;
}

function isUnsupported(error: unknown): boolean {
  return error instanceof Error && /unsupported/i.test(error.name);
}

function pageStateCopy(error: unknown): PageStateCopy {
  const status = errorStatus(error);
  if (status === 404) {
    return {
      eyebrow: "Результат расчета",
      title: "Результат еще не опубликован",
      description: "Проверьте ход расчета или вернитесь к списку расчетов.",
      retryLabel: "Проверить еще раз",
      showProgressLink: true,
    };
  }
  if (status === 409) {
    return {
      eyebrow: "Результат еще готовится",
      title: "Данные временно не согласованы",
      description: "Сервис завершает публикацию результата. Повторите запрос через несколько секунд.",
      retryLabel: "Обновить сведения",
      showProgressLink: false,
    };
  }
  if (status === 503) {
    return {
      eyebrow: "Результат расчета",
      title: "Результат временно недоступен",
      description: "Сервис не может безопасно собрать представление результата. Значения не восстанавливаются в браузере.",
      retryLabel: "Повторить",
      showProgressLink: false,
    };
  }
  if (isUnsupported(error)) {
    return {
      eyebrow: "Защитная проверка",
      title: "Данные результата имеют неподдерживаемый формат",
      description: "Ответ не прошел проверку и поэтому не показан.",
      retryLabel: "Повторить",
      showProgressLink: false,
    };
  }
  return {
    eyebrow: "Результат расчета",
    title: "Не удалось загрузить результат",
    description: "Проверьте соединение и повторите попытку.",
    retryLabel: "Повторить",
    showProgressLink: false,
  };
}

function ResultPageState({ copy, jobId, onRetry }: { copy: PageStateCopy; jobId: string; onRetry: () => void }) {
  return (
    <section className={styles.pageState} role="alert">
      <span className={styles.eyebrow}>{copy.eyebrow}</span>
      <h1>{copy.title}</h1>
      <p>{copy.description}</p>
      <div className={styles.pageStateActions}>
        {copy.retryLabel ? <Button onClick={onRetry}>{copy.retryLabel}</Button> : null}
        {copy.showProgressLink ? <Link className={styles.secondaryLink} to={`/calculations/${encodeURIComponent(jobId)}/progress`}>Открыть ход расчета</Link> : null}
        <Link className={styles.secondaryLink} to="/calculations">Все расчеты</Link>
      </div>
    </section>
  );
}

function ResultLoadingState() {
  return (
    <div className={styles.resultLoading} aria-live="polite" aria-busy="true">
      <div className={styles.loadingBreadcrumb} aria-hidden="true" />
      <header className={styles.loadingHeader}>
        <div><span aria-hidden="true" /><h1 aria-hidden="true" /><p>Получаем результат расчета…</p></div>
        <i aria-hidden="true" />
        <dl aria-hidden="true">{Array.from({ length: 5 }, (_, index) => <div key={index}><dt /><dd /></div>)}</dl>
      </header>
      <div className={styles.loadingTabs} aria-hidden="true">{Array.from({ length: 4 }, (_, index) => <span key={index} />)}</div>
      <div className={styles.loadingDecision} aria-hidden="true"><section><span /><h2 /><p /><p /><div /></section><aside><div /><div /></aside></div>
    </div>
  );
}

export function ResultOverviewPage() {
  const auth = useAuth();
  const { id = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = resultTabFromSearch(searchParams.get("tab"));
  const [mediaControls, setMediaControls] = useState<MediaPlanControls>(DEFAULT_MEDIA_CONTROLS);
  const resultQuery = useQuery({
    queryKey: ["job-result-view-v2", id],
    queryFn: ({ signal }) => getJobResultViewV2(id, signal),
    enabled: Boolean(id),
    retry: false,
    staleTime: 0,
  });
  const mediaScenarioId = resultQuery.data
    ? completedMediaScenario(resultQuery.data, searchParams.get("scenario"))
    : null;
  const previousMediaScenario = useRef(mediaScenarioId);

  useEffect(() => {
    if (!resultQuery.data) return;
    const canonical = resultSearchParams(activeTab, activeTab === "media-plan" ? mediaScenarioId : null);
    if (canonical.toString() !== searchParams.toString()) setSearchParams(canonical, { replace: true });
  }, [activeTab, mediaScenarioId, resultQuery.data, searchParams, setSearchParams]);

  useEffect(() => {
    if (previousMediaScenario.current === mediaScenarioId) return;
    previousMediaScenario.current = mediaScenarioId;
    setMediaControls(DEFAULT_MEDIA_CONTROLS);
  }, [mediaScenarioId]);

  const mediaQuery = useQuery({
    queryKey: ["scenario-media-plan-v2", id, mediaScenarioId, mediaControls.channel, mediaControls.geo, mediaControls.page, mediaControls.pageSize],
    queryFn: ({ signal }) => {
      if (mediaScenarioId === null || !resultQuery.data) throw new Error("Рассчитанный медиаплан для просмотра недоступен.");
      return getScenarioMediaPlanV2(id, {
        scenarioId: mediaScenarioId,
        channel: mediaControls.channel,
        geo: mediaControls.geo,
        page: mediaControls.page,
        pageSize: mediaControls.pageSize,
      }, resultQuery.data, signal);
    },
    enabled: Boolean(id) && Boolean(resultQuery.data) && activeTab === "media-plan" && mediaScenarioId !== null,
    retry: false,
    staleTime: 0,
  });

  const reportQuery = useQuery({
    queryKey: ["job-report-artifacts", id, resultQuery.data?.result_id],
    queryFn: ({ signal }) => {
      if (!resultQuery.data) throw new Error("Результат для проверки отчета недоступен.");
      return getJobReportArtifacts(id, resultQuery.data.result_id, signal);
    },
    enabled: Boolean(id) && Boolean(resultQuery.data) && activeTab === "report",
    retry: false,
    staleTime: 0,
  });

  if (!id) return <ResultPageState copy={pageStateCopy({ status: 404 })} jobId={id} onRetry={() => undefined} />;
  if (resultQuery.isPending && !resultQuery.data) return <ResultLoadingState />;
  if (!resultQuery.data) return <ResultPageState copy={pageStateCopy(resultQuery.error)} jobId={id} onRetry={() => { void resultQuery.refetch(); }} />;

  const refreshNotice = resultQuery.error
    ? isUnsupported(resultQuery.error)
      ? "Получен неподдерживаемый формат. Последний безопасный снимок результата сохранен."
      : "Не удалось обновить результат. Последний полученный снимок сохранен."
    : null;
  const changeTab = (tab: ResultTabId) => {
    const scenario = tab === "media-plan" ? completedMediaScenario(resultQuery.data, searchParams.get("scenario")) : null;
    setSearchParams(resultSearchParams(tab, scenario));
  };

  return (
    <JobResultView
      result={resultQuery.data}
      activeTab={activeTab}
      mediaPlan={mediaQuery.data}
      mediaScenarioId={mediaScenarioId}
      mediaControls={mediaControls}
      mediaLoading={mediaQuery.isPending || mediaQuery.isFetching}
      mediaError={mediaQuery.error}
      reportArtifacts={reportQuery.data}
      reportLoading={reportQuery.isPending || reportQuery.isFetching}
      reportError={reportQuery.error}
      canDownload={auth.can("report.download")}
      refreshNotice={refreshNotice}
      onTabChange={changeTab}
      onMediaScenarioChange={(scenarioId) => {
        setMediaControls(DEFAULT_MEDIA_CONTROLS);
        setSearchParams(resultSearchParams("media-plan", scenarioId));
      }}
      onMediaControlsChange={setMediaControls}
      onMediaPageChange={(page) => setMediaControls((current) => ({ ...current, page }))}
      onMediaRetry={() => {
        if (errorStatus(mediaQuery.error) === 422) setMediaControls(DEFAULT_MEDIA_CONTROLS);
        else void mediaQuery.refetch();
      }}
      onReportRetry={() => { void reportQuery.refetch(); }}
      onRefresh={() => { void resultQuery.refetch(); }}
    />
  );
}
