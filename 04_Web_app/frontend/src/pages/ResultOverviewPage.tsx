import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { selectCampaign } from "../features/calculation-result/selectCampaign";
import { PermissionDeniedPage } from "./PermissionDeniedPage";
import { createResultProvider } from "../shared/api/provider-factory";
import { Card } from "../shared/ui/Card";
import { EmptyState } from "../shared/ui/EmptyState";
import { ErrorState } from "../shared/ui/ErrorState";
import { LoadingSkeleton } from "../shared/ui/LoadingSkeleton";
import { ResultOverview } from "../widgets/result-overview/ResultOverview";

const resultProvider = createResultProvider();

export function ResultOverviewPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const forcedState = import.meta.env.DEV ? searchParams.get("state") : null;
  const campaignId = searchParams.get("campaignId");

  const query = useQuery({
    queryKey: ["decision-result", id, resultProvider.kind],
    queryFn: () => resultProvider.getResult(id ?? ""),
    enabled: Boolean(id) && forcedState === null,
  });

  if (forcedState === "loading" || query.isLoading) return <LoadingSkeleton />;
  if (forcedState === "permission") return <PermissionDeniedPage />;
  if (forcedState === "unavailable") {
    return (
      <EmptyState
        title="Результат недоступен"
        description="Backend не вернул доступный результат для этого расчёта."
      />
    );
  }
  if (forcedState === "error" || query.isError) {
    return (
      <ErrorState
        title="Не удалось загрузить результат"
        description={
          query.error instanceof Error
            ? query.error.message
            : "Повторите попытку после восстановления соединения."
        }
      />
    );
  }

  if (!query.data) {
    return (
      <EmptyState
        title="Нет данных"
        description="DecisionResult отсутствует. Нулевые значения не подставляются."
      />
    );
  }

  const selection = selectCampaign(query.data, campaignId);
  if (selection.status === "empty") {
    return (
      <EmptyState
        title="Нет кампаний"
        description="DecisionResult не содержит campaign_results."
      />
    );
  }
  if (selection.status === "not-found") {
    return (
      <ErrorState
        title="Кампания не найдена"
        description={`В результате нет campaign_id ${selection.requestedCampaignId}.`}
      />
    );
  }
  if (selection.status === "selection-required") {
    return (
      <Card as="section" className="campaign-selection">
        <h1>Выберите кампанию</h1>
        <p>Результат содержит несколько кампаний. Автоматически первая не выбирается.</p>
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

  return (
    <ResultOverview result={query.data} campaign={selection.campaign} />
  );
}
