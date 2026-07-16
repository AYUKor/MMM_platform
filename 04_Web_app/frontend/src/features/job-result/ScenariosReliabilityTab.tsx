import type {
  JobResultViewV1,
  QuantileMetric,
  ReliabilityComponent,
  Scenario,
} from "../../shared/api/generated/job-result-view-v1";
import { formatInteger, formatRub } from "../../shared/formatters/metrics";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import {
  metricUsageLabel,
  metricValue,
  qualityLabel,
  qualityTone,
  reliabilityTone,
  scenarioAnchorLabel,
  scenarioDisplayName,
  scenarioNumber,
  type ResultMetricId,
  type ResultTone,
} from "./jobResultFormatting";
import { MetricSummary, ScenarioRangeChart } from "./ResultVisuals";
import styles from "./job-result.module.css";

type ScenarioStatus = Scenario["status"];

const scenarioStatusCopy: Record<
  ScenarioStatus,
  { label: string; tone: ResultTone }
> = {
  completed: { label: "Рассчитан", tone: "accent" },
  unavailable: { label: "Нет данных", tone: "neutral" },
  failed: { label: "Не рассчитан", tone: "danger" },
};

const scenarioRoleCopy: Record<Scenario["role"], string> = {
  source: "Исходная точка",
  control: "Контрольный сценарий",
  benchmark: "Ориентир для сравнения",
  adaptive: "Адаптивный поиск",
};

const reliabilityStatusCopy: Record<
  ReliabilityComponent["status"],
  string
> = {
  good: "Хорошо",
  caution: "Осторожно",
  poor: "Требует проверки",
  unavailable: "Нет данных",
};

function rankText(value: number | null): string {
  return value === null ? "Нет данных" : `№ ${formatInteger(value)}`;
}

function MetricCell({ metric }: { metric: QuantileMetric }) {
  const available =
    metric.status === "available" &&
    metric.p10 !== null &&
    metric.p50 !== null &&
    metric.p90 !== null;
  const usage = metricUsageLabel(metric);

  if (!available) {
    return (
      <div className={styles.scenarioMetricEmpty}>
        <strong>Нет данных</strong>
        <span>{metric.display_text}</span>
      </div>
    );
  }

  return (
    <div className={styles.scenarioMetricCell}>
      <strong>P50: {metricValue(metric, metric.p50)}</strong>
      <span>P10: {metricValue(metric, metric.p10)}</span>
      <span>P90: {metricValue(metric, metric.p90)}</span>
      {usage ? <small>{usage}</small> : null}
    </div>
  );
}

function ScenarioBadges({
  result,
  scenario,
}: {
  result: JobResultViewV1;
  scenario: Scenario;
}) {
  const anchor = scenarioAnchorLabel(scenario.scenario_id);
  const isCanonicalRecommendation =
    result.recommendation.status === "recommended" &&
    result.recommendation.scenario_id === scenario.scenario_id &&
    scenario.is_recommended;

  return (
    <div className={styles.scenarioBadges}>
      {anchor ? <StatusBadge tone="neutral">{anchor}</StatusBadge> : null}
      {isCanonicalRecommendation ? (
        <StatusBadge tone="accent">Рекомендован</StatusBadge>
      ) : null}
      {scenario.is_best_safe ? (
        <StatusBadge tone="accent">Лучший безопасный</StatusBadge>
      ) : null}
      {scenario.is_best_raw ? (
        <StatusBadge tone="warning">Лучший математический</StatusBadge>
      ) : null}
    </div>
  );
}

function ScenarioComparisonTable({ result }: { result: JobResultViewV1 }) {
  return (
    <section
      className={styles.scenarioComparisonSection}
      aria-labelledby="scenario-comparison-title"
    >
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>Подробное сравнение</span>
          <h2 id="scenario-comparison-title">Все шесть сценариев</h2>
        </div>
        <p>
          Места сценариев учитывают ожидаемый эффект и ограничения надежности.
        </p>
      </div>

      <div
        className={styles.scenarioTableWrap}
        role="region"
        aria-label="Таблица сравнения сценариев"
        tabIndex={0}
      >
        <table className={styles.scenarioTable}>
          <caption className="sr-only">
            Сценарии 1–6: статусы, места, бюджеты и диапазоны показателей
          </caption>
          <thead>
            <tr>
              <th scope="col">Сценарий</th>
              <th scope="col">Статус и качество</th>
              <th scope="col">Места</th>
              <th scope="col">Дополнительный оборот</th>
              <th scope="col">ROAS</th>
              <th scope="col">Дополнительные заказы</th>
              <th scope="col">Заказы на 100 000 ₽</th>
              <th scope="col">Изменение среднего чека</th>
              <th scope="col">Вклад механизма среднего чека</th>
              <th scope="col">Бюджет</th>
            </tr>
          </thead>
          <tbody>
            {result.scenarios.map((scenario) => {
              const statusCopy = scenarioStatusCopy[scenario.status];
              return (
                <tr key={scenario.scenario_id}>
                  <th scope="row">
                    <div className={styles.scenarioIdentity}>
                      <strong>S{scenarioNumber(scenario.scenario_id)}</strong>
                      <span>{scenarioDisplayName(scenario)}</span>
                      <small>{scenarioRoleCopy[scenario.role]}</small>
                      <p>{scenario.description}</p>
                      <ScenarioBadges result={result} scenario={scenario} />
                    </div>
                  </th>
                  <td>
                    <div className={styles.scenarioStatusCell}>
                      <StatusBadge tone={statusCopy.tone}>
                        {statusCopy.label}
                      </StatusBadge>
                      <StatusBadge tone={qualityTone(scenario.quality_status)}>
                        {qualityLabel(scenario.quality_status)}
                      </StatusBadge>
                      <span>{scenario.quality_display_text}</span>
                    </div>
                  </td>
                  <td>
                    <dl className={styles.scenarioRanks}>
                      <div>
                        <dt>Среди устойчивых</dt>
                        <dd>{rankText(scenario.safe_rank)}</dd>
                      </div>
                      <div>
                        <dt>По математической оценке</dt>
                        <dd>{rankText(scenario.raw_rank)}</dd>
                      </div>
                    </dl>
                  </td>
                  <td>
                    <MetricCell metric={scenario.metrics.incremental_turnover_rub} />
                  </td>
                  <td>
                    <MetricCell metric={scenario.metrics.roas} />
                  </td>
                  <td>
                    <MetricCell metric={scenario.metrics.incremental_orders} />
                  </td>
                  <td>
                    <MetricCell metric={scenario.metrics.orders_per_100k_rub} />
                  </td>
                  <td>
                    <MetricCell metric={scenario.metrics.avg_basket_delta_rub} />
                  </td>
                  <td>
                    <MetricCell
                      metric={scenario.metrics.avg_basket_turnover_bridge_rub}
                    />
                  </td>
                  <td>
                    <dl className={styles.scenarioBudgetCell}>
                      <div>
                        <dt>Запрошено</dt>
                        <dd>{formatRub(scenario.budget.requested_budget_rub)}</dd>
                      </div>
                      <div>
                        <dt>Распределено</dt>
                        <dd>{formatRub(scenario.budget.allocated_budget_rub)}</dd>
                      </div>
                      <div>
                        <dt>Не распределено</dt>
                        <dd>{formatRub(scenario.budget.unallocated_budget_rub)}</dd>
                      </div>
                    </dl>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ReliabilityComponents({ result }: { result: JobResultViewV1 }) {
  const selected = result.scenarios.find(
    (scenario) => scenario.scenario_id === result.overview.selected_scenario_id,
  );

  return (
    <section
      className={styles.reliabilitySection}
      aria-labelledby="scenario-reliability-title"
    >
      <div className={styles.reliabilityIntro}>
        <span className={styles.eyebrow}>Надежность</span>
        <h2 id="scenario-reliability-title">
          Надежность S
          {selected ? scenarioNumber(selected.scenario_id) : "—"}
        </h2>
        <p>{result.reliability.display_text}</p>
        <StatusBadge tone="neutral">
          Числовая оценка надежности недоступна
        </StatusBadge>
      </div>

      <ul className={styles.reliabilityComponentGrid}>
        {result.reliability.components.map((component) => (
          <li key={component.component_id}>
            <StatusBadge tone={reliabilityTone(component.status)}>
              {reliabilityStatusCopy[component.status]}
            </StatusBadge>
            <h3>{component.title}</h3>
            <p>{component.display_text}</p>
          </li>
        ))}
      </ul>

      <div
        className={styles.reliabilityMatrixWrap}
        role="region"
        aria-label="Надежность всех сценариев"
        tabIndex={0}
      >
        <table className={styles.reliabilityMatrix}>
          <caption className="sr-only">
            Качественные признаки надежности для каждого сценария
          </caption>
          <thead>
            <tr>
              <th scope="col">Сценарий</th>
              {result.reliability.components.map((component) => (
                <th key={component.component_id} scope="col">
                  {component.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.scenarios.map((scenario) => (
              <tr key={scenario.scenario_id}>
                <th scope="row">
                  S{scenarioNumber(scenario.scenario_id)} · {scenarioDisplayName(scenario)}
                </th>
                {scenario.reliability.components.map((component) => (
                  <td key={component.component_id}>
                    <StatusBadge tone={reliabilityTone(component.status)}>
                      {reliabilityStatusCopy[component.status]}
                    </StatusBadge>
                    <span>{component.display_text}</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function BestRawPanel({ result }: { result: JobResultViewV1 }) {
  const bestRaw = result.best_raw;
  if (!bestRaw.available) return null;

  return (
    <section className={styles.bestRawPanel} aria-labelledby="best-raw-title">
      <div className={styles.bestRawHeading}>
        <div>
          <span className={styles.eyebrow}>Только для проверки расчета</span>
          <h2 id="best-raw-title">
            Математически сильный, но не рекомендованный вариант
          </h2>
        </div>
        <StatusBadge tone="warning">Не является рекомендацией</StatusBadge>
      </div>

      <p className={styles.bestRawReason}>
        {bestRaw.reason_not_recommended ?? "Нет данных"}
      </p>
      <dl className={styles.bestRawMeta}>
        <div>
          <dt>Сценарий</dt>
          <dd>
            {bestRaw.scenario_id === null
              ? "Нет данных"
              : `S${scenarioNumber(bestRaw.scenario_id)}`}
          </dd>
        </div>
        <div>
          <dt>Место по математической оценке</dt>
          <dd>{rankText(bestRaw.raw_rank)}</dd>
        </div>
        <div>
          <dt>Место среди устойчивых</dt>
          <dd>{rankText(bestRaw.safe_rank)}</dd>
        </div>
      </dl>

      {bestRaw.metrics ? (
        <div className={styles.bestRawMetrics}>
          <MetricSummary
            title="Дополнительный оборот"
            metric={bestRaw.metrics.incremental_turnover_rub}
          />
          <MetricSummary title="ROAS по обороту" metric={bestRaw.metrics.roas} />
        </div>
      ) : (
        <p className={styles.inlineUnavailable}>Нет данных о показателях.</p>
      )}

      {bestRaw.blocking_cells_status === "available" &&
      bestRaw.blocking_cells.length > 0 ? (
        <div
          className={styles.blockingCellsWrap}
          role="region"
          aria-label="Связки, требующие ручной проверки"
          tabIndex={0}
        >
          <table className={styles.blockingCellsTable}>
            <caption>Связки, из-за которых вариант не рекомендован</caption>
            <thead>
              <tr>
                <th scope="col">Сегмент</th>
                <th scope="col">География</th>
                <th scope="col">Канал</th>
                <th scope="col">Причина</th>
              </tr>
            </thead>
            <tbody>
              {bestRaw.blocking_cells.map((cell, index) => (
                <tr key={`${cell.segment}:${cell.geo}:${cell.channel}:${index}`}>
                  <td>{cell.segment}</td>
                  <td>{cell.geo}</td>
                  <td>{cell.channel}</td>
                  <td>{cell.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : bestRaw.blocking_cells_status === "unavailable" ? (
        <p className={styles.inlineUnavailable}>
          Подробности по отдельным связкам пока недоступны.
        </p>
      ) : null}
    </section>
  );
}

function Limitations({ result }: { result: JobResultViewV1 }) {
  return (
    <section className={styles.limitationsSection} aria-labelledby="limitations-title">
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>Границы результата</span>
          <h2 id="limitations-title">Ограничения данных</h2>
        </div>
      </div>
      <ul>
        {result.limitations.map((limitation) => (
          <li key={limitation.code}>{limitation.display_text}</li>
        ))}
      </ul>
    </section>
  );
}

export function ScenariosReliabilityTab({
  result,
  metricId,
  onMetricChange,
}: {
  result: JobResultViewV1;
  metricId: ResultMetricId;
  onMetricChange: (metricId: ResultMetricId) => void;
}) {
  return (
    <div className={styles.tabStack}>
      <header className={styles.tabIntro}>
        <div>
          <span className={styles.eyebrow}>Сценарии и надежность</span>
          <h2>Сравнение рассчитанных вариантов</h2>
        </div>
        <p>
          S1 всегда остается исходным планом, S5 — устойчивым ориентиром.
          Рекомендация, лучшие безопасный и математический варианты показаны
          раздельно.
        </p>
      </header>

      <ScenarioRangeChart
        scenarios={[...result.scenarios]}
        recommendationScenarioId={result.recommendation.scenario_id}
        metricId={metricId}
        onMetricChange={onMetricChange}
        title="Диапазоны по сценариям"
      />
      <ScenarioComparisonTable result={result} />
      <ReliabilityComponents result={result} />
      <BestRawPanel result={result} />
      <Limitations result={result} />
    </div>
  );
}
