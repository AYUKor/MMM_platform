import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { JobProgressView } from "../features/job-progress/JobProgressView";
import {
  isTerminalJobStatus,
  selectFactForJob,
} from "../features/job-progress/jobProgressModel";
import progressStyles from "../features/job-progress/job-progress.module.css";
import {
  getJobProgressView,
  getMmmFacts,
  JobProgressInconsistentError,
  JobProgressNotFoundError,
  UnsupportedJobProgressContractError,
} from "../shared/api/job-progress-client";
import { cancelJob } from "../shared/api/lifecycle-client";
import { Button } from "../shared/ui/Button";

interface InitialStateCopy {
  title: string;
  description: string;
  retryLabel: string | null;
}

function initialStateCopy(error: unknown): InitialStateCopy {
  if (error instanceof JobProgressNotFoundError) {
    return {
      title: "Расчет не найден",
      description: "Проверьте адрес или вернитесь к списку расчетов.",
      retryLabel: null,
    };
  }
  if (error instanceof JobProgressInconsistentError) {
    return {
      title: "Состояние расчета временно не согласовано",
      description: "Данные обновляются. Запросите сведения еще раз через несколько секунд.",
      retryLabel: "Обновить сведения",
    };
  }
  if (error instanceof UnsupportedJobProgressContractError) {
    return {
      title: "Формат сведений не поддерживается",
      description: "Версия интерфейса не может безопасно показать полученные данные.",
      retryLabel: "Повторить",
    };
  }
  return {
    title: "Не удалось обновить сведения о расчете",
    description: "Проверьте соединение и повторите попытку.",
    retryLabel: "Повторить",
  };
}

function ProgressPageState({
  copy,
  onRetry,
}: {
  copy: InitialStateCopy;
  onRetry: () => void;
}) {
  return (
    <section className={progressStyles.pageState} role="alert">
      <span className={progressStyles.eyebrow}>Ход расчета</span>
      <h1>{copy.title}</h1>
      <p>{copy.description}</p>
      <div className={progressStyles.pageStateActions}>
        {copy.retryLabel ? <Button onClick={onRetry}>{copy.retryLabel}</Button> : null}
        <Link className={progressStyles.secondaryLink} to="/calculations">Все расчеты</Link>
      </div>
    </section>
  );
}

export function JobProgressPage() {
  const { id = "" } = useParams();
  const progressQuery = useQuery({
    queryKey: ["job-progress-view", id],
    queryFn: ({ signal }) => getJobProgressView(id, signal),
    enabled: Boolean(id),
    retry: false,
    staleTime: 0,
    refetchInterval: (query) => {
      const status = query.state.data?.job_status.code;
      if (!status || isTerminalJobStatus(status)) return false;
      return ["queued", "running", "cancel_requested"].includes(status) ? 1_500 : false;
    },
    refetchIntervalInBackground: false,
  });
  const factsQuery = useQuery({
    queryKey: ["mmm-facts-v1"],
    queryFn: ({ signal }) => getMmmFacts(signal),
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const cancelMutation = useMutation({
    mutationFn: () => cancelJob(id),
    onSuccess: async () => {
      await progressQuery.refetch();
    },
  });

  if (!id) {
    return (
      <ProgressPageState
        copy={initialStateCopy(new JobProgressNotFoundError())}
        onRetry={() => undefined}
      />
    );
  }

  if (progressQuery.isPending && !progressQuery.data) {
    return (
      <div className={progressStyles.loadingPage} aria-live="polite" aria-busy="true">
        <span aria-hidden="true" />
        <p>Получаем сведения о расчете…</p>
      </div>
    );
  }

  if (!progressQuery.data) {
    return (
      <ProgressPageState
        copy={initialStateCopy(progressQuery.error)}
        onRetry={() => {
          void progressQuery.refetch();
        }}
      />
    );
  }

  const refreshNotice = progressQuery.error
    ? {
        description: progressQuery.error instanceof JobProgressInconsistentError
          ? "Состояние расчета временно не согласовано. Последние полученные сведения сохранены."
          : progressQuery.error instanceof UnsupportedJobProgressContractError
            ? "Получен неподдерживаемый формат. Последние полученные сведения сохранены."
            : "Не удалось обновить сведения о расчете. Последние полученные сведения сохранены.",
        actionLabel: progressQuery.error instanceof JobProgressInconsistentError
          ? "Обновить сведения"
          : "Повторить",
      }
    : null;

  return (
    <JobProgressView
      view={progressQuery.data}
      fact={selectFactForJob(factsQuery.data, id)}
      refreshNotice={refreshNotice}
      onRefresh={() => {
        void progressQuery.refetch();
      }}
      onCancel={async () => {
        await cancelMutation.mutateAsync();
      }}
      cancelPending={cancelMutation.isPending}
      cancelError={cancelMutation.isError
        ? "Не удалось отправить запрос на отмену. Повторите попытку."
        : null}
    />
  );
}
