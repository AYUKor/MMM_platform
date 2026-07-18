import { Link } from "react-router-dom";
import type { GeoCatalogV1 } from "../../shared/api/generated/geo-catalog-v1";
import type { WorkspaceGeoBudgetV1 } from "../../shared/api/generated/workspace-geo-budget-v1";
import type { WorkspaceHomeV1 } from "../../shared/api/generated/workspace-home-v1";
import { formatDate, formatInteger, formatRub } from "../../shared/formatters/metrics";
import { containsLegacyTargetClaim } from "../../shared/presentation/turnover-only";
import { RefreshNotice } from "./ProductNavigationPageState";
import styles from "./product-navigation.module.css";

interface HomeViewProps {
  home: WorkspaceHomeV1;
  geoBudget: WorkspaceGeoBudgetV1 | null;
  geoCatalog: GeoCatalogV1 | null;
  geoLoading?: boolean;
  geoUnavailable?: boolean;
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

function statusClass(status: string): string {
  if (status === "succeeded") return styles.statusSuccess;
  if (["failed", "timed_out"].includes(status)) return styles.statusDanger;
  if (["queued", "running", "cancel_requested"].includes(status)) return styles.statusActive;
  return styles.statusNeutral;
}

export function HomeView({
  home,
  geoBudget,
  geoCatalog,
  geoLoading = false,
  geoUnavailable = false,
  refreshMessage = null,
  onRefresh,
}: HomeViewProps) {
  const newCalculation = home.quick_actions.find((item) => item.action_id === "new_calculation");
  const history = home.quick_actions.find((item) => item.action_id === "calculation_history");
  const modelDisplayName = home.model.display_name
    && !containsLegacyTargetClaim(home.model.display_name)
    ? home.model.display_name
    : "Модель дополнительного оборота";
  return (
    <div className={styles.page}>
      <header className={styles.homeHero}>
        <div className={styles.heroCopy}>
          <div className={styles.headerLabels}>
            <span className={styles.eyebrow}>Рабочее пространство MMM</span>
            {home.record_origin === "synthetic_fixture" ? (
              <span className={styles.demoBadge}>Демонстрационные данные</span>
            ) : null}
          </div>
          <h1>Планируйте бюджет и проверяйте результат в одном месте</h1>
          <p>Создайте расчет, следите за его ходом и возвращайтесь к опубликованным результатам.</p>
          <div className={styles.heroActions}>
            {newCalculation ? (
              <Link className={styles.primaryLink} to={newCalculation.path}>
                {newCalculation.title}
              </Link>
            ) : null}
            {history ? (
              <Link className={styles.secondaryLink} to={history.path}>
                {history.title}
              </Link>
            ) : null}
          </div>
        </div>
        <div className={styles.heroContour} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </header>

      {refreshMessage ? <RefreshNotice message={refreshMessage} onRetry={onRefresh} /> : null}

      <section className={styles.summarySection} aria-labelledby="home-summary-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Состояние расчетов</span>
            <h2 id="home-summary-title">Что происходит сейчас</h2>
          </div>
          <span>Обновлено {formatDateTime(home.updated_at_utc)}</span>
        </div>
        <dl className={styles.summaryStrip}>
          <div><dt>Выполняются</dt><dd>{formatInteger(home.summary.running)}</dd></div>
          <div><dt>В очереди</dt><dd>{formatInteger(home.summary.queued)}</dd></div>
          <div><dt>Завершены за 30 дней</dt><dd>{formatInteger(home.summary.completed_30d)}</dd></div>
          <div><dt>Ошибки за 30 дней</dt><dd>{formatInteger(home.summary.failed_30d)}</dd></div>
        </dl>
      </section>

      <section className={styles.geoBudgetSection} aria-labelledby="geo-budget-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>География бюджета</span>
            <h2 id="geo-budget-title">Бюджет проверенных кампаний по географиям</h2>
          </div>
          <span>Сводка формируется сервисом</span>
        </div>
        {geoBudget ? (
          <dl className={styles.geoBudgetSummary}>
            <div><dt>Бюджет в проверенных кампаниях</dt><dd>{formatRub(geoBudget.total_budget_rub)}</dd></div>
            <div><dt>Кампании</dt><dd>{formatInteger(geoBudget.campaigns_n)}</dd></div>
            <div><dt>Географии</dt><dd>{formatInteger(geoBudget.geographies_n)}</dd></div>
          </dl>
        ) : null}
        <div className={styles.geoUnavailable} role="status" aria-live="polite">
          <div className={styles.geoUnavailableMark} aria-hidden="true"><span /><span /></div>
          <div>
            <strong>Карта пока недоступна</strong>
            <p>Карта будет доступна после подключения утвержденного справочника координат.</p>
            <small>
              {geoLoading
                ? "Проверяем готовность справочника."
                : geoUnavailable
                  ? "Не удалось получить сведения о готовности карты."
                  : geoCatalog?.display_text ?? geoBudget?.display_text ?? "Координаты пока не опубликованы."}
            </small>
          </div>
        </div>
      </section>

      <div className={styles.homeGrid}>
        <section className={styles.listSection} aria-labelledby="active-calculations-title">
          <div className={styles.sectionHeading}>
            <div>
              <span className={styles.eyebrow}>В работе</span>
              <h2 id="active-calculations-title">Активные расчеты</h2>
            </div>
          </div>
          {home.active_calculations.length === 0 ? (
            <div className={styles.inlineEmpty} role="status">
              <strong>Активных расчетов нет</strong>
              <span>Новый расчет можно запустить из верхней части страницы.</span>
            </div>
          ) : (
            <ul className={styles.calculationList}>
              {home.active_calculations.map((item) => (
                <li key={item.job_id}>
                  <div className={styles.rowMain}>
                    <span className={`${styles.statusTag} ${statusClass(item.status.code)}`}>
                      {item.status.display_text}
                    </span>
                    <strong>{item.campaign_name}</strong>
                    <span>{item.current_stage?.title ?? item.display_text}</span>
                    {item.current_stage ? <small>{item.current_stage.display_text}</small> : null}
                  </div>
                  <div className={styles.rowAside}>
                    <time dateTime={item.created_at_utc}>{formatDateTime(item.created_at_utc)}</time>
                    <Link className={styles.textLink} to={item.progress_path}>Открыть ход расчета</Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className={styles.modelSummary} aria-labelledby="home-model-title">
          <div className={styles.headerLabels}>
            <span className={styles.eyebrow}>Активная модель</span>
            <span className={`${styles.statusTag} ${home.model.status.code === "available" ? styles.statusSuccess : styles.statusNeutral}`}>
              {home.model.status.display_text}
            </span>
          </div>
          {home.model.status.code === "available" ? (
            <>
              <h2 id="home-model-title">{modelDisplayName}</h2>
              <p>Рекомендации рассчитываются только по дополнительному обороту.</p>
              <dl className={styles.modelFacts}>
                <div><dt>Основной показатель</dt><dd>Дополнительный оборот</dd></div>
                <div><dt>Период обучения</dt><dd>{periodLabel(home.model.training_period)}</dd></div>
                <div><dt>Географий</dt><dd>{formatInteger(home.model.supported_scope?.geographies_n ?? null)}</dd></div>
                <div><dt>Режим</dt><dd>Research / preprod</dd></div>
              </dl>
            </>
          ) : (
            <>
              <h2 id="home-model-title">Сведения об активной модели пока недоступны</h2>
              <p>Сведения о serving-модели дополнительного оборота пока не опубликованы.</p>
            </>
          )}
          <Link className={styles.textLink} to={home.model.details_path}>Подробнее о модели</Link>
        </section>
      </div>

      <section className={styles.listSection} aria-labelledby="recent-calculations-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Последние изменения</span>
            <h2 id="recent-calculations-title">Последние расчеты</h2>
          </div>
          <Link className={styles.textLink} to="/calculations">Вся история</Link>
        </div>
        {home.recent_calculations.length === 0 ? (
          <div className={styles.inlineEmpty} role="status">
            <strong>Завершенных расчетов пока нет</strong>
            <span>Здесь появятся последние опубликованные результаты.</span>
          </div>
        ) : (
          <ul className={styles.recentList}>
            {home.recent_calculations.map((item) => {
              const destination = item.result_path ?? item.progress_path;
              return (
                <li key={item.job_id}>
                  <div className={styles.rowMain}>
                    <strong>{item.campaign_name}</strong>
                    <span>{periodLabel(item.campaign_period)}</span>
                  </div>
                  <dl className={styles.compactFacts}>
                    <div><dt>Бюджет</dt><dd>{formatRub(item.total_budget_rub)}</dd></div>
                    <div><dt>Завершен</dt><dd>{formatDateTime(item.completed_at_utc)}</dd></div>
                    <div><dt>Результат</dt><dd>{item.result_available ? "Доступен" : "Не готов"}</dd></div>
                    <div><dt>Отчет</dt><dd>{item.report_available ? "Готов" : "Не готов"}</dd></div>
                    <div><dt>Замечания</dt><dd>{formatInteger(item.warnings_count)}</dd></div>
                  </dl>
                  <div className={styles.rowAside}>
                    <span className={`${styles.statusTag} ${statusClass(item.status.code)}`}>
                      {item.status.display_text}
                    </span>
                    <Link className={styles.textLink} to={destination}>
                      {item.result_available ? "Открыть результат" : "Открыть расчет"}
                    </Link>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {home.warnings.length > 0 ? (
        <section className={styles.warningSection} aria-labelledby="home-warnings-title">
          <div className={styles.sectionHeading}>
            <div>
              <span className={styles.eyebrow}>Требует внимания</span>
              <h2 id="home-warnings-title">Что стоит проверить</h2>
            </div>
          </div>
          <ul className={styles.warningList}>
            {home.warnings.map((warning) => (
              <li key={warning.code} className={styles[`warning-${warning.severity}`]}>
                <div>
                  <strong>{warning.title}</strong>
                  <p>{warning.display_text}</p>
                  <span>Что можно сделать: {warning.recommended_action}</span>
                </div>
                {warning.path ? <Link className={styles.textLink} to={warning.path}>Открыть</Link> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className={styles.quickActions} aria-labelledby="quick-actions-title">
        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Следующий шаг</span>
            <h2 id="quick-actions-title">Быстрые переходы</h2>
          </div>
        </div>
        <div className={styles.actionGrid}>
          {home.quick_actions.map((action, index) => (
            <Link key={action.action_id} className={index === 0 ? styles.actionPrimary : styles.actionItem} to={action.path}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{action.title}</strong>
              <small>{action.description}</small>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
