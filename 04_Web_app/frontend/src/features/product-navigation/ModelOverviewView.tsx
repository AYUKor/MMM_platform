import { Link } from "react-router-dom";
import type { ModelOverviewV1 } from "../../shared/api/generated/model-overview-v1";
import { formatDate, formatInteger } from "../../shared/formatters/metrics";
import { RefreshNotice } from "./ProductNavigationPageState";
import styles from "./product-navigation.module.css";

interface ModelOverviewViewProps {
  overview: ModelOverviewV1;
  refreshMessage?: string | null;
  onRefresh: () => void;
}

function formatDateTime(value: string | null): string {
  if (value === null) return "Нет данных";
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.valueOf())) return "Нет данных";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function periodLabel(period: { start_date: string; end_date: string } | null): string {
  return period
    ? `${formatDate(period.start_date)} — ${formatDate(period.end_date)}`
    : "Нет данных";
}

function capabilityLabel(status: ModelOverviewV1["capabilities"][number]["status"]): string {
  if (status === "available") return "Доступно";
  if (status === "conditional") return "Зависит от кампании";
  return "Недоступно";
}

function capabilityClass(status: ModelOverviewV1["capabilities"][number]["status"]): string {
  if (status === "available") return styles.statusSuccess;
  if (status === "conditional") return styles.statusActive;
  return styles.statusNeutral;
}

export function ModelOverviewView({
  overview,
  refreshMessage = null,
  onRefresh,
}: ModelOverviewViewProps) {
  const active = overview.active_model;
  const scope = active.supported_scope;
  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <div className={styles.headerLabels}>
            <span className={styles.eyebrow}>Как устроен расчет</span>
            {overview.record_origin === "synthetic_fixture" ? (
              <span className={styles.demoBadge}>Демонстрационные данные</span>
            ) : null}
          </div>
          <h1>Модель</h1>
          <p>Назначение, возможности и ограничения текущей версии — без скрытых оценок и неподтвержденных показателей.</p>
        </div>
        <span className={`${styles.statusTag} ${active.status.code === "available" ? styles.statusSuccess : styles.statusNeutral}`}>
          {active.status.display_text}
        </span>
      </header>

      {refreshMessage ? <RefreshNotice message={refreshMessage} onRetry={onRefresh} /> : null}

      {active.status.code === "available" ? (
        <section className={styles.modelHero} aria-labelledby="active-model-title">
          <div className={styles.modelHeroCopy}>
            <span className={styles.eyebrow}>Активная версия</span>
            <h2 id="active-model-title">{active.display_name ?? "Модель MMM"}</h2>
            <p>{active.description}</p>
            <strong>{active.purpose}</strong>
          </div>
          <dl className={styles.modelHeroFacts}>
            <div><dt>Версия</dt><dd>{active.version ?? "Нет данных"}</dd></div>
            <div><dt>Фреймворк</dt><dd>{active.framework ?? "Нет данных"}</dd></div>
            <div><dt>Период обучения</dt><dd>{periodLabel(active.training_period)}</dd></div>
            <div><dt>Опубликована</dt><dd>{formatDateTime(active.published_at_utc)}</dd></div>
          </dl>
        </section>
      ) : (
        <section className={styles.unavailableHero} aria-labelledby="active-model-title">
          <span className={styles.eyebrow}>Активная версия</span>
          <h2 id="active-model-title">Сведения об активной модели пока недоступны</h2>
          <p>{active.description}</p>
        </section>
      )}

      {scope ? (
        <section className={styles.scopeSection} aria-labelledby="model-scope-title">
          <div className={styles.sectionHeading}>
            <div>
              <span className={styles.eyebrow}>Покрытие</span>
              <h2 id="model-scope-title">Что умеет текущая версия</h2>
            </div>
          </div>
          <dl className={styles.scopeStrip}>
            <div><dt>Сегменты</dt><dd>{formatInteger(scope.segments.length)}</dd><small>{scope.segments.join(", ")}</small></div>
            <div><dt>Каналы</dt><dd>{formatInteger(scope.channels.length)}</dd><small>{scope.channels.join(", ")}</small></div>
            <div><dt>Показатели</dt><dd>{formatInteger(scope.targets.length)}</dd><small>{scope.targets.join(", ")}</small></div>
            <div><dt>Географии</dt><dd>{formatInteger(scope.geographies_n)}</dd><small>В подтвержденном покрытии</small></div>
            <div><dt>Комбинации</dt><dd>{formatInteger(scope.capability_cells_n)}</dd><small>Сегмент × канал × показатель</small></div>
          </dl>
          <dl className={styles.usageStrip} aria-label="Режимы использования модели">
            <div><dt>Основное использование</dt><dd>{formatInteger(scope.allowed_use_counts.primary)}</dd></div>
            <div><dt>С осторожностью</dt><dd>{formatInteger(scope.allowed_use_counts.caution)}</dd></div>
            <div><dt>Только диагностика</dt><dd>{formatInteger(scope.allowed_use_counts.diagnostic)}</dd></div>
            <div><dt>Недоступно</dt><dd>{formatInteger(scope.allowed_use_counts.unavailable)}</dd></div>
          </dl>
        </section>
      ) : null}

      <section className={styles.capabilitySection} aria-labelledby="capabilities-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Возможности</span>
            <h2 id="capabilities-title">Что можно получить в расчете</h2>
          </div>
        </div>
        <ul className={styles.capabilityList}>
          {overview.capabilities.map((capability, index) => (
            <li key={capability.capability_id}>
              <span className={styles.listIndex}>{String(index + 1).padStart(2, "0")}</span>
              <div><strong>{capability.title}</strong><p>{capability.description}</p></div>
              <span className={`${styles.statusTag} ${capabilityClass(capability.status)}`}>
                {capabilityLabel(capability.status)}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <div className={styles.modelColumns}>
        <section className={styles.requirementsSection} aria-labelledby="requirements-title">
          <div className={styles.sectionHeading}>
            <div><span className={styles.eyebrow}>Входные данные</span><h2 id="requirements-title">Что подготовить</h2></div>
          </div>
          <ul className={styles.requirementsList}>
            {overview.data_requirements.map((requirement) => (
              <li key={requirement.requirement_id}>
                <div>
                  <strong>{requirement.title}</strong>
                  <span>{requirement.required ? "Обязательно" : "Если доступно"}</span>
                </div>
                <p>{requirement.description}</p>
                {requirement.accepted_values.length > 0 ? (
                  <small>{requirement.accepted_values.join(" · ")}</small>
                ) : null}
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.methodologySection} aria-labelledby="methodology-title">
          <div className={styles.sectionHeading}>
            <div><span className={styles.eyebrow}>Методология</span><h2 id="methodology-title">Как формируется результат</h2></div>
          </div>
          <ol className={styles.methodologyList}>
            {overview.methodology.map((method, index) => (
              <li key={method.method_id}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{method.title}</strong><p>{method.summary}</p></div>
              </li>
            ))}
          </ol>
        </section>
      </div>

      <section className={styles.limitationsSection} aria-labelledby="limitations-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Границы использования</span>
            <h2 id="limitations-title">Ограничения</h2>
          </div>
          <span>Показаны полностью</span>
        </div>
        <ul className={styles.limitationsList}>
          {overview.limitations.map((limitation) => (
            <li key={limitation.code}>
              <span className={`${styles.statusTag} ${limitation.status === "active" ? styles.statusActive : styles.statusNeutral}`}>
                {limitation.status === "active" ? "Действует" : "Недоступно"}
              </span>
              <div>
                <strong>{limitation.title}</strong>
                <p>{limitation.display_text}</p>
                <small>Что учитывать: {limitation.recommended_action}</small>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.versionsSection} aria-labelledby="versions-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Публикации</span>
            <h2 id="versions-title">История версий</h2>
          </div>
          <span>{formatInteger(overview.versions.length)}</span>
        </div>
        {overview.versions.length === 0 ? (
          <div className={styles.inlineEmpty} role="status">
            <strong>История версий пока недоступна</strong>
          </div>
        ) : (
          <ol className={styles.versionList}>
            {overview.versions.map((version, index) => (
              <li key={`${version.model_id}-${version.model_run_id}`}>
                <span className={styles.listIndex}>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>Публикация модели</strong><span>{formatDateTime(version.registered_at_utc)}</span></div>
                <span className={`${styles.statusTag} ${version.status === "active" ? styles.statusSuccess : styles.statusNeutral}`}>
                  {version.status === "active" ? "Активная" : "Зарегистрирована"}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      {overview.artifacts.length > 0 ? (
        <section className={styles.artifactsSection} aria-labelledby="artifacts-title">
          <div className={styles.sectionHeading}>
            <div><span className={styles.eyebrow}>Материалы</span><h2 id="artifacts-title">Опубликованные материалы</h2></div>
          </div>
          <ul className={styles.artifactList}>
            {overview.artifacts.map((artifact) => (
              <li key={artifact.artifact_id}>
                <div><strong>{artifact.title}</strong><span>{artifact.display_text}</span></div>
                {artifact.status === "available" && artifact.path ? (
                  <Link className={styles.textLink} to={artifact.path}>Открыть</Link>
                ) : <span>Нет данных</span>}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className={styles.updatedLine}>Сведения обновлены {formatDateTime(overview.updated_at_utc)}</p>
    </div>
  );
}
