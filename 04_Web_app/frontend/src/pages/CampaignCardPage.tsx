import { useQuery } from "@tanstack/react-query";
import { useLocation, useParams } from "react-router-dom";
import { CampaignCardView } from "../features/campaign-catalog/CampaignCardView";
import { CampaignCatalogPageState } from "../features/campaign-catalog/CampaignCatalogPageState";
import { ProductNavigationLoading } from "../features/product-navigation/ProductNavigationPageState";
import { CampaignNotFoundError, getCampaignCard } from "../shared/api/campaign-catalog-client";

function campaignNumber(value: string | undefined): number | null {
  if (!value || !/^[1-9][0-9]{0,3}$/.test(value)) return null;
  return Number(value);
}

export function CampaignCardPage() {
  const params = useParams();
  const location = useLocation();
  const number = campaignNumber(params.number);
  const query = useQuery({
    queryKey: ["campaign-card-v1", number],
    queryFn: ({ signal }) => getCampaignCard(number as number, signal),
    enabled: number !== null,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const backLink = `/campaigns${location.search}`;
  if (number === null) return <CampaignCatalogPageState error={new CampaignNotFoundError()} onRetry={() => undefined} backLink={backLink} />;
  if (query.isPending) return <ProductNavigationLoading label="Загрузка карточки кампании" />;
  if (!query.data) return <CampaignCatalogPageState error={query.error} onRetry={() => { void query.refetch(); }} backLink={backLink} />;
  return <CampaignCardView card={query.data} backLink={backLink} />;
}
