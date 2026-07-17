import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { CalculationHistoryV1 } from "../shared/api/generated/calculation-history-v1";
import { getCalculationHistory } from "../shared/api/product-navigation-client";
import { HistoryView } from "../features/product-navigation/HistoryView";
import {
  ProductNavigationLoading,
  ProductNavigationPageState,
} from "../features/product-navigation/ProductNavigationPageState";
import {
  historyQueryFromSearch,
  historySearchParams,
  navigationErrorCopy,
  navigationErrorMessage,
  navigationErrorStatus,
} from "../features/product-navigation/productNavigationModel";

export function CalculationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [lastSuccessfulHistory, setLastSuccessfulHistory] = useState<CalculationHistoryV1 | null>(null);
  const historyQueryState = historyQueryFromSearch(searchParams);
  const query = useQuery({
    queryKey: ["calculation-history-v1", historyQueryState],
    queryFn: async ({ signal }) => {
      const history = await getCalculationHistory(historyQueryState, signal);
      if (!signal.aborted) setLastSuccessfulHistory(history);
      return history;
    },
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

  const history = query.data ?? lastSuccessfulHistory;
  if (query.isPending && !history) {
    return <ProductNavigationLoading label="Загрузка истории расчетов" />;
  }
  if (!history) {
    return <ProductNavigationPageState error={query.error} onRetry={() => { void query.refetch(); }} />;
  }
  const errorCopy = query.error ? navigationErrorCopy(query.error) : null;
  const refreshMessage = query.error
    ? navigationErrorStatus(query.error) === 422
      ? `${navigationErrorMessage(query.error) ?? errorCopy?.description ?? "Проверьте выбранные фильтры."} Последний проверенный снимок сохранен.`
      : `${errorCopy?.description ?? "Не удалось обновить историю."} Последний проверенный снимок сохранен.`
    : null;
  return (
    <HistoryView
      key={[historyQueryState.search, historyQueryState.createdFrom, historyQueryState.createdTo].join("|")}
      history={history}
      query={historyQueryState}
      refreshMessage={refreshMessage}
      onQueryChange={(nextQuery) => setSearchParams(historySearchParams(nextQuery))}
      onRefresh={() => { void query.refetch(); }}
    />
  );
}
