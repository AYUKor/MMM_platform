import type {
  JobResultViewV1,
  Scenario,
} from "../../shared/api/generated/job-result-view-v1";
import { formatInteger, formatPercent, formatRub } from "../../shared/formatters/metrics";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import {
  campaignPeriod,
  metricValue,
  qualityLabel,
  qualityTone,
  reliabilityTone,
  scenarioAnchorLabel,
  scenarioDisplayName,
  scenarioNumber,
  type ResultMetricId,
} from "./jobResultFormatting";
import {
  BudgetComparisonChart,
  MetricSummary,
  ScenarioRangeChart,
  UnavailableBlock,
} from "./ResultVisuals";
import styles from "./job-result.module.css";

function findScenario(result: JobResultViewV1, id: string): Scenario {
  return result.scenarios.find((scenario) => scenario.scenario_id === id) ?? result.scenarios[0];
}

function ScenarioAnchorCard({
  scenario,
  recommended,
}: {
  scenario: Scenario;
  recommended: boolean;
}) {
  const anchor = scenarioAnchorLabel(scenario.scenario_id);
  const turnover = scenario.metrics.incremental_turnover_rub;
  const roas = scenario.metrics.roas;
  return (
    <article className={styles.anchorCard}>
      <div className={styles.anchorTopline}>
        <span>S{scenarioNumber(scenario.scenario_id)}</span>
        <div>
          {anchor ? <StatusBadge tone="neutral">{anchor}</StatusBadge> : null}
          {recommended ? <StatusBadge tone="accent">Рекомендован</StatusBadge> : null}
        </div>
      </div>
      <h3>{scenarioDisplayName(scenario)}</h3>
      <p>{scenario.description}</p>
      <dl className={styles.anchorMetrics}>
        <div><dt>Дополнительный оборот</dt><dd>{metricValue(turnover, turnover.p50)}</dd></div>
        <div><dt>ROAS</dt><dd>{metricValue(roas, roas.p50)}</dd></div>
        <div><dt>Распределено</dt><dd>{formatRub(scenario.budget.allocated_budget_rub)}</dd></div>
      </dl>
      <StatusBadge tone={qualityTone(scenario.quality_status)}>
        {qualityLabel(scenario.quality_status)}
      </StatusBadge>
    </article>
  );
}

function WarningList({ result }: { result: JobResultViewV1 }) {
  if (result.warnings.length === 0) return null;
  return (
    <section className={styles.warningSection} aria-labelledby="overview-warnings-title">
      <div className={styles.sectionHeading}>
        <div><span className={styles.eyebrow}>Что важно учитывать</span><h2 id="overview-warnings-title">Замечания к результату</h2></div>
      </div>
      <ul className={styles.warningList}>
        {result.warnings.map((warning) => (
          <li key={warning.code} className={styles[`warning-${warning.severity}`]}>
            <div>
              <StatusBadge tone={warning.severity === "blocking" ? "danger" : warning.severity === "info" ? "neutral" : "warning"}>
                {warning.severity === "blocking" ? "Требует действия" : warning.severity === "info" ? "Информация" : "Обратите внимание"}
              </StatusBadge>
              <h3>{warning.title}</h3>
            </div>
            <p>{warning.display_text}</p>
            <span>Что можно сделать: {warning.recommended_action}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function OverviewTab({
  result,
  metricId,
  onMetricChange,
  onOpenMediaPlan,
}: {
  result: JobResultViewV1;
  metricId: ResultMetricId;
  onMetricChange: (metricId: ResultMetricId) => void;
  onOpenMediaPlan: () => void;
}) {
  const selected = findScenario(result, result.overview.selected_scenario_id);
  const source = findScenario(result, "S01");
  const benchmark = findScenario(result, "S05");
  const recommended = result.recommendation.status === "recommended"
    ? findScenario(result, result.recommendation.scenario_id ?? result.overview.selected_scenario_id)
    : null;
  const anchorScenarios = [source, benchmark].filter(
    (scenario, index, rows) =>
      scenario.scenario_id !== recommended?.scenario_id &&
      rows.findIndex((candidate) => candidate.scenario_id === scenario.scenario_id) === index,
  );
  const metrics = selected.metrics;

  return (
    <div className={styles.tabStack}>
      <section className={styles.decisionGrid} aria-label="Рекомендация и опорные сценарии">
        <article className={`${styles.recommendationHero} ${
          result.recommendation.status === "recommended" ? "" : styles.recommendationUnavailable
        }`}>
          <div className={styles.heroTopline}>
            <span className={styles.eyebrow}>
              {result.recommendation.status === "recommended" ? "Рекомендация" : "Статус рекомендации"}
            </span>
            {result.recommendation.status === "recommended" ? (
              <StatusBadge tone="accent">Рекомендован системой</StatusBadge>
            ) : (
              <StatusBadge tone="warning">Автоматическая рекомендация отсутствует</StatusBadge>
            )}
          </div>
          <h2>{result.recommendation.status === "no_safe_recommendation"
            ? "Безопасная автоматическая рекомендация не сформирована"
            : result.recommendation.title}</h2>
          {recommended ? (
            <div className={styles.heroScenarioLine}>
              <strong>S{scenarioNumber(recommended.scenario_id)} · {scenarioDisplayName(recommended)}</strong>
              {scenarioAnchorLabel(recommended.scenario_id) ? (
                <StatusBadge tone="neutral">{scenarioAnchorLabel(recommended.scenario_id)}</StatusBadge>
              ) : null}
            </div>
          ) : null}
          <p>{result.recommendation.display_text}</p>
          <p className={styles.decisionScope}>{result.recommendation.decision_scope_text}</p>
          {recommended ? (
            <dl className={styles.heroMetrics}>
              <div><dt>Дополнительный оборот</dt><dd>{metricValue(recommended.metrics.incremental_turnover_rub, recommended.metrics.incremental_turnover_rub.p50)}</dd></div>
              <div><dt>ROAS</dt><dd>{metricValue(recommended.metrics.roas, recommended.metrics.roas.p50)}</dd></div>
              <div><dt>Место среди устойчивых</dt><dd>{recommended.safe_rank === null ? "Нет данных" : `№ ${formatInteger(recommended.safe_rank)}`}</dd></div>
              <div><dt>Место без учета ограничений</dt><dd>{recommended.raw_rank === null ? "Нет данных" : `№ ${formatInteger(recommended.raw_rank)}`}</dd></div>
            </dl>
          ) : (
            <div className={styles.noSafeExplanation}>
              <strong>S1 остается исходной точкой, а S5 — устойчивым ориентиром.</strong>
              <span>Ни один из них не становится победителем автоматически.</span>
            </div>
          )}
          <button type="button" className={styles.heroAction} onClick={onOpenMediaPlan}>
            Посмотреть рассчитанные медиапланы
          </button>
        </article>
        <div className={styles.anchorColumn}>
          {anchorScenarios.map((scenario) => (
            <ScenarioAnchorCard
              key={scenario.scenario_id}
              scenario={scenario}
              recommended={result.recommendation.scenario_id === scenario.scenario_id}
            />
          ))}
        </div>
      </section>

      <section className={styles.metricSection} aria-labelledby="headline-metrics-title">
        <div className={styles.sectionHeading}>
          <div><span className={styles.eyebrow}>Оценка выбранного для просмотра сценария</span><h2 id="headline-metrics-title">Ключевые показатели</h2></div>
          <span>S{scenarioNumber(selected.scenario_id)} · {scenarioDisplayName(selected)}</span>
        </div>
        <div className={styles.metricsGrid}>
          <MetricSummary title="Дополнительный оборот" metric={metrics.incremental_turnover_rub} />
          <MetricSummary title="ROAS по обороту" metric={metrics.roas} />
          <MetricSummary title="Дополнительные заказы" metric={metrics.incremental_orders} />
          <MetricSummary title="Заказы на 100 000 ₽" metric={metrics.orders_per_100k_rub} />
          <MetricSummary
            title="Изменение среднего чека"
            metric={metrics.avg_basket_delta_rub}
            unavailableText="Изменение среднего чека пока недоступно"
          />
          <MetricSummary
            title="Механизм среднего чека"
            metric={metrics.avg_basket_turnover_bridge_rub}
            unavailableText="Вклад механизма среднего чека пока недоступен"
          />
        </div>
        <dl className={styles.budgetSummary}>
          <div><dt>Запрошенный бюджет</dt><dd>{formatRub(selected.budget.requested_budget_rub)}</dd></div>
          <div><dt>Распределено</dt><dd>{formatRub(selected.budget.allocated_budget_rub)}</dd></div>
          <div className={selected.budget.unallocated_budget_rub > 0 ? styles.budgetWarning : ""}>
            <dt>Не распределено</dt><dd>{formatRub(selected.budget.unallocated_budget_rub)}</dd>
          </div>
          <div><dt>Покрытие модели</dt><dd>{formatPercent(result.campaign.model_coverage_share)}</dd></div>
        </dl>
      </section>

      <ScenarioRangeChart
        scenarios={[...result.scenarios]}
        recommendationScenarioId={result.recommendation.scenario_id}
        metricId={metricId}
        onMetricChange={onMetricChange}
        title="Сценарии 1–6"
      />

      <section className={styles.reliabilityOverview} aria-labelledby="overview-reliability-title">
        <div className={styles.reliabilityIntro}>
          <span className={styles.eyebrow}>Надежность</span>
          <h2 id="overview-reliability-title">Надежность результата</h2>
          <p>
            Числовая оценка пока недоступна, поэтому показаны отдельные признаки надежности. {result.reliability.display_text}
          </p>
          <StatusBadge tone="neutral">Числовая шкала пока недоступна</StatusBadge>
        </div>
        <ul className={styles.reliabilityCompactList}>
          {result.reliability.components.map((component) => (
            <li key={component.component_id}>
              <StatusBadge tone={reliabilityTone(component.status)}>{component.status === "good" ? "Хорошо" : component.status === "caution" ? "Осторожно" : component.status === "poor" ? "Требует проверки" : "Нет данных"}</StatusBadge>
              <strong>{component.title}</strong>
              <span>{component.display_text}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.budgetChartsSection} aria-labelledby="budget-changes-title">
        <div className={styles.sectionHeading}>
          <div><span className={styles.eyebrow}>Сравнение исходного и выбранного плана</span><h2 id="budget-changes-title">Что изменилось в бюджете</h2></div>
        </div>
        <div className={styles.budgetChartsGrid}>
          <BudgetComparisonChart title="По каналам" rows={[...result.overview.channel_summary]} dimension="channel" />
          <BudgetComparisonChart title="По географиям" rows={[...result.overview.geo_summary]} dimension="geo" limit={8} />
        </div>
        <div className={styles.geoChannelSummary}>
          <strong>География × канал</strong>
          <span>{formatInteger(result.overview.geo_channel_summary.length)} рассчитанных связок</span>
          <p>Детальный просмотр каждой связки доступен во вкладке «Медиаплан».</p>
        </div>
      </section>

      <UnavailableBlock title="Карта" description={result.media_plan.map.display_text} />
      <WarningList result={result} />

      <footer className={styles.resultFootnote}>
        <span>{campaignPeriod(result.campaign.start_date, result.campaign.end_date)}</span>
        <span>{result.record_origin === "sanitized_fixture" ? "Демонстрационные данные" : "Готовый результат расчета"}</span>
      </footer>
    </div>
  );
}
