import { useQuery } from "@tanstack/react-query";
import { HomeView } from "../features/product-navigation/HomeView";
import {
  ProductNavigationLoading,
  ProductNavigationPageState,
} from "../features/product-navigation/ProductNavigationPageState";
import { navigationErrorCopy } from "../features/product-navigation/productNavigationModel";
import {
  getHistoricalModelGeoBudget,
  UnsupportedBusinessSemanticsContractError,
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
  const historicalGeoBudgetQuery = useQuery({
    queryKey: ["historical-model-geo-budget-v1"],
    // Keep the first request alive across React development remounts so one
    // Home load produces one backend call instead of an aborted duplicate.
    queryFn: () => getHistoricalModelGeoBudget(),
    retry: false,
    staleTime: 0,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  const refresh = () => {
    void Promise.all([
      homeQuery.refetch(),
      historicalGeoBudgetQuery.refetch(),
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
  const geoRequestState = historicalGeoBudgetQuery.data
    ? "ready"
    : historicalGeoBudgetQuery.isPending
      ? "loading"
      : historicalGeoBudgetQuery.error instanceof UnsupportedBusinessSemanticsContractError
        ? "unsupported-contract"
        : "network-error";

  return (
    <HomeView
      home={homeQuery.data}
      historicalGeoBudget={historicalGeoBudgetQuery.data ?? null}
      geoRequestState={geoRequestState}
      refreshMessage={refreshMessage}
      onRefresh={refresh}
    />
  );
}
