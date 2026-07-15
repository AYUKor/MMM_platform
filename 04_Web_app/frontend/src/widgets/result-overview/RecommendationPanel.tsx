import type { ResultOverviewViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { formatDecimal, formatRub } from "../../shared/formatters/metrics";
import { Card } from "../../shared/ui/Card";
import styles from "./result-overview.module.css";

interface RecommendationPanelProps {
  model: ResultOverviewViewModel;
}

export function RecommendationPanel({ model }: RecommendationPanelProps) {
  const turnover = model.recommendedScenario.turnover;
  return (
    <Card className={styles.recommendation}>
      <div className={styles.recommendationContour} aria-hidden="true" />
      <div className={styles.panelLabel}>Рекомендация по allocation</div>
      <h2>{model.recommendation.title}</h2>
      <strong className={styles.scenarioName}>{model.recommendation.scenarioName}</strong>

      <div className={styles.heroMetrics}>
        <div>
          <strong>{formatRub(turnover?.p50 ?? null)}</strong>
          <span>Доп. оборот · p50</span>
        </div>
        <div>
          <strong>{formatDecimal(model.recommendedScenario.roasP50)}</strong>
          <span>ROAS · p50</span>
        </div>
        <div>
          <strong>Нет данных</strong>
          <span>Надёжность</span>
        </div>
      </div>

      <p className={styles.recommendationReason}>{model.recommendation.reason}</p>
      <p className={styles.allocationNotice}>{model.recommendation.allocationOnlyNotice}</p>
      <div className={styles.recommendationFooter}>
        <span>{model.recommendation.planStatus}</span>
        <span>{model.recommendation.qualityStatus}</span>
      </div>
    </Card>
  );
}
