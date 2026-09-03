import type { ValidationResultV2 } from "../shared/api/generated/validation-result-v2";

export interface ExplicitLocalPlacement {
  geoDisplayName: string;
  budgetRub: number;
}

export const D1R2_MIXED_WARNING =
  "В плане одновременно указаны федеральный бюджет и отдельные локальные бюджеты. Локальные суммы будут добавлены поверх федерального распределения.";

function requirePositivePlacements(placements: readonly ExplicitLocalPlacement[]): void {
  if (
    placements.some(({ geoDisplayName, budgetRub }) =>
      geoDisplayName.trim().length === 0 || !Number.isFinite(budgetRub) || budgetRub <= 0)
    || new Set(placements.map(({ geoDisplayName }) => geoDisplayName)).size !== placements.length
  ) {
    throw new Error("D1R2 placements must have unique names and positive finite budgets.");
  }
}

function reconcileShares(validation: ValidationResultV2): void {
  const total = validation.file_validation.requested_budget_rub;
  for (const point of validation.geo_points) {
    point.budget_share = total === 0 ? null : point.budget_rub / total;
  }
}

/**
 * Derives a backend-shaped mixed-plan response from the exact federal-only
 * production control. The helper deliberately writes all totals and shares
 * into the payload so frontend tests never reproduce allocator mathematics.
 */
export function buildD1r2AvailableMixedValidation(
  federalOnly: ValidationResultV2,
  placements: readonly ExplicitLocalPlacement[],
  federalSourceRowsCount = 1,
): ValidationResultV2 {
  requirePositivePlacements(placements);
  if (!Number.isSafeInteger(federalSourceRowsCount) || federalSourceRowsCount < 1) {
    throw new Error("D1R2 federal source row count must be a positive integer.");
  }

  const validation = structuredClone(federalOnly);
  if (validation.federal_allocation.status !== "available" || validation.federal_allocation.breakdown.length !== 1) {
    throw new Error("D1R2 mixed fixtures require the exact one-direction federal control.");
  }

  const explicitBudget = placements.reduce((sum, placement) => sum + placement.budgetRub, 0);
  const requestedBudget = validation.federal_allocation.source_budget_rub + explicitBudget;

  for (const placement of placements) {
    const point = validation.geo_points.find(({ geo_display_name: name }) => name === placement.geoDisplayName);
    if (!point || point.coordinates_status !== "canonical") {
      throw new Error(`D1R2 available geography is absent from the federal allocation: ${placement.geoDisplayName}`);
    }
    point.input_geo_name = placement.geoDisplayName;
    point.budget_rub += placement.budgetRub;
  }

  validation.status = "warning";
  validation.job_creation_allowed = true;
  validation.file_validation.rows_n = federalSourceRowsCount + placements.length;
  validation.file_validation.requested_budget_rub = requestedBudget;
  validation.file_validation.blocking_errors_n = 0;
  validation.federal_allocation.source_rows_count = federalSourceRowsCount;
  validation.federal_allocation.mixed_local_overlap = true;
  validation.federal_allocation.warnings = [{
    code: "FEDERAL_AND_LOCAL_GEO_OVERLAP",
    display_text: D1R2_MIXED_WARNING,
  }];
  validation.federal_allocation.breakdown[0].source_rows_count = federalSourceRowsCount;
  validation.map_coverage = {
    status: "available",
    located_geographies_n: validation.geo_points.length,
    unlocated_geographies_n: 0,
    unlocated_geographies: [],
    located_budget_rub: requestedBudget,
    unlocated_budget_rub: 0,
    unlocated_budget_share: 0,
  };
  reconcileShares(validation);
  return validation;
}

/** Builds a backend-shaped blocking response for one unavailable explicit geo. */
export function buildD1r2UnavailableMixedValidation(
  federalOnly: ValidationResultV2,
  availablePlacements: readonly ExplicitLocalPlacement[],
  unavailablePlacement: ExplicitLocalPlacement,
): ValidationResultV2 {
  requirePositivePlacements([...availablePlacements, unavailablePlacement]);
  const validation = buildD1r2AvailableMixedValidation(federalOnly, availablePlacements);
  const channel = validation.federal_allocation.channels[0];
  const unavailableGeoId = "geo_ffffffffffffffff";
  const requestedBudget = validation.file_validation.requested_budget_rub + unavailablePlacement.budgetRub;

  validation.status = "warning";
  validation.job_creation_allowed = false;
  validation.file_validation.rows_n += 1;
  validation.file_validation.geographies_n += 1;
  validation.file_validation.requested_budget_rub = requestedBudget;
  validation.geo_points.push({
    geo_id: unavailableGeoId,
    geo_display_name: unavailablePlacement.geoDisplayName,
    input_geo_name: unavailablePlacement.geoDisplayName,
    canonical_geo_id: null,
    canonical_geo_display_name: null,
    normalization_status: "unknown",
    normalization_rule: "no_forecast_ready_geography",
    latitude: null,
    longitude: null,
    coordinates_status: "unavailable",
    region_id: null,
    region_display_name: null,
    budget_rub: unavailablePlacement.budgetRub,
    budget_share: unavailablePlacement.budgetRub / requestedBudget,
    channels: [channel],
    has_model_limitations: true,
    model_limitations_n: 1,
  });
  validation.model_limitations.push({
    target: "turnover",
    channel_id: channel.channel_id,
    channel_display_name: channel.channel_display_name,
    limitation_type: "explicit_local_geography_unavailable",
    affected_geos_n: 1,
    affected_geos: [unavailablePlacement.geoDisplayName],
    severity: "blocking",
    allowed_use: "unavailable",
    blocks_calculation: true,
    what: `География «${unavailablePlacement.geoDisplayName}» недоступна для расчета на выбранный период.`,
    why: "Для явно указанной локальной географии нет forecast-ready модели.",
    recommended_action: "Измените географию или период кампании и повторите проверку.",
  });
  validation.map_coverage = {
    status: "partial",
    located_geographies_n: validation.geo_points.length - 1,
    unlocated_geographies_n: 1,
    unlocated_geographies: [{
      geo_id: unavailableGeoId,
      geo_display_name: unavailablePlacement.geoDisplayName,
    }],
    located_budget_rub: requestedBudget - unavailablePlacement.budgetRub,
    unlocated_budget_rub: unavailablePlacement.budgetRub,
    unlocated_budget_share: unavailablePlacement.budgetRub / requestedBudget,
  };
  reconcileShares(validation);
  return validation;
}
