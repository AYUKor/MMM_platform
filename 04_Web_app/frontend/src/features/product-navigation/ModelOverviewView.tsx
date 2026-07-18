import type { ModelOverviewV2 } from "../../shared/api/generated/model-overview-v2";
import type { ModelPassportV2 } from "../../shared/api/generated/model-passport-v2";
import { formatDate, formatInteger } from "../../shared/formatters/metrics";
import { RefreshNotice } from "./ProductNavigationPageState";
import styles from "./product-navigation.module.css";

interface ModelOverviewViewProps {
  passport: ModelPassportV2;
  overview: ModelOverviewV2;
  refreshMessage?: string | null;
  onRefresh: () => void;
}

type EvidenceStatus = ModelOverviewV2["summary"]["historical_replay"]["status"];

function periodLabel(period: { start_date: string; end_date: string }): string {
  return `${formatDate(period.start_date)} — ${formatDate(period.end_date)}`;
}

function nullablePeriodLabel(period: { start_date: string | null; end_date: string | null }): string {
  return period.start_date && period.end_date
    ? `${formatDate(period.start_date)} — ${formatDate(period.end_date)}`
    : "Нет данных";
}

function evidenceLabel(status: EvidenceStatus): string {
  if (status === "passed") return "Пройдено";
  if (status === "failed") return "Не пройдено";
  return "Нет данных";
}

function evidenceClass(status: EvidenceStatus): string {
  if (status === "passed") return styles.statusSuccess;
  if (status === "failed") return styles.statusDanger;
  return styles.statusNeutral;
}

function packageStatusLabel(value: string | null): string {
  if (value === "posterior_ready") return "Пакет подготовлен";
  if (value === null) return "Нет данных";
  return "Статус требует проверки";
}

function activationStatusLabel(value: string | null): string {
  if (value === "preprod_restricted") return "Исследовательский / preprod";
  if (value === null) return "Нет данных";
  return "Статус требует проверки";
}

function policyLabel(value: string): string {
  if (value === "primary") return "Основное использование";
  if (value === "caution") return "С осторожностью";
  if (value === "diagnostic") return "Только для проверки";
  if (["unavailable", "unsupported"].includes(value)) return "Недоступно";
  return "Требует проверки";
}

function policyClass(value: string): string {
  if (value === "primary") return styles.statusSuccess;
  if (value === "caution") return styles.statusActive;
  return styles.statusNeutral;
}

export function ModelOverviewView({
  passport,
  overview,
  refreshMessage = null,
  onRefresh,
}: ModelOverviewViewProps) {
  const serving = passport.serving;
  const ready = serving.calculation_allowed && overview.summary.calculation_allowed;
  const constraints = [
    ...passport.validation.production_blockers.map((item) => ({
      kind: "Блокер публикации",
      title: "Что мешает production-использованию",
      text: item.display_text,
      action: null as string | null,
    })),
    ...overview.limitations.map((item) => ({
      kind: "Ограничение модели",
      title: item.title ?? "Что нужно учитывать",
      text: item.display_text,
      action: item.recommended_action ?? null,
    })),
    ...passport.caveats.map((item) => ({
      kind: "Важно",
      title: "Граница использования",
      text: item.display_text,
      action: null as string | null,
    })),
  ].filter((item, index, items) => (
    items.findIndex((candidate) => candidate.text === item.text) === index
  ));

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <div className={styles.headerLabels}>
            <span className={styles.eyebrow}>Как устроен расчет</span>
            {passport.record_origin === "synthetic_fixture" ? (
              <span className={styles.demoBadge}>Демонстрационные данные</span>
            ) : null}
          </div>
          <h1>Модель</h1>
          <p>
            Приложение использует один serving-показатель и показывает подтвержденные
            границы применения текущего пакета моделей.
          </p>
        </div>
        <span className={`${styles.statusTag} ${ready ? styles.statusSuccess : styles.statusActive}`}>
          {ready ? "Доступна для расчетов" : "Расчеты недоступны"}
        </span>
      </header>

      {refreshMessage ? <RefreshNotice message={refreshMessage} onRetry={onRefresh} /> : null}

      <section className={styles.modelHero} aria-labelledby="active-model-title">
        <div className={styles.modelHeroCopy}>
          <span className={styles.eyebrow}>Serving-контур</span>
          <h2 id="active-model-title">Дополнительный оборот</h2>
          <p>
            Рекомендация относится к распределению заданного бюджета и не является
            решением о запуске кампании.
          </p>
          <strong>
            Приложение использует модели оборота. Модели заказов и среднего чека
            сохранены для исследований, но не участвуют в расчете рекомендаций.
          </strong>
        </div>
        <dl className={styles.modelHeroFacts}>
          <div><dt>Основной показатель</dt><dd>Дополнительный оборот</dd></div>
          <div><dt>Serving-показателей</dt><dd>{formatInteger(serving.serving_targets_n)}</dd></div>
          <div><dt>Активных serving-моделей</dt><dd>{formatInteger(serving.active_serving_models_n)}</dd></div>
          <div><dt>Исследовательских моделей в пакете</dt><dd>{formatInteger(serving.research_models_in_package_n)}</dd></div>
        </dl>
      </section>

      <section className={styles.scopeSection} aria-labelledby="model-state-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Состояние пакета</span>
            <h2 id="model-state-title">Готовность и проверка</h2>
          </div>
          <span>Research / preprod</span>
        </div>
        <dl className={styles.modelStateGrid}>
          <div>
            <dt>Период обучения</dt>
            <dd>{periodLabel(overview.summary.training_period)}</dd>
            <small>Дневные данные</small>
          </div>
          <div>
            <dt>Статус пакета</dt>
            <dd>{packageStatusLabel(overview.summary.package_status)}</dd>
            <small>{activationStatusLabel(overview.summary.activation_status)}</small>
          </div>
          <div>
            <dt>Historical replay</dt>
            <dd><span className={`${styles.statusTag} ${evidenceClass(overview.summary.historical_replay.status)}`}>{evidenceLabel(overview.summary.historical_replay.status)}</span></dd>
            <small>{overview.summary.historical_replay.display_text}</small>
          </div>
          <div>
            <dt>Sealed OOT</dt>
            <dd><span className={`${styles.statusTag} ${evidenceClass(overview.summary.sealed_oot.status)}`}>{evidenceLabel(overview.summary.sealed_oot.status)}</span></dd>
            <small>{overview.summary.sealed_oot.display_text}</small>
          </div>
          <div>
            <dt>Период разработки</dt>
            <dd>{nullablePeriodLabel(passport.data.development_shadow_period)}</dd>
            <small>Не является подтвержденным sealed OOT</small>
          </div>
          <div>
            <dt>Production-статус</dt>
            <dd>Research / preprod</dd>
            <small>Production-утверждение не разрешено</small>
          </div>
        </dl>
      </section>

      <section className={styles.scopeSection} aria-labelledby="model-scope-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Покрытие</span>
            <h2 id="model-scope-title">Что доступно для расчета</h2>
          </div>
        </div>
        <dl className={styles.scopeStrip}>
          <div><dt>Показатель</dt><dd>1</dd><small>Дополнительный оборот</small></div>
          <div><dt>Сегменты</dt><dd>{formatInteger(passport.coverage.segments.length)}</dd><small>{passport.coverage.segments.join(", ")}</small></div>
          <div><dt>Каналы</dt><dd>{formatInteger(passport.coverage.channels.length)}</dd><small>{passport.coverage.channels.map((item) => item.channel_display_name).join(", ")}</small></div>
          <div><dt>Географии</dt><dd>{formatInteger(passport.coverage.geographies_n)}</dd><small>В опубликованном покрытии</small></div>
          <div><dt>Правила использования</dt><dd>{formatInteger(passport.coverage.capability_cells_n)}</dd><small>Сегмент × канал</small></div>
        </dl>
      </section>

      <section className={styles.capabilitySection} aria-labelledby="channel-policies-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Каналы</span>
            <h2 id="channel-policies-title">Правила применения модели</h2>
          </div>
          <span>{formatInteger(overview.channel_policies.length)}</span>
        </div>
        {overview.channel_policies.length === 0 ? (
          <div className={styles.inlineEmpty} role="status">
            <strong>Правила каналов пока недоступны</strong>
            <span>Расчет следует считать недоступным до публикации правил.</span>
          </div>
        ) : (
          <ul className={styles.policyList}>
            {overview.channel_policies.map((policy, index) => (
              <li key={`${policy.segment}-${policy.channel_id}`}>
                <span className={styles.listIndex}>{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <strong>{policy.channel_display_name}</strong>
                  <span>{policy.segment}</span>
                  <p>{policy.display_text}</p>
                </div>
                <span className={`${styles.statusTag} ${policyClass(policy.allowed_use)}`}>
                  {policyLabel(policy.allowed_use)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.limitationsSection} aria-labelledby="limitations-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Границы использования</span>
            <h2 id="limitations-title">Ограничения и caveats</h2>
          </div>
          <span>Показаны полностью</span>
        </div>
        {constraints.length === 0 ? (
          <div className={styles.inlineEmpty} role="status">
            <strong>Опубликованных ограничений нет</strong>
            <span>Это не означает production-готовность модели.</span>
          </div>
        ) : (
          <ul className={styles.limitationsList}>
            {constraints.map((item, index) => (
              <li key={`${item.kind}-${item.text}-${index}`}>
                <span className={`${styles.statusTag} ${item.kind === "Блокер публикации" ? styles.statusActive : styles.statusNeutral}`}>
                  {item.kind}
                </span>
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.text}</p>
                  {item.action ? <small>Что учитывать: {item.action}</small> : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
