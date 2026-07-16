import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  JobResultInconsistentError,
  JobResultNotReadyError,
  JobResultNotFoundError,
  JobResultUnavailableError,
  MediaPlanQueryUnsupportedError,
  UnsupportedJobResultContractError,
  getJobResultView,
  getScenarioMediaPlan,
} from "../shared/api/job-result-client";
import { Button } from "../shared/ui/Button";
import { JobResultView } from "../features/job-result/JobResultView";
import type { MediaPlanControls } from "../features/job-result/MediaPlanTab";
import type { ResultMetricId } from "../features/job-result/jobResultFormatting";
import {
  mediaPlanScenarioFromSearch,
  resultSearchParams,
  resultTabFromSearch,
  type ResultTabId,
} from "../features/job-result/jobResultModel";
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

function pageStateCopy(error: unknown): PageStateCopy {
  if (error instanceof JobResultNotFoundError) {
    return {
      eyebrow: "Результат расчета",
      title: "Результат не найден",
      description: "Проверьте адрес или вернитесь к списку расчетов.",
      retryLabel: null,
      showProgressLink: false,
    };
  }
  if (error instanceof JobResultNotReadyError) {
    return {
      eyebrow: "Расчет продолжается",
      title: "Результат еще не готов",
      description: "Откройте ход расчета или повторите запрос через несколько секунд. Автоматического перехода не будет.",
      retryLabel: "Проверить еще раз",
      showProgressLink: true,
    };
  }
  if (error instanceof JobResultInconsistentError) {
    return {
      eyebrow: "Результат еще готовится",
      title: "Данные временно не согласованы",
      description: "Сервис завершает публикацию результата. Повторите запрос через несколько секунд.",
      retryLabel: "Обновить сведения",
      showProgressLink: false,
    };
  }
  if (error instanceof JobResultUnavailableError) {
    return {
      eyebrow: "Результат расчета",
      title: "Результат временно недоступен",
      description: "Сервис не может безопасно собрать представление результата. Значения не восстанавливаются в браузере.",
      retryLabel: "Повторить",
      showProgressLink: false,
    };
  }
  if (error instanceof UnsupportedJobResultContractError) {
    return {
      eyebrow: "Защитная проверка",
      title: "Формат результата не поддерживается",
      description: "Ответ не прошел проверку контракта и поэтому не показан.",
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

function ResultPageState({
  copy,
  jobId,
  onRetry,
}: {
  copy: PageStateCopy;
  jobId: string;
  onRetry: () => void;
}) {
  return (
    <section className={styles.pageState} role="alert">
      <span className={styles.eyebrow}>{copy.eyebrow}</span>
      <h1>{copy.title}</h1>
      <p>{copy.description}</p>
      <div className={styles.pageStateActions}>
        {copy.retryLabel ? <Button onClick={onRetry}>{copy.retryLabel}</Button> : null}
        {copy.showProgressLink ? (
          <Link className={styles.secondaryLink} to={`/calculations/${encodeURIComponent(jobId)}/progress`}>
            Открыть ход расчета
          </Link>
        ) : null}
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
        <div>
          <span aria-hidden="true" />
          <h1 aria-hidden="true" />
          <p>Получаем результат расчета…</p>
        </div>
        <i aria-hidden="true" />
        <dl aria-hidden="true">
          {Array.from({ length: 6 }, (_, index) => <div key={index}><dt /><dd /></div>)}
        </dl>
      </header>
      <div className={styles.loadingTabs} aria-hidden="true">
        {Array.from({ length: 4 }, (_, index) => <span key={index} />)}
      </div>
      <div className={styles.loadingDecision} aria-hidden="true">
        <section><span /><h2 /><p /><p /><div /></section>
        <aside><div /><div /></aside>
      </div>
    </div>
  );
}

export function ResultOverviewPage() {
  const { id = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = resultTabFromSearch(searchParams.get("tab"));
  const [metricId, setMetricId] = useState<ResultMetricId>("incremental_turnover_rub");
  const [mediaControls, setMediaControls] = useState<MediaPlanControls>(DEFAULT_MEDIA_CONTROLS);

  const resultQuery = useQuery({
    queryKey: ["job-result-view", id],
    queryFn: ({ signal }) => getJobResultView(id, signal),
    enabled: Boolean(id),
    retry: false,
    staleTime: 0,
  });
  const mediaScenarioId = resultQuery.data
    ? mediaPlanScenarioFromSearch(resultQuery.data, searchParams.get("scenario"))
    : null;
  const previousMediaScenario = useRef(mediaScenarioId);

  useEffect(() => {
    if (!resultQuery.data) return;
    const canonical = resultSearchParams(activeTab, activeTab === "media-plan" ? mediaScenarioId : null);
    if (canonical.toString() !== searchParams.toString()) {
      setSearchParams(canonical, { replace: true });
    }
  }, [activeTab, mediaScenarioId, resultQuery.data, searchParams, setSearchParams]);

  useEffect(() => {
    if (previousMediaScenario.current !== mediaScenarioId) {
      previousMediaScenario.current = mediaScenarioId;
      setMediaControls(DEFAULT_MEDIA_CONTROLS);
    }
  }, [mediaScenarioId]);

  const mediaQuery = useQuery({
    queryKey: [
      "scenario-media-plan",
      id,
      mediaScenarioId,
      mediaControls.channel,
      mediaControls.geo,
      mediaControls.page,
      mediaControls.pageSize,
    ],
    queryFn: ({ signal }) => {
      if (!resultQuery.data || mediaScenarioId === null) {
        throw new Error("Медиаплан нельзя запросить без результата и сценария.");
      }
      return getScenarioMediaPlan(
        id,
        {
          scenarioId: mediaScenarioId,
          channel: mediaControls.channel,
          geo: mediaControls.geo,
          page: mediaControls.page,
          pageSize: mediaControls.pageSize,
        },
        resultQuery.data,
        signal,
      );
    },
    enabled: Boolean(id) && Boolean(resultQuery.data) && activeTab === "media-plan" && mediaScenarioId !== null,
    retry: false,
    staleTime: 0,
  });

  if (!id) {
    return <ResultPageState copy={pageStateCopy(new JobResultNotFoundError())} jobId={id} onRetry={() => undefined} />;
  }

  if (resultQuery.isPending && !resultQuery.data) {
    return <ResultLoadingState />;
  }

  if (!resultQuery.data) {
    return (
      <ResultPageState
        copy={pageStateCopy(resultQuery.error)}
        jobId={id}
        onRetry={() => { void resultQuery.refetch(); }}
      />
    );
  }

  const refreshNotice = resultQuery.error
    ? resultQuery.error instanceof JobResultInconsistentError
      ? "Данные временно не согласованы. Последний безопасный снимок результата сохранен."
      : resultQuery.error instanceof UnsupportedJobResultContractError
        ? "Получен неподдерживаемый формат. Последний безопасный снимок результата сохранен."
        : "Не удалось обновить результат. Последний полученный снимок сохранен."
    : null;

  const changeTab = (tab: ResultTabId) => {
    const scenario = tab === "media-plan"
      ? mediaPlanScenarioFromSearch(resultQuery.data, searchParams.get("scenario"))
      : null;
    setSearchParams(resultSearchParams(tab, scenario));
  };

  const retryMediaPlan = () => {
    if (mediaQuery.error instanceof MediaPlanQueryUnsupportedError) {
      const controlsAreDefault =
        mediaControls.channel === null &&
        mediaControls.geo === null &&
        mediaControls.page === DEFAULT_MEDIA_CONTROLS.page &&
        mediaControls.pageSize === DEFAULT_MEDIA_CONTROLS.pageSize;
      if (!controlsAreDefault) {
        setMediaControls(DEFAULT_MEDIA_CONTROLS);
        return;
      }
    }
    void mediaQuery.refetch();
  };

  return (
    <JobResultView
      result={resultQuery.data}
      activeTab={activeTab}
      metricId={metricId}
      mediaPlan={mediaQuery.data}
      mediaScenarioId={mediaScenarioId}
      mediaControls={mediaControls}
      mediaLoading={mediaQuery.isPending || mediaQuery.isFetching}
      mediaError={mediaQuery.error}
      refreshNotice={refreshNotice}
      onTabChange={changeTab}
      onMetricChange={setMetricId}
      onMediaScenarioChange={(scenarioId) => {
        setMediaControls(DEFAULT_MEDIA_CONTROLS);
        setSearchParams(resultSearchParams("media-plan", scenarioId));
      }}
      onMediaControlsChange={setMediaControls}
      onMediaPageChange={(page) => setMediaControls((current) => ({ ...current, page }))}
      onMediaRetry={retryMediaPlan}
      onRefresh={() => { void resultQuery.refetch(); }}
    />
  );
}
