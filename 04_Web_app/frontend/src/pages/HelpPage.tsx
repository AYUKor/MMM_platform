import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { HelpCatalogView } from "../features/product-navigation/HelpCatalogView";
import {
  ProductNavigationLoading,
  ProductNavigationPageState,
} from "../features/product-navigation/ProductNavigationPageState";
import {
  helpSearchParams,
  helpSelectionFromSearch,
  navigationErrorCopy,
} from "../features/product-navigation/productNavigationModel";
import { getHelpCatalog } from "../shared/api/product-navigation-client";

export function HelpPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useQuery({
    queryKey: ["help-catalog-v1"],
    queryFn: ({ signal }) => getHelpCatalog(signal),
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const selection = query.data
    ? helpSelectionFromSearch(query.data, searchParams)
    : null;

  useEffect(() => {
    if (!selection) return;
    const canonical = helpSearchParams(selection);
    if (canonical.toString() !== searchParams.toString()) {
      setSearchParams(canonical, { replace: true });
    }
  }, [searchParams, selection, setSearchParams]);

  if (query.isPending && !query.data) {
    return <ProductNavigationLoading label="Загрузка справки" />;
  }
  if (!query.data || !selection) {
    return <ProductNavigationPageState error={query.error} onRetry={() => { void query.refetch(); }} />;
  }
  const refreshMessage = query.error
    ? `${navigationErrorCopy(query.error).description} Последний проверенный снимок сохранен.`
    : null;
  return (
    <HelpCatalogView
      catalog={query.data}
      selection={selection}
      refreshMessage={refreshMessage}
      onSelectionChange={(nextSelection) => setSearchParams(helpSearchParams(nextSelection))}
      onRefresh={() => { void query.refetch(); }}
    />
  );
}
