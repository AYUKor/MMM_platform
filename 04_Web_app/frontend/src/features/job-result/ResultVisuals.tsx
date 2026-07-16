import type {
  QuantileMetric,
  QualityStatus,
  Scenario,
  ScenarioId,
} from "../../shared/api/generated/job-result-view-v1";
import { formatRub } from "../../shared/formatters/metrics";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import {
  metricForScenario,
  formatDeltaPercent,
  metricUsageLabel,
  metricValue,
  qualityLabel,
  qualityTone,
  RESULT_METRICS,
  scenarioAnchorLabel,
  scenarioDisplayName,
  scenarioNumber,
  type ResultMetricId,
} from "./jobResultFormatting";
import styles from "./job-result.module.css";

interface BudgetComparisonRow {
  channel?: string;
  geo?: string;
  source_budget_rub: number;
  selected_budget_rub: number;
  delta_rub: number;
  delta_pct: number | null;
  quality_status: QualityStatus;
  quality_display_text: string;
}

export function MetricSummary({
  title,
  metric,
  unavailableText,
}: {
  title: string;
  metric: QuantileMetric;
  unavailableText?: string;
}) {
  const usage = metricUsageLabel(metric);
  const available = metric.status === "available";
  return (
    <article className={styles.metricCard}>
      <div className={styles.metricHeading}>
        <h3>{title}</h3>
        {usage ? <StatusBadge tone="warning">{usage}</StatusBadge> : null}
      </div>
      <strong className={available ? styles.metricValue : styles.metricUnavailable}>
        {available ? metricValue(metric, metric.p50) : "Нет данных"}
      </strong>
      {available ? (
        <dl className={styles.metricRange} aria-label={`${title}: диапазон оценки`}>
          <div><dt>Осторожная</dt><dd>{metricValue(metric, metric.p10)}</dd></div>
          <div><dt>Базовая</dt><dd>{metricValue(metric, metric.p50)}</dd></div>
          <div><dt>Оптимистичная</dt><dd>{metricValue(metric, metric.p90)}</dd></div>
        </dl>
      ) : (
        <p className={styles.metricNote}>{unavailableText ?? metric.display_text}</p>
      )}
      {available ? <p className={styles.metricNote}>{metric.display_text}</p> : null}
    </article>
  );
}

interface ScenarioRangeChartProps {
  scenarios: Scenario[];
  recommendationScenarioId: ScenarioId | null;
  metricId: ResultMetricId;
  onMetricChange: (metricId: ResultMetricId) => void;
  title?: string;
}

function intervalPosition(
  value: number,
  minimum: number,
  maximum: number,
): number {
  if (maximum === minimum) return 50;
  return Math.min(100, Math.max(0, ((value - minimum) / (maximum - minimum)) * 100));
}

export function ScenarioRangeChart({
  scenarios,
  recommendationScenarioId,
  metricId,
  onMetricChange,
  title = "Диапазоны сценариев",
}: ScenarioRangeChartProps) {
  const available = scenarios
    .map((scenario) => ({ scenario, metric: metricForScenario(scenario, metricId) }))
    .filter(
      (item): item is { scenario: Scenario; metric: QuantileMetric & { p10: number; p50: number; p90: number } } =>
        item.metric.status === "available" &&
        item.metric.p10 !== null &&
        item.metric.p50 !== null &&
        item.metric.p90 !== null,
    );
  const minimum = available.length > 0
    ? Math.min(...available.map(({ metric }) => metric.p10))
    : 0;
  const maximum = available.length > 0
    ? Math.max(...available.map(({ metric }) => metric.p90))
    : 0;

  return (
    <section className={styles.rangePanel} aria-labelledby="scenario-range-title">
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>Сравнение рассчитанных вариантов</span>
          <h2 id="scenario-range-title">{title}</h2>
        </div>
        <label className={styles.metricSelector}>
          <span>Показатель</span>
          <select
            value={metricId}
            onChange={(event) => onMetricChange(event.target.value as ResultMetricId)}
          >
            {RESULT_METRICS.map((metric) => (
              <option key={metric.id} value={metric.id}>{metric.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className={styles.rangeLegend} aria-hidden="true">
        <span><i className={styles.legendInterval} />Диапазон</span>
        <span><i className={styles.legendMedian} />Базовая оценка</span>
      </div>

      <ol className={styles.rangeRows}>
        {scenarios.map((scenario) => {
          const metric = metricForScenario(scenario, metricId);
          const isAvailable = metric.status === "available" &&
            metric.p10 !== null && metric.p50 !== null && metric.p90 !== null;
          const availableQuantiles = isAvailable
            ? { p10: metric.p10 as number, p50: metric.p50 as number, p90: metric.p90 as number }
            : null;
          const anchor = scenarioAnchorLabel(scenario.scenario_id);
          const recommended = recommendationScenarioId === scenario.scenario_id;
          return (
            <li
              key={scenario.scenario_id}
              className={`${styles.rangeRow} ${recommended ? styles.rangeRecommended : ""} ${
                scenario.scenario_id === "S05" ? styles.rangeBenchmark : ""
              }`}
            >
              <div className={styles.rangeScenario}>
                <strong>S{scenarioNumber(scenario.scenario_id)}</strong>
                <span>{scenarioDisplayName(scenario)}</span>
                <div className={styles.rangeBadges}>
                  {recommended ? <StatusBadge tone="accent">Рекомендован</StatusBadge> : null}
                  {anchor ? <StatusBadge tone="neutral">{anchor}</StatusBadge> : null}
                </div>
              </div>
              {availableQuantiles ? (
                <div className={styles.intervalCell}>
                  <div
                    className={styles.intervalTrack}
                    role="img"
                    aria-label={`${scenarioDisplayName(scenario)}: ${metricValue(metric, metric.p10)} — ${metricValue(metric, metric.p90)}, базовая оценка ${metricValue(metric, metric.p50)}`}
                  >
                    <span
                      className={styles.intervalBand}
                      style={{
                        left: `${intervalPosition(availableQuantiles.p10, minimum, maximum)}%`,
                        width: `${Math.max(
                          1,
                          intervalPosition(availableQuantiles.p90, minimum, maximum) -
                            intervalPosition(availableQuantiles.p10, minimum, maximum),
                        )}%`,
                      }}
                    />
                    <i
                      className={styles.intervalMedian}
                      style={{ left: `${intervalPosition(availableQuantiles.p50, minimum, maximum)}%` }}
                    />
                  </div>
                  <div className={styles.intervalValues}>
                    <span>{metricValue(metric, metric.p10)}</span>
                    <strong>{metricValue(metric, metric.p50)}</strong>
                    <span>{metricValue(metric, metric.p90)}</span>
                  </div>
                </div>
              ) : (
                <div className={styles.intervalEmpty}>Нет данных</div>
              )}
              <StatusBadge tone={qualityTone(scenario.quality_status)}>
                {qualityLabel(scenario.quality_status)}
              </StatusBadge>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function BudgetComparisonChart({
  title,
  rows,
  dimension,
  limit,
}: {
  title: string;
  rows: BudgetComparisonRow[];
  dimension: "channel" | "geo";
  limit?: number;
}) {
  const visibleRows = typeof limit === "number" ? rows.slice(0, limit) : rows;
  const maximum = Math.max(
    1,
    ...visibleRows.flatMap((row) => [row.source_budget_rub, row.selected_budget_rub]),
  );
  return (
    <section className={styles.budgetChart}>
      <h3>{title}</h3>
      <div className={styles.budgetLegend} aria-hidden="true">
        <span><i className={styles.sourceSwatch} />Исходный план</span>
        <span><i className={styles.selectedSwatch} />Выбранный план</span>
      </div>
      <ul>
        {visibleRows.map((row, index) => {
          const label = dimension === "channel" ? row.channel : row.geo;
          return (
            <li key={`${label ?? "unknown"}:${index}`}>
              <div className={styles.budgetIdentity}>
                <span className={styles.budgetName}>{label ?? "Нет данных"}</span>
                <StatusBadge tone={qualityTone(row.quality_status)}>{qualityLabel(row.quality_status)}</StatusBadge>
                <small>{row.quality_display_text}</small>
              </div>
              <div className={styles.budgetBars}>
                <span><i className={styles.sourceBar} style={{ width: `${(row.source_budget_rub / maximum) * 100}%` }} /></span>
                <span><i className={styles.selectedBar} style={{ width: `${(row.selected_budget_rub / maximum) * 100}%` }} /></span>
              </div>
              <div className={`${styles.budgetDelta} ${row.delta_rub >= 0 ? styles.positiveDelta : styles.negativeDelta}`}>
                <strong>{row.delta_rub === 0 ? formatRub(0) : `${row.delta_rub > 0 ? "+" : "−"}${formatRub(Math.abs(row.delta_rub))}`}</strong>
                <small>{formatDeltaPercent(row.delta_pct)}</small>
              </div>
              <span className="sr-only">
                Исходный бюджет {formatRub(row.source_budget_rub)}, выбранный бюджет {formatRub(row.selected_budget_rub)}.
                Качество: {row.quality_display_text}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function UnavailableBlock({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <section className={styles.unavailableBlock}>
      <span aria-hidden="true">—</span>
      <div><h3>{title}</h3><p>{description}</p></div>
    </section>
  );
}
