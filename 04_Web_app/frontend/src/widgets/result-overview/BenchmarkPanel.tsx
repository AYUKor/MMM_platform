import type { ScenarioViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { formatDecimal, formatRub } from "../../shared/formatters/metrics";
import { Card } from "../../shared/ui/Card";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import styles from "./result-overview.module.css";

interface BenchmarkPanelProps {
  scenario: ScenarioViewModel;
}

export function BenchmarkPanel({ scenario }: BenchmarkPanelProps) {
  const isS5 = scenario.id === "S05";
  return (
    <Card className={styles.benchmark}>
      <div className={styles.panelLabel}>
        {isS5 ? "Ориентир по устойчивости" : "Исходный benchmark"}
      </div>
      <h2>{scenario.title}</h2>
      <p>{scenario.description}</p>
      <strong className={styles.benchmarkValue}>
        {formatRub(scenario.turnover?.p50 ?? null)}
      </strong>
      <span className={styles.benchmarkCaption}>Дополнительный оборот · p50</span>
      <dl className={styles.benchmarkList}>
        <div><dt>ROAS · p50</dt><dd>{formatDecimal(scenario.roas?.p50 ?? null)}</dd></div>
        <div><dt>Качество</dt><dd>{scenario.quality.label}</dd></div>
        <div><dt>Сравнение</dt><dd>Абсолютные значения</dd></div>
      </dl>
      <StatusBadge tone={isS5 ? "accent" : "neutral"}>
        {isS5 ? "Ориентир по устойчивости" : "Как загрузили"}
      </StatusBadge>
    </Card>
  );
}
