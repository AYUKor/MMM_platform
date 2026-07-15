import type { ResultOverviewViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { formatPercent, formatRub } from "../../shared/formatters/metrics";
import { Card } from "../../shared/ui/Card";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import styles from "./result-overview.module.css";

interface CoveragePanelProps {
  model: ResultOverviewViewModel;
}

export function CoveragePanel({ model }: CoveragePanelProps) {
  const coverage = model.coverage;
  return (
    <Card as="section" className={styles.coveragePanel} aria-label="Покрытие расчета">
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.panelLabel}>Покрытие модели</span>
          <h2>{coverage.partial ? "Результат рассчитан частично" : "Бюджет покрыт моделью"}</h2>
        </div>
        <StatusBadge tone={coverage.partial ? "warning" : "accent"}>
          {formatPercent(coverage.modelCoverageShare)}
        </StatusBadge>
      </div>
      <p className={styles.coverageLead}>{coverage.status.description}</p>
      <dl className={styles.coverageGrid}>
        <div><dt>Загружено</dt><dd>{formatRub(coverage.uploadedBudgetRub)}</dd></div>
        <div><dt>В расчете модели</dt><dd>{formatRub(coverage.modelInputBudgetRub)}</dd></div>
        <div><dt>Рассчитано</dt><dd>{formatRub(coverage.calculatedBudgetRub)}</dd></div>
        <div><dt>Вне покрытия</dt><dd>{formatRub(coverage.unmodeledBudgetRub)}</dd></div>
        <div><dt>Не распределено</dt><dd>{formatRub(coverage.unallocatedBudgetRub)}</dd></div>
      </dl>
    </Card>
  );
}
