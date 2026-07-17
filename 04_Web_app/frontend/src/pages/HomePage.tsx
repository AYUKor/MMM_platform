import { useQuery } from "@tanstack/react-query";
import { HomeView } from "../features/product-navigation/HomeView";
import {
  ProductNavigationLoading,
  ProductNavigationPageState,
} from "../features/product-navigation/ProductNavigationPageState";
import { navigationErrorCopy } from "../features/product-navigation/productNavigationModel";
import { getWorkspaceHome } from "../shared/api/product-navigation-client";

export function HomePage() {
  const query = useQuery({
    queryKey: ["workspace-home-v1"],
    queryFn: ({ signal }) => getWorkspaceHome(signal),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (state) => state.state.data?.active_calculations.length ? 5_000 : false,
    refetchIntervalInBackground: false,
  });

  if (query.isPending && !query.data) {
    return <ProductNavigationLoading label="Загрузка рабочего пространства" />;
  }
  if (!query.data) {
    return <ProductNavigationPageState error={query.error} onRetry={() => { void query.refetch(); }} />;
  }

  const refreshMessage = query.error
    ? `${navigationErrorCopy(query.error).description} Последний проверенный снимок сохранен.`
    : null;
  return (
    <HomeView
      home={query.data}
      refreshMessage={refreshMessage}
      onRefresh={() => { void query.refetch(); }}
    />
  );
}
