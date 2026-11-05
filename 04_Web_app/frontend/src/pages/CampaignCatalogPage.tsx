import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../features/auth/AuthProvider";
import {
  CampaignCatalogUnpublished,
  CampaignCatalogView,
} from "../features/campaign-catalog/CampaignCatalogView";
import { CampaignCatalogPageState } from "../features/campaign-catalog/CampaignCatalogPageState";
import {
  filtersFromSearch,
  filtersToSearch,
} from "../features/campaign-catalog/campaignCatalogModel";
import { ProductNavigationLoading } from "../features/product-navigation/ProductNavigationPageState";
import {
  campaignCatalogDownloadUrl,
  getCampaignCatalog,
} from "../shared/api/campaign-catalog-client";

const CAMPAIGN_CATALOG_QUERY_KEY = ["campaign-catalog-v1"] as const;

export function CampaignCatalogPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = filtersFromSearch(searchParams);
  const query = useQuery({
    queryKey: CAMPAIGN_CATALOG_QUERY_KEY,
    queryFn: ({ signal }) => getCampaignCatalog(signal),
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  if (query.isPending) return <ProductNavigationLoading label="Загрузка каталога прошлых кампаний" />;
  if (!query.data) return <CampaignCatalogPageState error={query.error} onRetry={() => { void query.refetch(); }} />;
  const catalog = query.data;
  if (catalog.status === "unavailable") return <CampaignCatalogUnpublished displayText={catalog.display_text} />;

  const listSearch = location.search;
  return (
    <CampaignCatalogView
      catalog={catalog}
      filters={filters}
      onFiltersChange={(next) => setSearchParams(filtersToSearch(next), { replace: true })}
      canDownload={auth.can("report.download")}
      downloadUrl={campaignCatalogDownloadUrl()}
      cardLink={(number) => `/campaigns/${number}${listSearch}`}
      onOpen={(number) => navigate(`/campaigns/${number}${listSearch}`)}
    />
  );
}
