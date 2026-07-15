import type {
  ResultCopyTone,
} from "../../features/calculation-result/resultCopy";
import type { ResultOverviewViewModel } from "../../features/calculation-result/buildResultOverviewModel";
import { formatDecimal, formatRub } from "../../shared/formatters/metrics";
import { Card } from "../../shared/ui/Card";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import { Caveats } from "./Caveats";
import { CoveragePanel } from "./DataGapPanel";
import { SearchStats } from "./SearchStats";
import styles from "./result-overview.module.css";

function badgeTone(tone: ResultCopyTone): "neutral" | "accent" | "warning" | "danger" {
  if (tone === "positive") return "accent";
  return tone;
}

function CandidateCard({
  title,
  description,
  available,
  eligible,
  turnoverP50,
  roasP50,
}: {
  title: string;
  description: string;
  available: boolean;
  eligible: boolean;
  turnoverP50: number | null;
  roasP50: number | null;
}) {
  return (
    <Card className={styles.candidateCard}>
      <div className={styles.sectionHeading}>
        <h3>{title}</h3>
        <StatusBadge tone={available && eligible ? "accent" : "warning"}>
          {!available ? "Нет данных" : eligible ? "Допустим" : "Только для проверки"}
        </StatusBadge>
      </div>
      <p>{description}</p>
      <dl className={styles.candidateMetrics}>
        <div><dt>Доп. оборот · p50</dt><dd>{formatRub(turnoverP50)}</dd></div>
        <div><dt>ROAS · p50</dt><dd>{formatDecimal(roasP50)}</dd></div>
      </dl>
    </Card>
  );
}

export function ReliabilityPanel({ model }: { model: ResultOverviewViewModel }) {
  return (
    <section className={styles.tabSection} aria-labelledby="reliability-heading">
      <header className={styles.tabIntro}>
        <div>
          <span className={styles.panelLabel}>Надежность</span>
          <h2 id="reliability-heading">Что можно использовать и с какой осторожностью</h2>
        </div>
        <p>
          Здесь нет придуманного балла надежности. Показаны только статусы, покрытие,
          ограничения и предупреждения, переданные сервисом расчета.
        </p>
      </header>

      <div className={styles.statusGrid}>
        {model.statuses.map((status) => (
          <Card key={status.id} className={styles.statusCard}>
            <div className={styles.sectionHeading}>
              <h3>{status.title}</h3>
              <StatusBadge tone={badgeTone(status.copy.tone)}>{status.copy.label}</StatusBadge>
            </div>
            <p>{status.copy.description}</p>
          </Card>
        ))}
      </div>

      <CoveragePanel model={model} />

      <section className={styles.s6Audit} aria-labelledby="s6-audit-heading">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.panelLabel}>Адаптивный поиск</span>
            <h2 id="s6-audit-heading">Вариант до проверок и допустимый вариант</h2>
          </div>
          <StatusBadge tone={badgeTone(model.search.status.tone)}>
            {model.search.status.label}
          </StatusBadge>
        </div>
        <p className={styles.sectionLead}>
          {model.search.rawDiffersFromSafe
            ? "Вариант с максимальным сырым результатом отличается от варианта, прошедшего ограничения."
            : "Сервис не сообщил о различии между исходным и допустимым вариантами."}
        </p>
        <div className={styles.candidateGrid}>
          <CandidateCard
            title="Лучший вариант до проверок"
            description="Показан только для аудита. Он не становится рекомендацией без прохождения ограничений."
            available={model.search.bestRaw.available}
            eligible={model.search.bestRaw.eligible}
            turnoverP50={model.search.bestRaw.turnover?.p50 ?? null}
            roasP50={model.search.bestRaw.roas?.p50 ?? null}
          />
          <CandidateCard
            title="Лучший допустимый вариант"
            description="Этот вариант прошел доступные проверки и может быть использован только в заявленных границах."
            available={model.search.bestSafe.available}
            eligible={model.search.bestSafe.eligible}
            turnoverP50={model.search.bestSafe.turnover?.p50 ?? null}
            roasP50={model.search.bestSafe.roas?.p50 ?? null}
          />
          <SearchStats model={model} />
        </div>
      </section>

      <Caveats warnings={model.warnings} />
    </section>
  );
}
