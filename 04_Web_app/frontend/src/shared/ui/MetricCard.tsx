import type { MetricViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { formatMetricValue } from "../formatters/metrics";
import { Card } from "./Card";
import { RangeMetric } from "./RangeMetric";
import styles from "./ui.module.css";

interface MetricCardProps {
  metric: MetricViewModel;
}

export function MetricCard({ metric }: MetricCardProps) {
  return (
    <Card className={styles.metricCard} aria-label={metric.title}>
      <h3>{metric.title}</h3>
      <div className={styles.metricValue}>
        {formatMetricValue(metric.p50, metric.unit)}
      </div>
      <RangeMetric
        p10={metric.p10}
        p50={metric.p50}
        p90={metric.p90}
        unit={metric.unit}
      />
      <p className={metric.tone === "warning" ? styles.warningNote : styles.metricNote}>
        {metric.note}
      </p>
    </Card>
  );
}
