import { useMemo, useState } from "react";
import type {
  ModelPassportAllowedUse,
  ModelPassportEvidenceStatus,
  ModelPassportV1,
} from "../../entities/model-passport/types";
import {
  getAllowedUseCopy,
  getCalculationCopy,
  getDeploymentProfileCopy,
  getEvidenceCopy,
  getRecordOriginCopy,
  getTargetLabel,
} from "../../features/model-passport/modelPassportCopy";
import { formatDate, formatInteger } from "../../shared/formatters/metrics";
import { Card } from "../../shared/ui/Card";
import { PageHeader } from "../../shared/ui/PageHeader";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import styles from "./model-passport.module.css";

function EvidenceCard({
  title,
  evidence,
  note,
}: {
  title: string;
  evidence: ModelPassportV1["validation"]["historical_replay"];
  note: string;
}) {
  const copy = getEvidenceCopy(evidence.status as ModelPassportEvidenceStatus);
  return (
    <Card as="section" className={styles.evidenceCard}>
      <div className={styles.sectionHeading}>
        <h3>{title}</h3>
        <StatusBadge tone={copy.tone}>{copy.label}</StatusBadge>
      </div>
      <p>{evidence.display_text}</p>
      <small>{note}</small>
    </Card>
  );
}

function Count({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{formatInteger(value ?? null)}</dd>
    </div>
  );
}

export function ModelPassport({ passport }: { passport: ModelPassportV1 }) {
  const [segment, setSegment] = useState("all");
  const [target, setTarget] = useState("all");
  const [allowedUse, setAllowedUse] = useState<"all" | ModelPassportAllowedUse>("all");

  const originCopy = getRecordOriginCopy(passport.record_origin);
  const deploymentCopy = getDeploymentProfileCopy(passport.serving.deployment_profile);
  const calculationCopy = getCalculationCopy(passport.serving.calculation_allowed);
  const targetLabels = useMemo(
    () => new Map(
      passport.coverage.targets.map((entry, index) => [
        entry.target,
        getTargetLabel(entry.target, index + 1),
      ]),
    ),
    [passport.coverage.targets],
  );
  const targetLabel = (value: string) => (
    targetLabels.get(value) ?? "Показатель — название не поддерживается"
  );
  const policies = useMemo(
    () => passport.coverage.channel_policies.filter((policy) =>
      (segment === "all" || policy.segment === segment) &&
      (target === "all" || policy.target === target) &&
      (allowedUse === "all" || policy.allowed_use === allowedUse)),
    [allowedUse, passport.coverage.channel_policies, segment, target],
  );

  const shadow = passport.data.development_shadow_period;
  const shadowAvailable = shadow.start_date !== null && shadow.end_date !== null;

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow={<span>Model Passport</span>}
        title={passport.serving.display_name}
        meta={<span>{deploymentCopy.label} · контракт v{passport.schema_version}</span>}
        actions={(
          <div className={styles.headerBadges}>
            <StatusBadge tone={originCopy.tone}>{originCopy.label}</StatusBadge>
            <StatusBadge tone="warning">Research / preprod</StatusBadge>
          </div>
        )}
      />

      <section className={styles.researchBoundary} aria-labelledby="research-boundary-title">
        <div>
          <span className={styles.kicker}>Граница применения</span>
          <h2 id="research-boundary-title">Исследовательская / preprod модель</h2>
        </div>
        <div className={styles.boundaryCopy}>
          <p>
            Модель предназначена для research-прогноза и распределения бюджета. Она не
            имеет статуса production-ready.
          </p>
          <p>
            Рекомендация относится к распределению бюджета и не является решением
            запускать или отменять кампанию.
          </p>
        </div>
      </section>

      {passport.record_origin === "synthetic_fixture" ? (
        <Card as="section" className={styles.demoNotice} role="status">
          <strong>Демонстрационные данные</strong>
          <p>{originCopy.description}</p>
        </Card>
      ) : null}

      <div className={styles.summaryGrid}>
        <Card as="section" className={styles.summaryPanel}>
          <span className={styles.kicker}>Данные</span>
          <h2>Период обучения</h2>
          <div className={styles.periodValue}>
            <time dateTime={passport.data.training_period.start_date}>
              {formatDate(passport.data.training_period.start_date)}
            </time>
            <span aria-hidden="true">→</span>
            <time dateTime={passport.data.training_period.end_date}>
              {formatDate(passport.data.training_period.end_date)}
            </time>
          </div>
          <p>Дневная гранулярность данных.</p>
          <dl className={styles.definitionList}>
            <div>
              <dt>Период development shadow</dt>
              <dd>
                {shadowAvailable
                  ? `${formatDate(shadow.start_date as string)} — ${formatDate(shadow.end_date as string)}`
                  : "Нет данных"}
              </dd>
            </div>
          </dl>
          <small>Development shadow — не sealed OOT и не заменяет независимую OOT-проверку.</small>
        </Card>

        <Card as="section" className={styles.summaryPanel}>
          <div className={styles.sectionHeading}>
            <div>
              <span className={styles.kicker}>Пакет модели</span>
              <h2>Статус использования</h2>
            </div>
            <StatusBadge tone={calculationCopy.tone}>{calculationCopy.label}</StatusBadge>
          </div>
          <p>{calculationCopy.description}</p>
          <dl className={styles.definitionList}>
            <div><dt>Источник паспорта</dt><dd>{originCopy.label}</dd></div>
            <div><dt>Контур</dt><dd>{deploymentCopy.label}</dd></div>
            <div><dt>Область решения</dt><dd>Прогноз и распределение бюджета</dd></div>
            <div><dt>Production-статус</dt><dd>Не разрешён</dd></div>
          </dl>
        </Card>
      </div>

      <section className={styles.section} aria-labelledby="validation-heading">
        <header className={styles.sectionIntro}>
          <div>
            <span className={styles.kicker}>Проверки модели</span>
            <h2 id="validation-heading">Replay и независимая OOT-проверка</h2>
          </div>
          <p>Эти проверки описывают подтверждения модели, а не качество конкретной кампании.</p>
        </header>
        <div className={styles.evidenceGrid}>
          <EvidenceCard
            title="Historical replay"
            evidence={passport.validation.historical_replay}
            note="Проверяет воспроизводимость на исторических данных."
          />
          <EvidenceCard
            title="Sealed OOT"
            evidence={passport.validation.sealed_oot}
            note="Отсутствие OOT не блокирует research-расчеты, но не разрешает production claim."
          />
        </div>
      </section>

      <section className={styles.section} aria-labelledby="coverage-heading">
        <header className={styles.sectionIntro}>
          <div>
            <span className={styles.kicker}>Покрытие</span>
            <h2 id="coverage-heading">Что покрывает модель</h2>
          </div>
          <p>Политика сохраняется на точном уровне «сегмент × канал × показатель».</p>
        </header>
        <dl className={styles.coverageStats}>
          <Count label="Сегменты" value={passport.coverage.segments.length} />
          <Count label="Каналы" value={passport.coverage.channels.length} />
          <Count label="Географии" value={passport.coverage.geographies_n} />
          <Count label="Комбинации правил" value={passport.coverage.capability_cells_n} />
          <Count label="Основные" value={passport.coverage.allowed_use_counts.primary} />
          <Count label="С осторожностью" value={passport.coverage.allowed_use_counts.caution} />
          <Count label="Диагностика" value={passport.coverage.allowed_use_counts.diagnostic} />
          <Count label="Недоступны" value={passport.coverage.allowed_use_counts.unavailable} />
        </dl>

        <div className={styles.coverageAxes}>
          <div>
            <h3>Сегменты</h3>
            <p>{passport.coverage.segments.length > 0 ? passport.coverage.segments.join(", ") : "Нет данных"}</p>
          </div>
          <div>
            <h3>Каналы</h3>
            <p>{passport.coverage.channels.length > 0 ? passport.coverage.channels.join(", ") : "Нет данных"}</p>
          </div>
        </div>

        {passport.coverage.targets.length === 0 ? (
          <Card as="section" className={styles.emptyPolicies} role="status">
            <strong>Нет данных</strong>
            <p>Сервис моделей не передал показатели покрытия.</p>
          </Card>
        ) : (
          <div className={styles.targetGrid}>
            {passport.coverage.targets.map((targetSummary) => (
              <article className={styles.targetSummary} key={targetSummary.target}>
                <h3>{targetLabel(targetSummary.target)}</h3>
                <dl>
                  <Count label="Основные" value={targetSummary.allowed_use_counts.primary} />
                  <Count label="Осторожно" value={targetSummary.allowed_use_counts.caution} />
                  <Count label="Диагностика" value={targetSummary.allowed_use_counts.diagnostic} />
                  <Count label="Недоступны" value={targetSummary.allowed_use_counts.unavailable} />
                </dl>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className={styles.section} aria-labelledby="policies-heading">
        <header className={styles.sectionIntro}>
          <div>
            <span className={styles.kicker}>Правила каналов</span>
            <h2 id="policies-heading">Правила использования каналов</h2>
          </div>
          <p>Режим применения одного канала может различаться для разных показателей.</p>
        </header>

        <div className={styles.filters}>
          <label>
            Сегмент
            <select value={segment} onChange={(event) => setSegment(event.target.value)}>
              <option value="all">Все сегменты</option>
              {passport.coverage.segments.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>
            Показатель
            <select value={target} onChange={(event) => setTarget(event.target.value)}>
              <option value="all">Все показатели</option>
              {passport.coverage.targets.map((value) => (
                <option key={value.target} value={value.target}>{targetLabel(value.target)}</option>
              ))}
            </select>
          </label>
          <label>
            Применение
            <select
              value={allowedUse}
              onChange={(event) => setAllowedUse(event.target.value as "all" | ModelPassportAllowedUse)}
            >
              <option value="all">Все статусы</option>
              {(["primary", "caution", "diagnostic", "unavailable"] as const).map((value) => (
                <option key={value} value={value}>{getAllowedUseCopy(value).label}</option>
              ))}
            </select>
          </label>
          <span className={styles.filterCount} aria-live="polite">
            Показано: {formatInteger(policies.length)}
          </span>
        </div>

        {policies.length === 0 ? (
          <Card as="section" className={styles.emptyPolicies} role="status">
            <strong>Нет данных</strong>
            <p>Для выбранных фильтров нет правил использования.</p>
          </Card>
        ) : (
          <>
            <div className={styles.policyTableWrap}>
              <table className={styles.policyTable}>
                <caption className="sr-only">Правила использования каналов по сегментам и показателям</caption>
                <thead>
                  <tr><th>Сегмент</th><th>Канал</th><th>Показатель</th><th>Применение</th><th>Пояснение</th></tr>
                </thead>
                <tbody>
                  {policies.map((policy) => {
                    const copy = getAllowedUseCopy(policy.allowed_use);
                    return (
                      <tr key={`${policy.segment}:${policy.channel}:${policy.target}`}>
                        <td>{policy.segment}</td>
                        <td>{policy.channel}</td>
                        <td>{targetLabel(policy.target)}</td>
                        <td><StatusBadge tone={copy.tone}>{copy.label}</StatusBadge></td>
                        <td>{policy.display_text}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className={styles.policyCards}>
              {policies.map((policy) => {
                const copy = getAllowedUseCopy(policy.allowed_use);
                return (
                  <article className={styles.policyCard} key={`${policy.segment}:${policy.channel}:${policy.target}`}>
                    <div className={styles.sectionHeading}>
                      <div><strong>{policy.channel}</strong><span>{policy.segment}</span></div>
                      <StatusBadge tone={copy.tone}>{copy.label}</StatusBadge>
                    </div>
                    <h3>{targetLabel(policy.target)}</h3>
                    <p>{policy.display_text}</p>
                  </article>
                );
              })}
            </div>
          </>
        )}
      </section>

      <section className={styles.boundaries} aria-labelledby="blockers-heading">
        <div>
          <span className={styles.kicker}>Блокеры production-статуса</span>
          <h2 id="blockers-heading">Что блокирует production claim</h2>
          {passport.validation.production_blockers.length > 0 ? (
            <ul>
              {passport.validation.production_blockers.map((blocker, index) => (
                <li key={`${blocker.code}:${index}`}>{blocker.display_text}</li>
              ))}
            </ul>
          ) : <p>Дополнительные blockers не переданы. Production claim всё равно запрещён контрактом.</p>}
        </div>
        <div>
          <span className={styles.kicker}>Ограничения</span>
          <h2>Как интерпретировать паспорт</h2>
          {passport.caveats.length > 0 ? (
            <ul>
              {passport.caveats.map((caveat, index) => (
                <li key={`${caveat.code}:${index}`}>{caveat.display_text}</li>
              ))}
            </ul>
          ) : <p>Дополнительные caveats не переданы.</p>}
        </div>
      </section>
    </div>
  );
}
