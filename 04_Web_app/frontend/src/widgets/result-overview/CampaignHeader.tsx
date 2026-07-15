import type { ResultOverviewViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { formatDate, formatRub } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { PageHeader } from "../../shared/ui/PageHeader";
import { StatusBadge } from "../../shared/ui/StatusBadge";

interface CampaignHeaderProps {
  model: ResultOverviewViewModel;
}

export function CampaignHeader({ model }: CampaignHeaderProps) {
  const [startDate, endDate] = model.campaign.dateRange.split(" — ");
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
          <Button disabled title="Share API не подключён">Поделиться</Button>
          <Button variant="primary" disabled title="Download API не подключён">
            Скачать Excel
          </Button>
        </>
      }
    />
  );
}
