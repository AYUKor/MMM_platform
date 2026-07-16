import type {
  ResultOverviewViewModel,
  ScenarioViewModel,
} from "../../features/calculation-result/buildResultOverviewModel";
import {
  formatDecimal,
  formatInteger,
  formatPercent,
  formatRub,
} from "../../shared/formatters/metrics";
import { Card } from "../../shared/ui/Card";
import { RangeMetric } from "../../shared/ui/RangeMetric";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import styles from "./result-overview.module.css";

function ScenarioCard({ scenario }: { scenario: ScenarioViewModel }) {
  return (
    <Card
      className={`${styles.scenarioCard} ${scenario.recommended ? styles.scenarioRecommended : ""} ${!scenario.available ? styles.scenarioUnavailable : ""}`}
      aria-label={`${scenario.number}: ${scenario.title}`}
    >
      <header className={styles.scenarioHeader}>
        <div>
          <span className={styles.panelLabel}>{scenario.number}</span>
          <h3>{scenario.title}</h3>
        </div>
        <div className={styles.scenarioBadges}>
          {scenario.recommended ? <StatusBadge tone="accent">Рекомендация</StatusBadge> : null}
          {scenario.stableBenchmark ? <StatusBadge>Ориентир по устойчивости</StatusBadge> : null}
          {!scenario.available ? <StatusBadge tone="warning">Недоступно</StatusBadge> : null}
        </div>
      </header>
      <p className={styles.scenarioDescription}>{scenario.description}</p>

      <div className={styles.scenarioMetricBlock}>
        <div className={styles.scenarioMetricTitle}>
          <span>Дополнительный оборот</span>
          <strong>{formatRub(scenario.turnover?.p50 ?? null)}</strong>
        </div>
        <RangeMetric
          p10={scenario.turnover?.p10 ?? null}
          p50={scenario.turnover?.p50 ?? null}
          p90={scenario.turnover?.p90 ?? null}
          unit="RUB"
        />
      </div>
      <div className={styles.scenarioMetricBlock}>
        <div className={styles.scenarioMetricTitle}>
          <span>ROAS по обороту</span>
          <strong>{formatDecimal(scenario.roas?.p50 ?? null)}</strong>
        </div>
        <RangeMetric
          p10={scenario.roas?.p10 ?? null}
          p50={scenario.roas?.p50 ?? null}
          p90={scenario.roas?.p90 ?? null}
          unit={null}
        />
      </div>

      <dl className={styles.scenarioDetails}>
        <div><dt>Распределено</dt><dd>{formatRub(scenario.budget.allocatedRub)}</dd></div>
        <div><dt>Не распределено</dt><dd>{formatRub(scenario.budget.unallocatedRub)}</dd></div>
        <div><dt>Покрытие</dt><dd>{formatPercent(scenario.coverageShare)}</dd></div>
        <div><dt>Качество</dt><dd>{scenario.quality.label}</dd></div>
      </dl>

      <div className={styles.supportStrip} aria-label="Предупреждения сценария">
        <span>Обычные <strong>{formatInteger(scenario.support.elevated)}</strong></span>
        <span>Сильные <strong>{formatInteger(scenario.support.strong)}</strong></span>
        <span>Критичные <strong>{formatInteger(scenario.support.hard)}</strong></span>
        <span>Нарушения <strong>{formatInteger(scenario.support.policyViolations)}</strong></span>
      </div>
      <p className={styles.scenarioStatus}>{scenario.supportStatus.description}</p>
    </Card>
  );
}

export function ScenarioComparisonPanel({ model }: { model: ResultOverviewViewModel }) {
  return (
    <section className={styles.tabSection} aria-labelledby="scenarios-heading">
      <header className={styles.tabIntro}>
        <div>
          <span className={styles.panelLabel}>Сценарии 1–6</span>
          <h2 id="scenarios-heading">Сравнение вариантов медиаплана</h2>
        </div>
        <p>
          Показаны абсолютные значения и интервалы из готового результата. Интерфейс не
          ранжирует сценарии и не выбирает лучший вариант самостоятельно.
        </p>
      </header>
      <div className={styles.scenarioGrid}>
        {model.scenarios.map((scenario) => (
          <ScenarioCard key={scenario.id} scenario={scenario} />
        ))}
      </div>
      <p className={styles.contractNote}>
        Заказы показаны только в диагностическом режиме; показатель «на 100 000 пользователей»
        не рассчитывается. Вклад среднего чека не интерпретируется как изменение среднего чека.
      </p>
    </section>
  );
}
