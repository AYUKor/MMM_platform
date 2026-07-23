import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type RefObject,
} from "react";
import russiaOutline from "../../assets/maps/russia-outline-v1.svg?raw";
import { formatInteger, formatPercent, formatRub } from "../../shared/formatters/metrics";
import {
  GEO_MAP_VIEWBOX,
  bubbleBrightness,
  bubbleRadius,
  formatGeoPointAccessibleLabel,
  layoutMapLabels,
  projectGeoPoint,
  selectLabelIds,
  sortPointsForPaint,
  type GeoBudgetMapModel,
  type GeoBudgetMapPoint,
  type GeoBudgetMapMode,
} from "./geoBudgetMapModel";
import styles from "./geo-budget-map.module.css";

export type GeoBudgetMapRequestState =
  | "ready"
  | "loading"
  | "network-error"
  | "unsupported-contract";

interface GeoBudgetMapProps {
  model: GeoBudgetMapModel | null;
  requestState?: GeoBudgetMapRequestState;
  onRetry?: () => void;
}

interface ProjectedMapPoint {
  point: GeoBudgetMapPoint;
  x: number;
  y: number;
  radius: number;
  mobileRadius: number;
  brightness: number;
  label: boolean;
  labelPriority: number;
  labelX: number;
  labelY: number;
}

interface ActivePoint {
  projected: ProjectedMapPoint;
  trigger: HTMLButtonElement;
}

const OUTLINE_IS_TRUSTED_LOCAL_ASSET =
  !/<script|<foreignObject|(?:href|src)\s*=/i.test(russiaOutline);

function stateCopy(state: Exclude<GeoBudgetMapRequestState, "ready">) {
  if (state === "loading") {
    return {
      title: "Загружаем карту бюджета",
      description: "Получаем координаты и готовую сводку сервиса.",
      tone: "neutral",
    } as const;
  }
  if (state === "unsupported-contract") {
    return {
      title: "Формат данных карты не поддерживается",
      description: "Карта скрыта, чтобы не показывать непроверенные координаты или бюджеты.",
      tone: "danger",
    } as const;
  }
  return {
    title: "Не удалось загрузить карту",
    description: "Остальные сведения на странице сохранены. Повторите запрос.",
    tone: "danger",
  } as const;
}

function MapState({
  state,
  title,
  description,
  onRetry,
}: {
  state: string;
  title: string;
  description: string;
  onRetry?: () => void;
}) {
  return (
    <div className={styles.state} data-state={state} role="status" aria-live="polite">
      <span className={styles.stateMark} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
        {onRetry ? (
          <button className={styles.retryButton} type="button" onClick={onRetry}>
            Повторить
          </button>
        ) : null}
      </div>
    </div>
  );
}

function pointStyle(projected: ProjectedMapPoint): CSSProperties {
  return {
    "--point-x": String((projected.x / GEO_MAP_VIEWBOX.width) * 100) + "%",
    "--point-y": String((projected.y / GEO_MAP_VIEWBOX.height) * 100) + "%",
    "--bubble-size": String(projected.radius * 2) + "px",
    "--bubble-mobile-size": String(projected.mobileRadius * 2) + "px",
    "--bubble-brightness": projected.brightness,
  } as CSSProperties;
}

function labelStyle(projected: ProjectedMapPoint): CSSProperties {
  return {
    "--label-x": String((projected.labelX / GEO_MAP_VIEWBOX.width) * 100) + "%",
    "--label-y": String((projected.labelY / GEO_MAP_VIEWBOX.height) * 100) + "%",
  } as CSSProperties;
}

const MarkerLayer = memo(function MarkerLayer({
  mode,
  points,
  periodDisplayText,
  onActivate,
  onFocusActivate,
  onHoverEnd,
}: {
  mode: GeoBudgetMapMode;
  points: readonly ProjectedMapPoint[];
  periodDisplayText?: string;
  onActivate: (projected: ProjectedMapPoint, trigger: HTMLButtonElement) => void;
  onFocusActivate: (projected: ProjectedMapPoint, trigger: HTMLButtonElement) => void;
  onHoverEnd: (geoId: string, trigger: HTMLButtonElement) => void;
}) {
  return (
    <>
      <div className={styles.markerLayer}>
        {points.filter((item) => item.point.budgetRub > 0).map((projected, index) => (
          <button
            className={styles.marker}
            data-map-marker={projected.point.geoId}
            data-budget-rub={projected.point.budgetRub}
            data-paint-order={index}
            key={projected.point.geoId}
            type="button"
            style={pointStyle(projected)}
            aria-label={formatGeoPointAccessibleLabel(mode, projected.point, periodDisplayText)}
            onMouseEnter={(event) => onActivate(projected, event.currentTarget)}
            onMouseLeave={(event) => onHoverEnd(projected.point.geoId, event.currentTarget)}
            onFocus={(event) => onFocusActivate(projected, event.currentTarget)}
            onClick={(event) => onActivate(projected, event.currentTarget)}
          >
            <span className={styles.glow} aria-hidden="true" />
            <span className={styles.bubble} aria-hidden="true">
              <span />
            </span>
          </button>
        ))}
      </div>
      <svg
        className={styles.leaderLayer}
        viewBox={`0 0 ${GEO_MAP_VIEWBOX.width} ${GEO_MAP_VIEWBOX.height}`}
        preserveAspectRatio="xMidYMid meet"
        aria-hidden="true"
      >
        {points.filter((item) => item.label && item.point.budgetRub > 0).map((projected) => (
          <line
            data-map-leader={projected.point.geoId}
            data-mobile-visible={projected.labelPriority < 5 ? "true" : "false"}
            key={projected.point.geoId}
            x1={projected.x}
            y1={projected.y}
            x2={projected.labelX}
            y2={projected.labelY}
          />
        ))}
      </svg>
      <div className={styles.labelLayer} aria-hidden="true">
        {points.filter((item) => item.label && item.point.budgetRub > 0).map((projected) => (
          <span
            className={styles.label}
            data-map-label={projected.point.geoId}
            data-label-priority={projected.labelPriority}
            data-mobile-visible={projected.labelPriority < 5 ? "true" : "false"}
            key={projected.point.geoId}
            style={labelStyle(projected)}
          >
            {projected.point.geoDisplayName}
          </span>
        ))}
      </div>
    </>
  );
});

function Tooltip({
  mode,
  active,
  periodDisplayText,
  onClose,
}: {
  mode: GeoBudgetMapMode;
  active: ActivePoint;
  periodDisplayText?: string;
  onClose: () => void;
}) {
  const point = active.projected.point;
  const position = {
    "--tooltip-x": String((active.projected.x / GEO_MAP_VIEWBOX.width) * 100) + "%",
    "--tooltip-y": String((active.projected.y / GEO_MAP_VIEWBOX.height) * 100) + "%",
  } as CSSProperties;
  const limitationText = point.hasModelLimitations === undefined
    ? "Нет данных"
    : point.hasModelLimitations
      ? formatInteger(point.modelLimitationsN ?? null)
      : "Нет";
  const periodValue = periodDisplayText?.replace(/^Период данных:\s*/u, "").trim()
    || "Нет данных";
  return (
    <aside
      className={styles.tooltip}
      data-map-tooltip={point.geoId}
      role="tooltip"
      style={position}
    >
      <div className={styles.tooltipHeader}>
        <strong>{point.geoDisplayName}</strong>
        <button type="button" onClick={onClose} aria-label="Закрыть подсказку">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d="M5 5l10 10M15 5L5 15" />
          </svg>
        </button>
      </div>
      <dl>
        <div>
          <dt>{mode === "historical-model" ? "Исторический рекламный бюджет" : "Бюджет"}</dt>
          <dd>{formatRub(point.budgetRub)}</dd>
        </div>
        <div>
          <dt>{mode === "historical-model" ? "Доля общего бюджета" : "Доля бюджета"}</dt>
          <dd>{formatPercent(point.budgetShare)}</dd>
        </div>
        {mode === "historical-model" ? (
          <>
            <div>
              <dt>Период данных</dt>
              <dd>{periodValue}</dd>
            </div>
          </>
        ) : (
          <>
            <div>
              <dt>Каналы</dt>
              <dd>{point.channels?.length ? point.channels.join(", ") : "Нет данных"}</dd>
            </div>
            <div>
              <dt>Ограничения модели</dt>
              <dd>{limitationText}</dd>
            </div>
          </>
        )}
      </dl>
    </aside>
  );
}

function CoverageNotice({ model }: { model: GeoBudgetMapModel }) {
  if (model.coverage.status !== "partial") return null;
  return (
    <section className={styles.coverageNotice} aria-labelledby={"map-coverage-" + model.mode}>
      <div>
        <span className={styles.coverageBadge}>Частичное покрытие</span>
        <h3 id={"map-coverage-" + model.mode}>
          Не удалось разместить географий: {formatInteger(model.coverage.unlocatedGeographiesN)}
        </h3>
        <p>
          Неразмещенный бюджет: {formatRub(model.coverage.unlocatedBudgetRub)}
          {" · "}
          доля: {formatPercent(model.coverage.unlocatedBudgetShare)}
        </p>
      </div>
      {model.coverage.unlocatedGeographies.length ? (
        <details>
          <summary>Показать географии</summary>
          <ul>
            {model.coverage.unlocatedGeographies.map((geo) => (
              <li key={geo.geoId}>{geo.geoDisplayName}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

function Attribution() {
  return (
    <div className={styles.attribution}>
      <span>Координаты городов: GeoNames, CC BY 4.0.</span>
      <span>Контур карты: Natural Earth, public domain.</span>
    </div>
  );
}

function useCanvasWidth(
  canvasRef: RefObject<HTMLDivElement | null>,
  observeKey: unknown,
) {
  const [width, setWidth] = useState(1100);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const update = () => {
      const nextWidth = Math.round(canvas.getBoundingClientRect().width);
      if (nextWidth > 0) setWidth((current) => current === nextWidth ? current : nextWidth);
    };
    update();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(update);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [canvasRef, observeKey]);
  return width;
}

export function GeoBudgetMap({
  model,
  requestState = "ready",
  onRetry,
}: GeoBudgetMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const activeTriggerRef = useRef<HTMLButtonElement | null>(null);
  const suppressFocusActivationRef = useRef(false);
  const [active, setActive] = useState<ActivePoint | null>(null);
  const [showMobileCampaignLabels, setShowMobileCampaignLabels] = useState(false);
  const canvasWidth = useCanvasWidth(canvasRef, requestState === "ready" ? model : null);
  const mobileLayout = canvasWidth <= 760;

  const closeTooltip = useCallback((restoreFocus = true) => {
    const trigger = activeTriggerRef.current;
    if (restoreFocus && trigger) suppressFocusActivationRef.current = true;
    setActive(null);
    if (restoreFocus && trigger) {
      trigger.focus({ preventScroll: true });
      queueMicrotask(() => {
        suppressFocusActivationRef.current = false;
      });
    }
  }, []);

  const activate = useCallback((projected: ProjectedMapPoint, trigger: HTMLButtonElement) => {
    activeTriggerRef.current = trigger;
    setActive({ projected, trigger });
  }, []);

  const focusActivate = useCallback((
    projected: ProjectedMapPoint,
    trigger: HTMLButtonElement,
  ) => {
    if (suppressFocusActivationRef.current) return;
    activate(projected, trigger);
  }, [activate]);

  const hoverEnd = useCallback((geoId: string, trigger: HTMLButtonElement) => {
    if (document.activeElement === trigger) return;
    setActive((current) => {
      if (current?.projected.point.geoId !== geoId) return current;
      activeTriggerRef.current = null;
      return null;
    });
  }, []);

  useEffect(() => {
    if (!active) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (containerRef.current?.contains(event.target as Node)) return;
      closeTooltip(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [active, closeTooltip]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape" || !active) return;
    event.preventDefault();
    closeTooltip();
  };

  const projectedPoints = useMemo(() => {
    if (!model) return [];
    const labels = selectLabelIds(model.mode, model.points);
    const labelPriorities = new Map([...labels].map((geoId, index) => [geoId, index]));
    const projected = sortPointsForPaint(model.points).flatMap((point) => {
      const projected = projectGeoPoint(point.latitude, point.longitude);
      if (!projected) return [];
      return [{
        point,
        ...projected,
        radius: bubbleRadius(point.budgetRub, model.maxBudgetRub),
        mobileRadius: bubbleRadius(point.budgetRub, model.maxBudgetRub, true),
        brightness: bubbleBrightness(point.budgetRub, model.maxBudgetRub),
        label: labels.has(point.geoId),
        labelPriority: labelPriorities.get(point.geoId) ?? Number.MAX_SAFE_INTEGER,
        labelX: projected.x,
        labelY: projected.y,
      }];
    });
    const visibleLabels = projected
      .filter((item) => item.label && item.point.budgetRub > 0)
      .filter((item) => !mobileLayout || model.mode === "campaign" || item.labelPriority < 5)
      .sort((left, right) => left.labelPriority - right.labelPriority);
    const labelPositions = layoutMapLabels(
      visibleLabels.map((item) => ({
        geoId: item.point.geoId,
        geoDisplayName: item.point.geoDisplayName,
        x: item.x,
        y: item.y,
        radius: mobileLayout ? item.mobileRadius : item.radius,
      })),
      canvasWidth,
    );
    return projected.map((item) => {
      const position = labelPositions.get(item.point.geoId);
      return position ? { ...item, labelX: position.x, labelY: position.y } : item;
    });
  }, [canvasWidth, mobileLayout, model]);

  if (requestState !== "ready") {
    const copy = stateCopy(requestState);
    return (
      <MapState
        state={copy.tone === "danger" ? requestState : "loading"}
        title={copy.title}
        description={copy.description}
        onRetry={copy.tone === "danger" ? onRetry : undefined}
      />
    );
  }

  if (!model || !OUTLINE_IS_TRUSTED_LOCAL_ASSET) {
    return (
      <MapState
        state="unsupported-contract"
        title="Формат данных карты не поддерживается"
        description="Карта скрыта, чтобы не показывать непроверенные координаты или контур."
        onRetry={onRetry}
      />
    );
  }

  if (model.coverage.status === "unavailable" || projectedPoints.length === 0) {
    return (
      <div className={styles.unavailableStack}>
        <MapState
          state="unavailable"
          title="Карта пока недоступна"
          description={
            model.mode === "historical-model"
              ? model.displayText
              : "Сервис не опубликовал координаты для географий этой кампании."
          }
        />
        {model.coverage.unlocatedGeographiesN > 0 ? (
          <div className={styles.unlocatedSummary}>
            <strong>
              Без координат: {formatInteger(model.coverage.unlocatedGeographiesN)} географий
            </strong>
            <span>
              Бюджет сохранен: {formatRub(model.coverage.unlocatedBudgetRub)}
              {" · "}
              доля: {formatPercent(model.coverage.unlocatedBudgetShare)}
            </span>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className={styles.map}
      data-map-mode={model.mode}
      data-coverage-status={model.coverage.status}
      data-compact-layout={mobileLayout ? "true" : "false"}
      data-mobile-campaign-labels={showMobileCampaignLabels ? "shown" : "hidden"}
      ref={containerRef}
      onKeyDown={onKeyDown}
    >
      <div className={styles.legend}>
        <span><i className={styles.legendSize} aria-hidden="true" />Размер точки — рекламный бюджет</span>
        <span><i className={styles.legendBrightness} aria-hidden="true" />Яркость — относительный бюджет</span>
        <small>
          {model.mode === "historical-model"
            ? mobileLayout
              ? "Подписаны 5 из 10 городов с наибольшим бюджетом"
              : "Подписаны 10 городов с наибольшим бюджетом"
            : mobileLayout
              ? "Все географии доступны по кнопке под картой"
              : "Подписаны все географии кампании"}
        </small>
      </div>
      <div
        className={styles.canvas}
        ref={canvasRef}
        role="group"
        aria-label={
          model.mode === "historical-model"
            ? "Карта исторического рекламного бюджета модели по географиям"
            : "Карта рекламного бюджета текущей кампании"
        }
      >
        <div
          className={styles.outline}
          aria-hidden="true"
          dangerouslySetInnerHTML={{ __html: russiaOutline }}
        />
        <MarkerLayer
          mode={model.mode}
          points={projectedPoints}
          periodDisplayText={model.mode === "historical-model" ? model.periodDisplayText : undefined}
          onActivate={activate}
          onFocusActivate={focusActivate}
          onHoverEnd={hoverEnd}
        />
        {active && !mobileLayout ? (
          <Tooltip
            mode={model.mode}
            active={active}
            periodDisplayText={model.mode === "historical-model" ? model.periodDisplayText : undefined}
            onClose={() => closeTooltip()}
          />
        ) : null}
      </div>
      {active && mobileLayout ? (
        <div className={styles.mobileTooltipTray}>
          <Tooltip
            mode={model.mode}
            active={active}
            periodDisplayText={model.mode === "historical-model" ? model.periodDisplayText : undefined}
            onClose={() => closeTooltip()}
          />
        </div>
      ) : null}
      {model.mode === "campaign" && mobileLayout ? (
        <div className={styles.mobileLabels}>
          <button
            type="button"
            aria-expanded={showMobileCampaignLabels}
            onClick={() => setShowMobileCampaignLabels((current) => !current)}
          >
            {showMobileCampaignLabels ? "Скрыть подписи" : `Показать подписи (${projectedPoints.filter((item) => item.label).length})`}
          </button>
          {showMobileCampaignLabels ? (
            <ul>
              {projectedPoints
                .filter((item) => item.label)
                .sort((left, right) => left.labelPriority - right.labelPriority)
                .map((item) => <li key={item.point.geoId}>{item.point.geoDisplayName}</li>)}
            </ul>
          ) : null}
        </div>
      ) : null}
      <Attribution />
      <CoverageNotice model={model} />
    </div>
  );
}
