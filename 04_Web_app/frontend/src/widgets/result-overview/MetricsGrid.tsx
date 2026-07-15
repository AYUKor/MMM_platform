import type { MetricViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { MetricCard } from "../../shared/ui/MetricCard";
import styles from "./result-overview.module.css";

interface MetricsGridProps {
  metrics: MetricViewModel[];
}

export function MetricsGrid({ metrics }: MetricsGridProps) {
  return (
    <section className={styles.metricsGrid} aria-label="Ключевые метрики">
      {metrics.map((metric) => <MetricCard key={metric.id} metric={metric} />)}
    </section>
  );
}
