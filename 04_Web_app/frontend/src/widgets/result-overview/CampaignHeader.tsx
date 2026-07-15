import type { ResultOverviewViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { appEnv } from "../../shared/config/env";
import { formatDate, formatRub } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { PageHeader } from "../../shared/ui/PageHeader";
import { StatusBadge } from "../../shared/ui/StatusBadge";

interface CampaignHeaderProps {
  model: ResultOverviewViewModel;
  reportArtifactId: string | null;
}

export function CampaignHeader({ model, reportArtifactId }: CampaignHeaderProps) {
  const [startDate, endDate] = model.campaign.dateRange.split(" — ");
  const downloadAvailable =
    appEnv.resultProvider === "http" && reportArtifactId !== null;
  const downloadReport = () => {
    if (!downloadAvailable) return;
    const baseUrl = appEnv.apiBaseUrl.replace(/\/+$/, "");
    window.location.assign(
      `${baseUrl}/api/v1/artifacts/${encodeURIComponent(reportArtifactId)}/download`,
    );
  };
  return (
    <PageHeader
      eyebrow={
        <>
          <span>Результат расчёта</span>
          {model.demoData ? (
            <StatusBadge tone="warning">Демонстрационные данные</StatusBadge>
          ) : null}
        </>
      }
      title={model.campaign.name}
      meta={
        <>
          <span>{model.campaign.segment}</span>
          <span>{formatDate(startDate ?? "")} — {formatDate(endDate ?? "")}</span>
          <span>{formatRub(model.campaign.budgetRub)}</span>
          <span>{model.campaign.channelsCount} каналов</span>
          <span>{model.campaign.geographiesCount} гео</span>
        </>
      }
      actions={
        <>
          <Button disabled title="Публикация ссылки будет подключена после authentication">
            Поделиться
          </Button>
          <Button
            variant="primary"
            disabled={!downloadAvailable}
            onClick={downloadReport}
            title={downloadAvailable ? "Скачать отчет для маркетолога" : "Excel-отчет недоступен"}
          >
            Скачать Excel
          </Button>
        </>
      }
    />
  );
}
