import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { selectCampaign } from "../features/calculation-result/selectCampaign";
import { getJob, getJobErrors } from "../shared/api/lifecycle-client";
import { createResultProvider } from "../shared/api/provider-factory";
import { Card } from "../shared/ui/Card";
import { EmptyState } from "../shared/ui/EmptyState";
import { ErrorState } from "../shared/ui/ErrorState";
import { LoadingSkeleton } from "../shared/ui/LoadingSkeleton";
import { ResultOverview } from "../widgets/result-overview/ResultOverview";
import { PermissionDeniedPage } from "./PermissionDeniedPage";

const resultProvider = createResultProvider();
const failedStatuses = new Set(["failed", "cancelled", "timed_out"]);

function FailedJobState({ status, retryable }: { status: string; retryable: boolean }) {
  if (status === "cancelled") {
    return (
      <ErrorState
        title="Расчет отменен"
        description="Этот запуск был отменен. Создайте новый расчет, если результат все еще нужен."
      />
    );
  }
  if (status === "timed_out") {
    return (
      <ErrorState
        title="Расчет не успел завершиться"
        description={retryable
          ? "Операция превысила допустимое время. Расчет можно запустить повторно."
          : "Операция превысила допустимое время. Перед повтором обратитесь к администратору."}
      />
    );
  }
  return (
    <ErrorState
      title="Расчет завершился с ошибкой"
      description={retryable
        ? "Ошибка допускает повторный запуск. Проверьте входной файл и попробуйте снова."
        : "Автоматический повтор недоступен. Перед новым запуском обратитесь к администратору."}
    />
  );
}

export function ResultOverviewPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const forcedState = import.meta.env.DEV ? searchParams.get("state") : null;
  const campaignId = searchParams.get("campaignId");

  const lifecycleQuery = useQuery({
    queryKey: ["result-job", id],
    queryFn: () => getJob(id ?? ""),
    enabled: Boolean(id) && forcedState === null && resultProvider.kind === "http",
  });
  const jobStatus = lifecycleQuery.data?.status.code;
  const errorsQuery = useQuery({
    queryKey: ["result-job-errors", id],
    queryFn: () => getJobErrors(id ?? ""),
    enabled:
      Boolean(id) &&
      forcedState === null &&
      resultProvider.kind === "http" &&
      typeof jobStatus === "string" &&
      failedStatuses.has(jobStatus),
  });
  const overviewCanLoad =
    resultProvider.kind !== "http" || jobStatus === "succeeded";
  const overviewQuery = useQuery({
    queryKey: ["result-overview", id, resultProvider.kind],
    queryFn: () => resultProvider.getOverview(id ?? ""),
    enabled: Boolean(id) && forcedState === null && overviewCanLoad,
  });

  if (!id) {
    return <ErrorState title="Расчет не указан" description="Вернитесь к истории и выберите расчет." />;
  }
  if (forcedState === "loading") return <LoadingSkeleton />;
  if (forcedState === "permission") return <PermissionDeniedPage />;
  if (forcedState === "empty") {
    return <EmptyState title="Нет данных" description="Готовый обзор не содержит доступных кампаний." />;
  }
  if (forcedState === "invalid") {
    return (
      <ErrorState
        title="Результат имеет неизвестный формат"
        description="Данные не прошли проверку контракта и поэтому не показаны."
      />
    );
  }
  if (forcedState === "failed") {
    return <FailedJobState status="failed" retryable />;
  }
  if (forcedState === "unavailable") {
    return (
      <EmptyState
        title="Результат недоступен"
        description="Готовый обзор для этого расчета отсутствует. Значения не восстанавливаются в браузере."
      />
    );
  }
  if (forcedState === "error") {
    return (
      <ErrorState
        title="Не удалось загрузить результат"
        description="Соединение прервалось. Повторите попытку после его восстановления."
      />
    );
  }

  if (resultProvider.kind === "http" && lifecycleQuery.isLoading) return <LoadingSkeleton />;
  if (lifecycleQuery.isError) {
    return (
      <ErrorState
        title="Не удалось проверить состояние расчета"
        description="История расчета временно недоступна. Повторите попытку позже."
      />
    );
  }
  if (jobStatus === "queued" || jobStatus === "running" || jobStatus === "cancel_requested") {
    return (
      <Card as="section" className="campaign-selection" role="status">
        <h1>Расчет еще выполняется</h1>
        <p>Готовый обзор появится после успешного завершения всех этапов.</p>
        <div className="campaign-selection__actions">
          <Link to={`/calculations/${encodeURIComponent(id)}/progress`}>Открыть прогресс</Link>
        </div>
      </Card>
    );
  }
  if (typeof jobStatus === "string" && failedStatuses.has(jobStatus)) {
    return (
      <FailedJobState
        status={jobStatus}
        retryable={errorsQuery.data?.some((error) => error.retryable) ?? false}
      />
    );
  }
  if (resultProvider.kind === "http" && jobStatus !== "succeeded") {
    return (
      <ErrorState
        title="Состояние расчета не поддерживается"
        description="Обзор не будет показан до подтвержденного успешного завершения."
      />
    );
  }
  if (overviewQuery.isLoading) return <LoadingSkeleton />;
  if (overviewQuery.isError) {
    return (
      <ErrorState
        title="Не удалось загрузить результат"
        description={
          overviewQuery.error instanceof Error
            ? overviewQuery.error.message
            : "Повторите попытку после восстановления соединения."
        }
      />
    );
  }
  if (!overviewQuery.data) {
    return (
      <EmptyState
        title="Нет данных"
        description="Готовый обзор отсутствует. Нулевые значения не подставляются."
      />
    );
  }

  const selection = selectCampaign(overviewQuery.data, campaignId);
  if (selection.status === "empty") {
    return (
      <EmptyState
        title="Нет кампаний"
        description="В результате нет ни одной доступной кампании."
      />
    );
  }
  if (selection.status === "not-found") {
    return (
      <ErrorState
        title="Кампания не найдена"
        description="Выбранная кампания отсутствует в этом результате. Вернитесь к выбору кампании."
      />
    );
  }
  if (selection.status === "selection-required") {
    return (
      <Card as="section" className="campaign-selection">
        <h1>Выберите кампанию</h1>
        <p>Результат содержит несколько кампаний. Первая не выбирается автоматически.</p>
        <div className="campaign-selection__actions">
          {selection.campaigns.map((campaign) => (
            <Link
              key={campaign.campaign_id}
              to={`?campaignId=${encodeURIComponent(campaign.campaign_id)}`}
            >
              {campaign.passport.campaign_name}
            </Link>
          ))}
        </div>
      </Card>
    );
  }

  return <ResultOverview result={overviewQuery.data} campaign={selection.campaign} />;
}
