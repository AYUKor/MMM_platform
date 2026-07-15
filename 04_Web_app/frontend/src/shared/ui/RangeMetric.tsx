import { formatMetricValue } from "../formatters/metrics";
import styles from "./ui.module.css";

interface RangeMetricProps {
  p10: number | null;
  p50: number | null;
  p90: number | null;
  unit: string | null;
}

export function RangeMetric({ p10, p50, p90, unit }: RangeMetricProps) {
  return (
    <div className={styles.range} aria-label="Диапазон p10, p50, p90">
      <div className={styles.rangeValues}>
        <span><small>p10</small>{formatMetricValue(p10, unit)}</span>
        <span className={styles.rangeMedian}><small>p50</small>{formatMetricValue(p50, unit)}</span>
        <span><small>p90</small>{formatMetricValue(p90, unit)}</span>
      </div>
      <div className={styles.rangeTrack} aria-hidden="true">
        <i />
      </div>
    </div>
  );
}
