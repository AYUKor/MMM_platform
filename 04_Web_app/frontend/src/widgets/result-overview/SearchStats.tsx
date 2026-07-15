import type { ResultOverviewViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { formatInteger } from "../../shared/formatters/metrics";
import { Card } from "../../shared/ui/Card";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import styles from "./result-overview.module.css";

interface SearchStatsProps {
  model: ResultOverviewViewModel;
}

export function SearchStats({ model }: SearchStatsProps) {
  return (
    <Card className={styles.searchCard}>
      <div className={styles.sectionHeading}>
        <h2>Адаптивный поиск</h2>
        <StatusBadge tone={model.s6.available ? "accent" : "warning"}>
          {model.s6.available ? "S6 доступен" : "S6 недоступен"}
        </StatusBadge>
      </div>
      <dl className={styles.searchStats}>
        <div><dt>Проверено попыток</dt><dd>{formatInteger(model.search.attemptsEvaluated)}</dd></div>
        <div><dt>Оценено кандидатов</dt><dd>{formatInteger(model.search.candidatesScored)}</dd></div>
        <div><dt>Отклонено кандидатов</dt><dd>{formatInteger(model.search.candidatesRejected)}</dd></div>
        <div><dt>Финалистов</dt><dd>{formatInteger(model.search.finalists)}</dd></div>
      </dl>
      <p className={styles.searchStatus}>{model.search.status.label}. {model.search.status.description}</p>
      {!model.s6.available ? <p className={styles.unavailableReason}>{model.s6.message}</p> : null}
    </Card>
  );
}
