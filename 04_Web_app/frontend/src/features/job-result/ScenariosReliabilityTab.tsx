import type {
  JobResultViewV2,
  Scenario,
} from "../../shared/api/generated/job-result-view-v2";
import { formatInteger, formatPercent, formatRub } from "../../shared/formatters/metrics";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import {
  decisionLabel,
  decisionTone,
  quantileRange,
  quantileValue,
  reliabilityLabel,
  reliabilityTone,
  reviewLabel,
  scenarioAnchorLabel,
  scenarioDisplayName,
  scenarioNumber,
  scenarioStatusLabel,
  scenarioVariantTitle,
} from "./jobResultFormatting";
import styles from "./job-result.module.css";

function ScenarioSpecificCopy({ scenario }: { scenario: Scenario }) {
  if (
    scenario.scenario_id === "S01" &&
    scenario.decision_status === "keep_uploaded_plan" &&
    scenario.review_status === "manual_review_required"
  ) {
    return (
      <p className={styles.scenarioCallout}>
        Исходный план показан как точка отсчета. Он не является рекомендацией системы и требует ручной проверки.
      </p>
    );
  }
  if (scenario.scenario_id === "S05" && scenario.scenario_variant === "full_conservative") {
    return (
      <p className={styles.scenarioCallout}>
        Система распределила весь бюджет по наименее рискованному из доступных вариантов.
      </p>
    );
  }
  if (scenario.scenario_id === "S05" && scenario.scenario_variant === "safe_partial") {
    return (
      <p className={styles.scenarioCallout}>
        Весь бюджет нельзя распределить с приемлемой надежностью. Показана только безопасно распределяемая часть; остаток требует ручного решения.
      </p>
    );
  }
  return null;
}

function InfeasibleScenario({ scenario }: { scenario: Scenario }) {
  return (
    <div className={styles.infeasibleScenario} role="status">
      <StatusBadge tone="neutral">Недоступно при текущих ограничениях</StatusBadge>
      <h3>Полный план максимального эффекта недоступен</h3>
      <p>При текущих каналах, географиях и ограничениях модели невозможно распределить весь бюджет.</p>
      {scenario.limiting_constraints.length > 0 ? (
        <details>
          <summary>Что ограничило расчет</summary>
          <ul>{scenario.limiting_constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}</ul>
        </details>
      ) : null}
    </div>
  );
}

function ScenarioBudget({ scenario }: { scenario: Scenario }) {
  return (
    <dl className={styles.scenarioBudget}>
      <div><dt>Запрошенный бюджет</dt><dd>{formatRub(scenario.budget.requested_budget_rub)}</dd></div>
      <div><dt>Распределено</dt><dd>{formatRub(scenario.budget.allocated_budget_rub)}</dd></div>
      <div><dt>Не распределено</dt><dd>{formatRub(scenario.budget.unallocated_budget_rub)}</dd></div>
      <div><dt>Доля распределения</dt><dd>{formatPercent(scenario.budget.allocation_share)}</dd></div>
    </dl>
  );
}

function ScenarioMetrics({ scenario }: { scenario: Scenario }) {
  const partial = scenario.scenario_id === "S05" && scenario.scenario_variant === "safe_partial";
  return (
    <div className={styles.scenarioMetrics}>
      <dl>
        <div>
          <dt>Дополнительный оборот · P50</dt>
          <dd>{quantileValue(scenario.incremental_turnover, scenario.incremental_turnover.p50)}</dd>
          <small>P10–P90: {quantileRange(scenario.incremental_turnover)}</small>
        </div>
        <div>
          <dt>{partial ? "ROAS распределенной части" : "ROAS"}</dt>
          <dd>{quantileValue(scenario.roas.allocated_budget, scenario.roas.allocated_budget.p50)}</dd>
          <small>Знаменатель: распределенный бюджет</small>
        </div>
        {partial ? (
          <div>
            <dt>Отдача относительно всего запрошенного бюджета</dt>
            <dd>{quantileValue(scenario.roas.requested_budget, scenario.roas.requested_budget.p50)}</dd>
            <small>Знаменатель: весь запрошенный бюджет</small>
          </div>
        ) : null}
      </dl>
      <dl className={styles.compactRisk} aria-label="Состав риска">
        <div><dt>Внутри надежного диапазона</dt><dd>{formatRub(scenario.risk_budget.within_support_budget_rub)} · {formatPercent(scenario.risk_budget.within_support_share)}</dd></div>
        <div><dt>Контролируемое расширение</dt><dd>{formatRub(scenario.risk_budget.controlled_extrapolation_budget_rub)} · {formatPercent(scenario.risk_budget.controlled_extrapolation_share)}</dd></div>
        <div><dt>Высокий риск</dt><dd>{formatRub(scenario.risk_budget.high_risk_budget_rub)} · {formatPercent(scenario.risk_budget.high_risk_share)}</dd></div>
      </dl>
    </div>
  );
}

function ScenarioCard({ scenario }: { scenario: Scenario }) {
  const partial = scenario.scenario_id === "S05" && scenario.scenario_variant === "safe_partial";
  const anchor = scenarioAnchorLabel(scenario);
  const displayName = scenarioDisplayName(scenario);
  const variantTitle = scenarioVariantTitle(scenario);
  const canUseGreenRecommendation = scenario.is_recommended && scenario.decision_status === "recommended_reallocation" && !partial;
  return (
    <article className={`${styles.scenarioDetailCard} ${partial ? styles.partialCard : ""}`} id={`scenario-${scenario.scenario_id}`}>
      <header>
        <div className={styles.scenarioIdentity}>
          <span>S{scenarioNumber(scenario.scenario_id)}</span>
          <div>
            <h2>{displayName}</h2>
            {variantTitle && variantTitle !== displayName ? <strong>{variantTitle}</strong> : null}
          </div>
        </div>
        <div className={styles.badgeCluster}>
          {anchor ? <StatusBadge tone={partial ? "warning" : "neutral"}>{anchor}</StatusBadge> : null}
          <StatusBadge tone={scenario.status === "completed" ? "neutral" : "warning"}>{scenarioStatusLabel(scenario)}</StatusBadge>
          {canUseGreenRecommendation ? <StatusBadge tone="accent">Рекомендованный вариант</StatusBadge> : null}
        </div>
      </header>
      <p className={styles.scenarioDescription}>{scenario.description}</p>
      <div className={styles.scenarioDecisionRow}>
        <StatusBadge tone={decisionTone(scenario.decision_status)}>{decisionLabel(scenario.decision_status)}</StatusBadge>
        {scenario.review_status === "manual_review_required" ? (
          <StatusBadge tone="warning">{reviewLabel(scenario.review_status)}</StatusBadge>
        ) : null}
        <StatusBadge tone={reliabilityTone(scenario.reliability.status)}>{reliabilityLabel(scenario.reliability.status)}</StatusBadge>
      </div>
      <ScenarioSpecificCopy scenario={scenario} />
      {scenario.status === "infeasible" ? (
        <InfeasibleScenario scenario={scenario} />
      ) : scenario.status === "completed" ? (
        <>
          <ScenarioBudget scenario={scenario} />
          <ScenarioMetrics scenario={scenario} />
        </>
      ) : (
        <p className={styles.inlineUnavailable}>Показатели для этого сценария не опубликованы.</p>
      )}
      <footer className={styles.scenarioFooter}>
        <span>{scenario.reliability.display_text}</span>
        <span>Место с учетом надежности: {scenario.reliability.safe_rank === null ? "Нет данных" : formatInteger(scenario.reliability.safe_rank)}</span>
      </footer>
    </article>
  );
}

export function ScenariosReliabilityTab({ result }: { result: JobResultViewV2 }) {
  return (
    <div className={styles.tabStack}>
      <section className={styles.tabIntro}>
        <div>
          <span className={styles.eyebrow}>Шесть рассчитанных вариантов</span>
          <h2>Сценарии и надежность</h2>
        </div>
        <p>Места сценариев учитывают ожидаемый эффект и ограничения надежности. S1 всегда остается точкой отсчета, S5 — осторожным сценарием.</p>
      </section>
      <div className={styles.scenarioDetailList}>
        {result.scenarios.map((scenario) => <ScenarioCard key={scenario.scenario_id} scenario={scenario} />)}
      </div>
    </div>
  );
}
