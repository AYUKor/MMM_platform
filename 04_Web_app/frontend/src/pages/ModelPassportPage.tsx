import { useQuery } from "@tanstack/react-query";
import { ModelOverviewView } from "../features/product-navigation/ModelOverviewView";
import {
  ProductNavigationLoading,
  ProductNavigationPageState,
} from "../features/product-navigation/ProductNavigationPageState";
import { navigationErrorCopy } from "../features/product-navigation/productNavigationModel";
import {
  getActiveModelPassportV2,
  getModelOverviewV2,
  UnsupportedBusinessSemanticsContractError,
} from "../shared/api/business-semantics-client";
import type { ModelOverviewV2 } from "../shared/api/generated/model-overview-v2";
import type { ModelPassportV2 } from "../shared/api/generated/model-passport-v2";

function modelContractsAgree(passport: ModelPassportV2, overview: ModelOverviewV2): boolean {
  return passport.serving.serving_policy_version === overview.serving.serving_policy_version
    && passport.serving.target_id === overview.serving.target_id
    && passport.serving.serving_targets_n === overview.serving.serving_targets_n
    && passport.serving.active_serving_models_n === overview.serving.active_serving_models_n
    && passport.serving.research_models_in_package_n === overview.serving.research_models_in_package_n
    && passport.serving.calculation_allowed === overview.summary.calculation_allowed
    && passport.data.training_period.start_date === overview.summary.training_period.start_date
    && passport.data.training_period.end_date === overview.summary.training_period.end_date;
}

export function ModelPassportPage() {
  const passportQuery = useQuery({
    queryKey: ["model-passport-v2"],
    queryFn: ({ signal }) => getActiveModelPassportV2(signal),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  const overviewQuery = useQuery({
    queryKey: ["model-overview-v2"],
    queryFn: ({ signal }) => getModelOverviewV2(signal),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

  const retry = () => {
    void Promise.all([passportQuery.refetch(), overviewQuery.refetch()]);
  };

  if (
    (passportQuery.isPending && !passportQuery.data)
    || (overviewQuery.isPending && !overviewQuery.data)
  ) {
    return <ProductNavigationLoading label="Загрузка сведений о модели" />;
  }

  if (!passportQuery.data || !overviewQuery.data) {
    return (
      <ProductNavigationPageState
        error={passportQuery.error ?? overviewQuery.error}
        onRetry={retry}
      />
    );
  }

  if (!modelContractsAgree(passportQuery.data, overviewQuery.data)) {
    return (
      <ProductNavigationPageState
        error={new UnsupportedBusinessSemanticsContractError()}
        onRetry={retry}
      />
    );
  }

  const refreshError = passportQuery.error ?? overviewQuery.error;
  const refreshMessage = refreshError
    ? `${navigationErrorCopy(refreshError).description} Последний проверенный снимок сохранен.`
    : null;

  return (
    <ModelOverviewView
      passport={passportQuery.data}
      overview={overviewQuery.data}
      refreshMessage={refreshMessage}
      onRefresh={retry}
    />
  );
}
