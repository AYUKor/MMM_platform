import type {
  Quantiles,
  RiskBudget,
} from "../../shared/api/generated/job-result-view-v2";
import { formatInteger, formatPercent, formatRub } from "../../shared/formatters/metrics";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import { quantileRange, quantileValue } from "./jobResultFormatting";
import styles from "./job-result.module.css";

export function QuantileSummary({
  title,
  metric,
  help,
}: {
  title: string;
  metric: Quantiles;
  help?: string;
}) {
  return (
    <article className={styles.metricCard}>
      <div className={styles.metricHeading}>
        <h3>{title}</h3>
        <StatusBadge tone={metric.status === "available" ? "neutral" : "warning"}>
          {metric.status === "available" ? "P50" : "Нет данных"}
        </StatusBadge>
      </div>
      <strong className={styles.metricValue}>{quantileValue(metric, metric.p50)}</strong>
      <span className={styles.metricRange}>Неопределенность P10–P90: {quantileRange(metric)}</span>
      {help ? <p className={styles.metricHelp}>{help}</p> : null}
    </article>
  );
}

const riskRows = [
  {
    key: "within",
    label: "Внутри надежного диапазона",
    budget: "within_support_budget_rub",
    share: "within_support_share",
    cells: "within_support_cells_n",
  },
  {
    key: "controlled",
    label: "Контролируемое расширение",
    budget: "controlled_extrapolation_budget_rub",
    share: "controlled_extrapolation_share",
    cells: "controlled_extrapolation_cells_n",
  },
  {
    key: "high",
    label: "Высокий риск",
    budget: "high_risk_budget_rub",
    share: "high_risk_share",
    cells: "high_risk_cells_n",
  },
] as const;

export function RiskComposition({ risk }: { risk: RiskBudget }) {
  return (
    <section className={styles.riskPanel} aria-labelledby="risk-composition-title">
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>Состав риска</span>
          <h2 id="risk-composition-title">Где находится распределенный бюджет</h2>
        </div>
        <p>Суммы и доли получены из результата расчета. Цвет не является единственным обозначением статуса.</p>
      </div>
      <div className={styles.riskBars}>
        {riskRows.map((row) => {
          const share = risk[row.share];
          return (
            <article className={`${styles.riskRow} ${styles[`risk_${row.key}`]}`} key={row.key}>
              <div>
                <strong>{row.label}</strong>
                <span>{formatInteger(risk[row.cells])} связок</span>
              </div>
              <div className={styles.riskTrack} aria-hidden="true">
                <span style={{ width: share === null ? "0%" : `${Math.max(0, Math.min(1, share)) * 100}%` }} />
              </div>
              <dl>
                <div><dt>Бюджет</dt><dd>{formatRub(risk[row.budget])}</dd></div>
                <div><dt>Доля</dt><dd>{formatPercent(share)}</dd></div>
              </dl>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function UnavailableBlock({ title, description }: { title: string; description: string }) {
  return (
    <section className={styles.unavailableBlock} role="status">
      <span className={styles.eyebrow}>Пока недоступно</span>
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}
