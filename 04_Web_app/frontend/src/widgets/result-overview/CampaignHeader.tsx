import type {
  DownloadViewModel,
  ResultOverviewViewModel,
} from "../../features/calculation-result/buildResultOverviewModel";
import { appEnv } from "../../shared/config/env";
import { formatDate, formatRub } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { PageHeader } from "../../shared/ui/PageHeader";
import { StatusBadge } from "../../shared/ui/StatusBadge";

interface CampaignHeaderProps {
  model: ResultOverviewViewModel;
  reportDownload: DownloadViewModel | null;
}

function artifactUrl(path: string): string {
  const baseUrl = appEnv.apiBaseUrl.replace(/\/+$/, "");
  return path.startsWith("http") ? path : `${baseUrl}${path.startsWith("/") ? "" : "/"}${path}`;
}

export function CampaignHeader({ model, reportDownload }: CampaignHeaderProps) {
  const downloadAvailable =
    appEnv.resultProvider === "http" && !model.demoData && reportDownload !== null;
  const downloadReport = () => {
    if (!downloadAvailable || !reportDownload) return;
    window.location.assign(artifactUrl(reportDownload.downloadPath));
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
          <span>{formatDate(model.campaign.sourceStartDate)} — {formatDate(model.campaign.sourceEndDate)}</span>
          <span>{formatRub(model.campaign.budgetRub)}</span>
          <span>{model.campaign.channelsCount} каналов</span>
          <span>{model.campaign.geographiesCount} гео</span>
        </>
      }
      actions={
        <>
          <Button disabled title="Публикация ссылки пока недоступна">
            Поделиться
          </Button>
          <Button
            variant="primary"
            disabled={!downloadAvailable}
            onClick={downloadReport}
            title={downloadAvailable ? "Скачать отчет для маркетолога" : "Excel-отчет недоступен или открыт демонстрационный результат"}
          >
            Скачать Excel
          </Button>
        </>
      }
    />
  );
}
