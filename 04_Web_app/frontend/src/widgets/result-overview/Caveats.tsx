import type { WarningViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { Card } from "../../shared/ui/Card";
import styles from "./result-overview.module.css";

interface CaveatsProps {
  warnings: WarningViewModel[];
  limit?: number;
}

export function Caveats({ warnings, limit }: CaveatsProps) {
  const visibleWarnings = typeof limit === "number" ? warnings.slice(0, limit) : warnings;
  return (
    <Card as="section" className={styles.caveats}>
      <h2>Что важно учитывать</h2>
      {visibleWarnings.length > 0 ? (
        <div className={styles.caveatList}>
          {visibleWarnings.map((warning) => (
            <article key={warning.id} className={styles.caveatItem}>
              <strong>{warning.title}</strong>
              <p>{warning.meaning}</p>
              <span>Что сделать: {warning.action}</span>
            </article>
          ))}
        </div>
      ) : (
        <p>Дополнительных предупреждений нет.</p>
      )}
    </Card>
  );
}
