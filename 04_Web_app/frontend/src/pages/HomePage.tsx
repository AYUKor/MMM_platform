import { useQuery } from "@tanstack/react-query";
import { HomeView } from "../features/product-navigation/HomeView";
import {
  ProductNavigationLoading,
  ProductNavigationPageState,
} from "../features/product-navigation/ProductNavigationPageState";
import { navigationErrorCopy } from "../features/product-navigation/productNavigationModel";
import {
  getGeoCatalog,
  getWorkspaceGeoBudget,
} from "../shared/api/business-semantics-client";
import { getWorkspaceHome } from "../shared/api/product-navigation-client";

export function HomePage() {
  const homeQuery = useQuery({
    queryKey: ["workspace-home-v1"],
    queryFn: ({ signal }) => getWorkspaceHome(signal),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (state) => state.state.data?.active_calculations.length ? 5_000 : false,
    refetchIntervalInBackground: false,
  });
  const geoBudgetQuery = useQuery({
    queryKey: ["workspace-geo-budget-v1"],
    queryFn: ({ signal }) => getWorkspaceGeoBudget(signal),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  const geoCatalogQuery = useQuery({
    queryKey: ["geo-catalog-v1"],
    queryFn: ({ signal }) => getGeoCatalog(signal),
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const refresh = () => {
    void Promise.all([
      homeQuery.refetch(),
      geoBudgetQuery.refetch(),
      geoCatalogQuery.refetch(),
    ]);
  };

  if (homeQuery.isPending && !homeQuery.data) {
    return <ProductNavigationLoading label="Загрузка рабочего пространства" />;
  }
  if (!homeQuery.data) {
    return <ProductNavigationPageState error={homeQuery.error} onRetry={refresh} />;
  }

  const refreshMessage = homeQuery.error
    ? `${navigationErrorCopy(homeQuery.error).description} Последний проверенный снимок сохранен.`
    : null;

  return (
    <HomeView
      home={homeQuery.data}
      geoBudget={geoBudgetQuery.data ?? null}
      geoCatalog={geoCatalogQuery.data ?? null}
      geoLoading={geoBudgetQuery.isPending || geoCatalogQuery.isPending}
      geoUnavailable={Boolean(geoBudgetQuery.error || geoCatalogQuery.error)}
      refreshMessage={refreshMessage}
      onRefresh={refresh}
    />
  );
}
