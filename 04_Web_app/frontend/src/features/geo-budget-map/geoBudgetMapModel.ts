import type { HistoricalModelGeoBudgetV1 } from "../../shared/api/generated/historical-model-geo-budget-v1";
import type { ValidationResultV2 } from "../../shared/api/generated/validation-result-v2";
import { formatInteger, formatPercent, formatRub } from "../../shared/formatters/metrics";

export type GeoBudgetMapMode = "historical-model" | "campaign";

export interface GeoBudgetMapPoint {
  geoId: string;
  geoDisplayName: string;
  latitude: number;
  longitude: number;
  budgetRub: number;
  budgetShare: number | null;
  activeDaysN?: number;
  activeRowsN?: number;
  channels?: readonly string[];
  hasModelLimitations?: boolean;
  modelLimitationsN?: number;
}

export interface GeoBudgetMapUnlocatedGeography {
  geoId: string;
  geoDisplayName: string;
}

export interface GeoBudgetMapCoverage {
  status: "available" | "partial" | "unavailable";
  locatedGeographiesN: number;
  unlocatedGeographiesN: number;
  unlocatedGeographies: readonly GeoBudgetMapUnlocatedGeography[];
  locatedBudgetRub: number;
  unlocatedBudgetRub: number;
  unlocatedBudgetShare: number | null;
}

interface GeoBudgetMapModelBase {
  mode: GeoBudgetMapMode;
  points: readonly GeoBudgetMapPoint[];
  coverage: GeoBudgetMapCoverage;
  maxBudgetRub: number;
}

export interface HistoricalModelGeoBudgetMapModel extends GeoBudgetMapModelBase {
  mode: "historical-model";
  title: string;
  displayText: string;
  periodDisplayText: string;
  totalBudgetRub: number | null;
  geographiesN: number;
}

export interface CampaignGeoBudgetMapModel extends GeoBudgetMapModelBase {
  mode: "campaign";
  validationId: string;
  requestedBudgetRub: number;
  geographiesN: number;
}

export type GeoBudgetMapModel = HistoricalModelGeoBudgetMapModel | CampaignGeoBudgetMapModel;

export interface ProjectedGeoPoint {
  x: number;
  y: number;
}

export interface MapLabelLayoutPoint extends ProjectedGeoPoint {
  geoId: string;
  geoDisplayName: string;
  radius: number;
}

export interface MapLabelLayoutPosition extends ProjectedGeoPoint {
  width: number;
  height: number;
}

export class InvalidGeoBudgetMapDataError extends Error {
  constructor(message = "Geo budget map data is invalid.") {
    super(message);
    this.name = "InvalidGeoBudgetMapDataError";
  }
}

const DEG_TO_RAD = Math.PI / 180;
const ALBERS_LATITUDE_1 = 45 * DEG_TO_RAD;
const ALBERS_LATITUDE_2 = 70 * DEG_TO_RAD;
const ALBERS_CENTRAL_LONGITUDE = 100 * DEG_TO_RAD;
const ALBERS_LATITUDE_OF_ORIGIN = 55 * DEG_TO_RAD;
const ALBERS_N = (Math.sin(ALBERS_LATITUDE_1) + Math.sin(ALBERS_LATITUDE_2)) / 2;
const ALBERS_C = Math.cos(ALBERS_LATITUDE_1) ** 2 + 2 * ALBERS_N * Math.sin(ALBERS_LATITUDE_1);
const ALBERS_RHO_ORIGIN = albersRho(ALBERS_LATITUDE_OF_ORIGIN);

export const GEO_MAP_VIEWBOX = Object.freeze({ width: 1200, height: 680 });
export const GEO_MAP_PROJECTION = Object.freeze({
  name: "Albers Equal Area",
  latitude1: 45,
  latitude2: 70,
  centralLongitude: 100,
  latitudeOfOrigin: 55,
  radius: 1,
  scale: 880.2744673041848,
  offsetX: 659.5017197759643,
  offsetY: 522.4001925283919,
});

const RADIUS_LIMITS = Object.freeze({
  desktop: { min: 5, max: 22 },
  mobile: { min: 4, max: 16 },
});
const BRIGHTNESS_MIN = 0.42;
const BRIGHTNESS_MAX = 1;
const HISTORICAL_LABEL_LIMIT = 10;
const russianCollator = new Intl.Collator("ru", { sensitivity: "base" });

interface LabelRect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function labelRect(x: number, y: number, width: number, height: number): LabelRect {
  return {
    left: x - width / 2,
    right: x + width / 2,
    top: y - height / 2,
    bottom: y + height / 2,
  };
}

function rectanglesOverlap(left: LabelRect, right: LabelRect, gap: number): boolean {
  return left.left < right.right + gap
    && left.right > right.left - gap
    && left.top < right.bottom + gap
    && left.bottom > right.top - gap;
}

function rectTouchesMarker(
  rect: LabelRect,
  markerX: number,
  markerY: number,
  markerRadius: number,
): boolean {
  const closestX = Math.max(rect.left, Math.min(markerX, rect.right));
  const closestY = Math.max(rect.top, Math.min(markerY, rect.bottom));
  return (closestX - markerX) ** 2 + (closestY - markerY) ** 2
    < (markerRadius + 3) ** 2;
}

/**
 * Places HTML labels in rendered-canvas pixels, then returns fixed-viewBox
 * coordinates. The greedy search is deterministic and never changes marker
 * projection; leader lines carry labels that need a more distant free slot.
 */
export function layoutMapLabels(
  points: readonly MapLabelLayoutPoint[],
  canvasWidth: number,
): ReadonlyMap<string, MapLabelLayoutPosition> {
  const safeCanvasWidth = Number.isFinite(canvasWidth) && canvasWidth > 0
    ? Math.max(280, canvasWidth)
    : 1100;
  const canvasHeight = safeCanvasWidth * GEO_MAP_VIEWBOX.height / GEO_MAP_VIEWBOX.width;
  const scale = safeCanvasWidth / GEO_MAP_VIEWBOX.width;
  const compact = safeCanvasWidth <= 760;
  const margin = compact ? 5 : 8;
  const collisionGap = compact ? 3 : 6;
  const fontSize = compact ? 8.8 : 10.55;
  const maxLabelWidth = compact ? 132 : 190;
  const labelHeight = compact ? 18 : 21;
  const markerObstacles = points.map((point) => ({
    geoId: point.geoId,
    x: point.x * scale,
    y: point.y * scale,
    radius: Math.max(4, point.radius),
  }));
  const placed: LabelRect[] = [];
  const positions = new Map<string, MapLabelLayoutPosition>();

  const canPlace = (rect: LabelRect, ownGeoId: string) => {
    if (rect.left < margin || rect.right > safeCanvasWidth - margin) return false;
    if (rect.top < margin || rect.bottom > canvasHeight - margin) return false;
    if (placed.some((other) => rectanglesOverlap(rect, other, collisionGap))) return false;
    return !markerObstacles.some((marker) => (
      marker.geoId !== ownGeoId
      && rectTouchesMarker(rect, marker.x, marker.y, marker.radius)
    ));
  };

  for (const point of points) {
    const pointX = point.x * scale;
    const pointY = point.y * scale;
    const labelWidth = Math.min(
      maxLabelWidth,
      Math.max(compact ? 40 : 48, 14 + point.geoDisplayName.length * fontSize * 0.72),
    );
    const baseX = point.radius + 8 + labelWidth / 2;
    const baseY = point.radius + 7 + labelHeight / 2;
    const candidates: Array<{ x: number; y: number }> = [];
    const extraDistances = compact ? [0, 16, 32, 48, 68] : [0, 18, 36, 58, 82, 110];
    for (const extra of extraDistances) {
      candidates.push(
        { x: pointX + baseX + extra, y: pointY - baseY * 0.72 - extra * 0.18 },
        { x: pointX + baseX + extra, y: pointY + baseY * 0.72 + extra * 0.18 },
        { x: pointX - baseX - extra, y: pointY - baseY * 0.72 - extra * 0.18 },
        { x: pointX - baseX - extra, y: pointY + baseY * 0.72 + extra * 0.18 },
        { x: pointX + extra * 0.35, y: pointY - baseY - extra },
        { x: pointX - extra * 0.35, y: pointY + baseY + extra },
        { x: pointX + baseX + extra, y: pointY },
        { x: pointX - baseX - extra, y: pointY },
      );
    }

    let selected = candidates.find((candidate) => (
      canPlace(labelRect(candidate.x, candidate.y, labelWidth, labelHeight), point.geoId)
    ));

    if (!selected) {
      const laneXs = pointX < safeCanvasWidth / 2
        ? [margin + labelWidth / 2, safeCanvasWidth * 0.38, safeCanvasWidth * 0.62]
        : [safeCanvasWidth - margin - labelWidth / 2, safeCanvasWidth * 0.62, safeCanvasWidth * 0.38];
      const laneCandidates: Array<{ x: number; y: number }> = [];
      for (const x of laneXs) {
        for (let y = margin + labelHeight / 2; y <= canvasHeight - margin; y += labelHeight + collisionGap) {
          laneCandidates.push({ x, y });
        }
      }
      laneCandidates.sort((left, right) => (
        (left.x - pointX) ** 2 + (left.y - pointY) ** 2
        - ((right.x - pointX) ** 2 + (right.y - pointY) ** 2)
      ));
      selected = laneCandidates.find((candidate) => (
        canPlace(labelRect(candidate.x, candidate.y, labelWidth, labelHeight), point.geoId)
      ));
    }

    const fallback = selected ?? {
      x: Math.min(safeCanvasWidth - margin - labelWidth / 2, Math.max(margin + labelWidth / 2, pointX)),
      y: Math.min(canvasHeight - margin - labelHeight / 2, Math.max(margin + labelHeight / 2, pointY)),
    };
    const rect = labelRect(fallback.x, fallback.y, labelWidth, labelHeight);
    placed.push(rect);
    positions.set(point.geoId, {
      x: fallback.x / scale,
      y: fallback.y / scale,
      width: labelWidth / scale,
      height: labelHeight / scale,
    });
  }

  return positions;
}

function albersRho(latitude: number): number {
  return Math.sqrt(Math.max(0, ALBERS_C - 2 * ALBERS_N * Math.sin(latitude))) / ALBERS_N;
}

function wrapRadians(value: number): number {
  const fullTurn = 2 * Math.PI;
  return ((value + Math.PI) % fullTurn + fullTurn) % fullTurn - Math.PI;
}

function isFiniteInRange(value: number, minimum: number, maximum: number): boolean {
  return Number.isFinite(value) && value >= minimum && value <= maximum;
}

function assertNonNegativeFinite(value: number, field: string): void {
  if (!Number.isFinite(value) || value < 0) {
    throw new InvalidGeoBudgetMapDataError(`${field} must be a finite non-negative number.`);
  }
}

function assertShare(value: number | null, field: string): void {
  if (value !== null && (!Number.isFinite(value) || value < 0 || value > 1)) {
    throw new InvalidGeoBudgetMapDataError(`${field} must be null or a finite share from 0 to 1.`);
  }
}

function assertPoint(point: GeoBudgetMapPoint): void {
  if (!point.geoId.trim() || !point.geoDisplayName.trim()) {
    throw new InvalidGeoBudgetMapDataError("Map points require a geo id and display name.");
  }
  if (!projectGeoPoint(point.latitude, point.longitude)) {
    throw new InvalidGeoBudgetMapDataError("Map point coordinates are outside the supported WGS84 range.");
  }
  assertNonNegativeFinite(point.budgetRub, "budgetRub");
  assertShare(point.budgetShare, "budgetShare");
  if (point.activeDaysN !== undefined && (!Number.isSafeInteger(point.activeDaysN) || point.activeDaysN < 0)) {
    throw new InvalidGeoBudgetMapDataError("activeDaysN must be a non-negative integer.");
  }
  if (point.activeRowsN !== undefined && (!Number.isSafeInteger(point.activeRowsN) || point.activeRowsN < 0)) {
    throw new InvalidGeoBudgetMapDataError("activeRowsN must be a non-negative integer.");
  }
  if (
    point.activeDaysN !== undefined
    && point.activeRowsN !== undefined
    && point.activeDaysN > point.activeRowsN
  ) {
    throw new InvalidGeoBudgetMapDataError("activeDaysN cannot exceed activeRowsN.");
  }
  if (point.modelLimitationsN !== undefined && (!Number.isSafeInteger(point.modelLimitationsN) || point.modelLimitationsN < 0)) {
    throw new InvalidGeoBudgetMapDataError("modelLimitationsN must be a non-negative integer.");
  }
}

function coverageFromContract(
  coverage: HistoricalModelGeoBudgetV1["coverage"] | ValidationResultV2["map_coverage"],
): GeoBudgetMapCoverage {
  assertNonNegativeFinite(coverage.located_budget_rub, "located_budget_rub");
  assertNonNegativeFinite(coverage.unlocated_budget_rub, "unlocated_budget_rub");
  assertShare(coverage.unlocated_budget_share, "unlocated_budget_share");
  return {
    status: coverage.status,
    locatedGeographiesN: coverage.located_geographies_n,
    unlocatedGeographiesN: coverage.unlocated_geographies_n,
    unlocatedGeographies: coverage.unlocated_geographies.map((geo) => ({
      geoId: geo.geo_id,
      geoDisplayName: geo.geo_display_name,
    })),
    locatedBudgetRub: coverage.located_budget_rub,
    unlocatedBudgetRub: coverage.unlocated_budget_rub,
    unlocatedBudgetShare: coverage.unlocated_budget_share,
  };
}

function maxBudget(points: readonly GeoBudgetMapPoint[]): number {
  let maximum = 0;
  for (const point of points) {
    assertPoint(point);
    maximum = Math.max(maximum, point.budgetRub);
  }
  return maximum;
}

/** Fixed spherical Albers Equal Area projection shared by every map mode. */
export function projectGeoPoint(latitude: number, longitude: number): ProjectedGeoPoint | null {
  if (!isFiniteInRange(latitude, -90, 90) || !isFiniteInRange(longitude, -180, 180)) return null;
  const phi = latitude * DEG_TO_RAD;
  const lambda = longitude * DEG_TO_RAD;
  const theta = ALBERS_N * wrapRadians(lambda - ALBERS_CENTRAL_LONGITUDE);
  const rho = albersRho(phi);
  const projectedX = rho * Math.sin(theta);
  const projectedY = ALBERS_RHO_ORIGIN - rho * Math.cos(theta);
  const x = GEO_MAP_PROJECTION.offsetX + GEO_MAP_PROJECTION.scale * projectedX;
  const y = GEO_MAP_PROJECTION.offsetY - GEO_MAP_PROJECTION.scale * projectedY;
  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
}

export function bubbleRadius(budget: number, maxBudget: number, mobile = false): number {
  if (!Number.isFinite(budget) || !Number.isFinite(maxBudget) || budget <= 0 || maxBudget <= 0) return 0;
  const limits = mobile ? RADIUS_LIMITS.mobile : RADIUS_LIMITS.desktop;
  const normalized = Math.sqrt(Math.min(budget, maxBudget) / maxBudget);
  return limits.min + normalized * (limits.max - limits.min);
}

export function bubbleBrightness(budget: number, maxBudget: number): number {
  if (!Number.isFinite(budget) || !Number.isFinite(maxBudget) || budget <= 0 || maxBudget <= 0) return 0;
  const normalized = Math.sqrt(Math.min(budget, maxBudget) / maxBudget);
  return BRIGHTNESS_MIN + normalized * (BRIGHTNESS_MAX - BRIGHTNESS_MIN);
}

export function sortPointsForPaint(points: readonly GeoBudgetMapPoint[]): GeoBudgetMapPoint[] {
  points.forEach(assertPoint);
  return [...points].sort((left, right) =>
    left.budgetRub - right.budgetRub
    || russianCollator.compare(left.geoDisplayName, right.geoDisplayName)
    || left.geoId.localeCompare(right.geoId),
  );
}

export function selectLabelIds(
  mode: GeoBudgetMapMode,
  points: readonly GeoBudgetMapPoint[],
): ReadonlySet<string> {
  points.forEach(assertPoint);
  if (mode === "campaign") return new Set(points.map((point) => point.geoId));
  const top = [...points]
    .sort((left, right) =>
      right.budgetRub - left.budgetRub
      || russianCollator.compare(left.geoDisplayName, right.geoDisplayName)
      || left.geoId.localeCompare(right.geoId),
    )
    .slice(0, HISTORICAL_LABEL_LIMIT);
  return new Set(top.map((point) => point.geoId));
}

export function formatGeoPointAccessibleLabel(
  mode: GeoBudgetMapMode,
  point: GeoBudgetMapPoint,
  periodDisplayText?: string,
): string {
  assertPoint(point);
  const parts = [
    point.geoDisplayName,
    `${mode === "historical-model" ? "Исторический рекламный бюджет" : "Бюджет"}: ${formatRub(point.budgetRub)}`,
    `${mode === "historical-model" ? "Доля общего бюджета" : "Доля бюджета"}: ${formatPercent(point.budgetShare)}`,
  ];
  if (mode === "historical-model") {
    parts.push(`Дней с рекламной активностью: ${formatInteger(point.activeDaysN ?? null)}`);
    parts.push(periodDisplayText?.trim() || "Период данных: Нет данных");
  } else {
    parts.push(`Каналы: ${point.channels?.length ? point.channels.join(", ") : "Нет данных"}`);
    const limitations = point.hasModelLimitations === undefined
      ? "Нет данных"
      : point.hasModelLimitations
        ? formatInteger(point.modelLimitationsN ?? null)
        : "нет";
    parts.push(`Ограничения модели: ${limitations}`);
  }
  return `${parts.join(". ")}.`;
}

export function adaptHistoricalModelGeoBudget(
  payload: HistoricalModelGeoBudgetV1,
): HistoricalModelGeoBudgetMapModel {
  const points: GeoBudgetMapPoint[] = payload.rows.flatMap((row) =>
    row.coordinates_status === "canonical"
      ? [{
        geoId: row.geo_id,
        geoDisplayName: row.geo_display_name,
        latitude: row.latitude,
        longitude: row.longitude,
        budgetRub: row.historical_total_budget_rub,
        budgetShare: row.budget_share,
        activeDaysN: row.active_days_n,
        activeRowsN: row.active_rows_n,
      }]
      : [],
  );
  if (payload.total_budget_rub !== null) {
    assertNonNegativeFinite(payload.total_budget_rub, "total_budget_rub");
  } else if (payload.status !== "unavailable") {
    throw new InvalidGeoBudgetMapDataError("total_budget_rub is required for an available historical artifact.");
  }
  if (!payload.period_display_text.trim()) {
    throw new InvalidGeoBudgetMapDataError("period_display_text must not be empty.");
  }
  return {
    mode: "historical-model",
    title: payload.title,
    displayText: payload.display_text,
    periodDisplayText: payload.period_display_text,
    totalBudgetRub: payload.total_budget_rub,
    geographiesN: payload.geographies_n,
    points,
    coverage: coverageFromContract(payload.coverage),
    maxBudgetRub: maxBudget(points),
  };
}

export function adaptValidationGeoBudget(payload: ValidationResultV2): CampaignGeoBudgetMapModel {
  const points: GeoBudgetMapPoint[] = payload.geo_points.flatMap((point) =>
    point.coordinates_status === "canonical"
      ? [{
        geoId: point.geo_id,
        geoDisplayName: point.geo_display_name,
        latitude: point.latitude,
        longitude: point.longitude,
        budgetRub: point.budget_rub,
        budgetShare: point.budget_share,
        channels: point.channels.map((channel) => channel.channel_display_name),
        hasModelLimitations: point.has_model_limitations,
        modelLimitationsN: point.model_limitations_n,
      }]
      : [],
  );
  assertNonNegativeFinite(payload.file_validation.requested_budget_rub, "requested_budget_rub");
  return {
    mode: "campaign",
    validationId: payload.validation_id,
    requestedBudgetRub: payload.file_validation.requested_budget_rub,
    geographiesN: payload.file_validation.geographies_n,
    points,
    coverage: coverageFromContract(payload.map_coverage),
    maxBudgetRub: maxBudget(points),
  };
}
