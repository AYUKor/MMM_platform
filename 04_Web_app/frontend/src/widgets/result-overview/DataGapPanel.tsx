import { Card } from "../../shared/ui/Card";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import styles from "./result-overview.module.css";

export function DataGapPanel() {
  return (
    <section className={styles.dataGapGrid} aria-label="Изменения медиаплана">
      <Card className={styles.dataGapCard}>
        <div className={styles.sectionHeading}>
          <h2>Бюджет по каналам · было / рекомендуется</h2>
          <StatusBadge>Нет данных</StatusBadge>
        </div>
        <div className={styles.dataGapVisual} aria-hidden="true"><i /><i /><i /><i /></div>
        <p>В contract отсутствует исходная allocation. Frontend не восстанавливает before/after.</p>
      </Card>
      <Card className={styles.dataGapCard}>
        <div className={styles.sectionHeading}>
          <h2>Гео с наибольшими изменениями</h2>
          <StatusBadge>Нет данных</StatusBadge>
        </div>
        <div className={styles.dataGapVisual} aria-hidden="true"><i /><i /><i /><i /></div>
        <p>Baseline по geo не передан, поэтому deltas не рассчитываются на клиенте.</p>
      </Card>
    </section>
  );
}
