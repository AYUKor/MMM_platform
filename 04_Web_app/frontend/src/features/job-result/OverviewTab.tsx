import type {
  JobResultViewV2,
  Scenario,
} from "../../shared/api/generated/job-result-view-v2";
import { formatPercent, formatRub } from "../../shared/formatters/metrics";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import {
  allocationShareLabel,
  budgetAllocationLabel,
  decisionLabel,
  decisionTone,
  reliabilityLabel,
  reliabilityTone,
  reviewLabel,
  scenarioAnchorLabel,
  scenarioDisplayName,
  scenarioNumber,
  scenarioVariantTitle,
  quantileValue,
} from "./jobResultFormatting";
import { scenarioById } from "./jobResultModel";
import { QuantileSummary, RiskComposition, UnavailableBlock } from "./ResultVisuals";
import styles from "./job-result.module.css";

function BudgetSummary({ scenario }: { scenario: Scenario }) {
  return (
    <dl className={styles.budgetSummary} aria-label={`Бюджет сценария ${scenarioNumber(scenario.scenario_id)}`}>
      <div><dt>Запрошенный бюджет</dt><dd>{formatRub(scenario.budget.requested_budget_rub)}</dd></div>
      <div><dt>Распределено</dt><dd>{formatRub(scenario.budget.allocated_budget_rub)}</dd></div>
      <div className={scenario.budget.unallocated_budget_rub > 0 ? styles.budgetWarning : ""}>
        <dt>Не распределено</dt><dd>{formatRub(scenario.budget.unallocated_budget_rub)}</dd>
      </div>
      <div><dt>Доля распределения</dt><dd>{allocationShareLabel(scenario)}</dd></div>
    </dl>
  );
}

function ScenarioAnchorCard({ scenario }: { scenario: Scenario }) {
  const anchor = scenarioAnchorLabel(scenario);
  const partial = scenario.scenario_id === "S05" && scenario.scenario_variant === "safe_partial";
  return (
    <article className={`${styles.anchorCard} ${partial ? styles.partialCard : ""}`}>
      <div className={styles.anchorTopline}>
        <span>S{scenarioNumber(scenario.scenario_id)}</span>
        {anchor ? <StatusBadge tone={partial ? "warning" : "neutral"}>{anchor}</StatusBadge> : null}
      </div>
      <h3>{scenarioDisplayName(scenario)}</h3>
      {scenarioVariantTitle(scenario) ? <strong>{scenarioVariantTitle(scenario)}</strong> : null}
      <p>{scenario.description}</p>
      {scenario.status === "completed" ? (
        <>
          <dl className={styles.anchorMetrics}>
            <div><dt>Распределение</dt><dd>{budgetAllocationLabel(scenario)}</dd></div>
            <div><dt>Доля</dt><dd>{allocationShareLabel(scenario)}</dd></div>
            <div><dt>ROAS к запрошенному бюджету</dt><dd>{quantileValue(scenario.roas.requested_budget, scenario.roas.requested_budget.p50)}</dd></div>
          </dl>
          <StatusBadge tone={reliabilityTone(scenario.reliability.status)}>
            {reliabilityLabel(scenario.reliability.status)}
          </StatusBadge>
        </>
      ) : (
        <StatusBadge tone="neutral">Нет данных</StatusBadge>
      )}
    </article>
  );
}

function PartialScenarioCallout({ scenario }: { scenario: Scenario }) {
  if (scenario.scenario_id !== "S05" || scenario.scenario_variant !== "safe_partial") return null;
  return (
    <section className={styles.partialCallout} aria-labelledby="partial-s5-title">
      <div>
        <StatusBadge tone="warning">Распределена безопасная часть</StatusBadge>
        <h2 id="partial-s5-title">Безопасно распределяемая часть</h2>
        <p>
          Весь бюджет нельзя распределить с приемлемой надежностью. Безопасно распределить удалось только {" "}
          <strong>{formatRub(scenario.budget.allocated_budget_rub)} из {formatRub(scenario.budget.requested_budget_rub)}</strong>.
        </p>
      </div>
      <dl>
        <div><dt>Доля распределения</dt><dd>{formatPercent(scenario.budget.allocation_share)}</dd></div>
        <div><dt>Не распределено</dt><dd>{formatRub(scenario.budget.unallocated_budget_rub)}</dd></div>
      </dl>
      <p className={styles.partialAction}>
        Оставшийся бюджет требует изменения каналов, географий, сроков кампании либо согласия на более рискованный прогноз.
      </p>
    </section>
  );
}

export function OverviewTab({
  result,
  onOpenMediaPlan,
}: {
  result: JobResultViewV2;
  onOpenMediaPlan: () => void;
}) {
  const source = scenarioById(result, "S01");
  const benchmark = scenarioById(result, "S05");
  const selected = result.recommendation.scenario_id
    ? scenarioById(result, result.recommendation.scenario_id)
    : source;
  const recommendationTone = decisionTone(result.recommendation.decision_status);
  const isPartial = selected.scenario_id === "S05" && selected.scenario_variant === "safe_partial";

  return (
    <div className={styles.tabStack}>
      <section className={styles.decisionGrid} aria-label="Решение и опорные сценарии">
        <article className={`${styles.recommendationHero} ${recommendationTone !== "accent" ? styles.recommendationUnavailable : ""}`}>
          <div className={styles.heroTopline}>
            <span className={styles.eyebrow}>Статус рекомендации</span>
            <div className={styles.badgeCluster}>
              <StatusBadge tone={recommendationTone}>{decisionLabel(result.recommendation.decision_status)}</StatusBadge>
              {result.recommendation.review_status === "manual_review_required" ? (
                <StatusBadge tone="warning">{reviewLabel(result.recommendation.review_status)}</StatusBadge>
              ) : null}
            </div>
          </div>
          <h2>{result.recommendation.title}</h2>
          <p>{result.recommendation.display_text}</p>
          <p className={styles.decisionScope}>{result.recommendation.decision_scope_text}</p>
          <div className={styles.heroScenarioLine}>
            <strong>S{scenarioNumber(selected.scenario_id)} · {scenarioDisplayName(selected)}</strong>
            {scenarioAnchorLabel(selected) ? <StatusBadge tone={isPartial ? "warning" : "neutral"}>{scenarioAnchorLabel(selected)}</StatusBadge> : null}
          </div>
          {selected.status === "completed" ? (
            <>
              <BudgetSummary scenario={selected} />
              <button type="button" className={styles.heroAction} onClick={onOpenMediaPlan}>
                Открыть рассчитанный медиаплан
              </button>
            </>
          ) : null}
        </article>
        <div className={styles.anchorColumn}>
          <ScenarioAnchorCard scenario={source} />
          <ScenarioAnchorCard scenario={benchmark} />
        </div>
      </section>

      <PartialScenarioCallout scenario={benchmark} />

      {selected.status === "completed" ? (
        <section className={styles.metricSection} aria-labelledby="headline-metrics-title">
          <div className={styles.sectionHeading}>
            <div>
              <span className={styles.eyebrow}>S{scenarioNumber(selected.scenario_id)} · {scenarioDisplayName(selected)}</span>
              <h2 id="headline-metrics-title">Оборот и ROAS</h2>
            </div>
            <p>Все значения и диапазоны приходят из результата расчета. Браузер не пересчитывает метрики.</p>
          </div>
          <div className={styles.metricsGrid}>
            <QuantileSummary title="Дополнительный оборот" metric={selected.incremental_turnover} />
            <QuantileSummary
              title={isPartial ? "ROAS распределенной части" : "ROAS"}
              metric={selected.roas.allocated_budget}
              help="Дополнительный оборот относительно распределенного бюджета."
            />
            {isPartial ? (
              <QuantileSummary
                title="Отдача относительно всего запрошенного бюджета"
                metric={selected.roas.requested_budget}
                help="Основная метрика сравнения partial-плана: знаменатель — весь запрошенный бюджет."
              />
            ) : null}
          </div>
          <BudgetSummary scenario={selected} />
        </section>
      ) : (
        <UnavailableBlock title="Показатели сценария недоступны" description="Сервис не опубликовал безопасные KPI для этого состояния." />
      )}

      <RiskComposition risk={selected.risk_budget} />

      <UnavailableBlock
        title="Карта географий"
        description="Карта будет доступна после подключения утвержденного справочника координат."
      />

      {result.limitations.length > 0 ? (
        <section className={styles.limitationsSection} aria-labelledby="result-limitations-title">
          <div className={styles.sectionHeading}>
            <div><span className={styles.eyebrow}>Перед решением</span><h2 id="result-limitations-title">Ограничения результата</h2></div>
          </div>
          <ul className={styles.limitationsList}>
            {result.limitations.map((limitation) => <li key={limitation.code}>{limitation.display_text}</li>)}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
