import type { JobResultViewV1, ScenarioId } from "../../shared/api/generated/job-result-view-v1";
import type { ScenarioMediaPlanV1 } from "../../shared/api/generated/scenario-media-plan-v1";
import {
  MediaPlanQueryUnsupportedError,
  MediaPlanUnavailableError,
  JobResultNotReadyError,
  UnsupportedScenarioMediaPlanContractError,
} from "../../shared/api/job-result-client";
import { formatInteger, formatPercent, formatRub, formatSignedRub } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import {
  qualityLabel,
  qualityTone,
  formatDeltaPercent,
  scenarioAnchorLabel,
  scenarioDisplayName,
  scenarioNumber,
} from "./jobResultFormatting";
import { BudgetComparisonChart, UnavailableBlock } from "./ResultVisuals";
import styles from "./job-result.module.css";

export interface MediaPlanControls {
  channel: string | null;
  geo: string | null;
  page: number;
  pageSize: number;
}

function MediaPlanErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const unsupportedQuery = error instanceof MediaPlanQueryUnsupportedError;
  const unsupportedContract = error instanceof UnsupportedScenarioMediaPlanContractError;
  const unavailable = error instanceof MediaPlanUnavailableError;
  const notReady = error instanceof JobResultNotReadyError;
  return (
    <section className={styles.inlineState} role="alert">
      <span className={styles.eyebrow}>Медиаплан</span>
      <h3>
        {unsupportedQuery
          ? "Такие параметры пока не поддерживаются"
          : unsupportedContract
            ? "Формат медиаплана не поддерживается"
            : notReady
              ? "Медиаплан еще не готов"
            : unavailable
              ? "Медиаплан временно недоступен"
              : "Не удалось получить медиаплан"}
      </h3>
      <p>
        {unsupportedQuery
          ? "Сбросьте фильтры или выберите другой рассчитанный сценарий."
          : unsupportedContract
            ? "Данные не прошли безопасную проверку и поэтому не показаны."
            : notReady
              ? "Расчет или публикация результата еще продолжаются. Повторите запрос позже."
            : "Проверьте соединение и повторите запрос."}
      </p>
      <Button onClick={onRetry}>{unsupportedQuery ? "Сбросить фильтры" : "Повторить"}</Button>
    </section>
  );
}

function Pagination({
  plan,
  onPageChange,
}: {
  plan: ScenarioMediaPlanV1;
  onPageChange: (page: number) => void;
}) {
  if (plan.pagination.total_pages <= 1) return null;
  return (
    <nav className={styles.pagination} aria-label="Страницы медиаплана">
      <Button
        disabled={plan.pagination.page <= 1}
        onClick={() => onPageChange(plan.pagination.page - 1)}
      >
        Назад
      </Button>
      <span>
        Страница {formatInteger(plan.pagination.page)} из {formatInteger(plan.pagination.total_pages)}
      </span>
      <Button
        disabled={plan.pagination.page >= plan.pagination.total_pages}
        onClick={() => onPageChange(plan.pagination.page + 1)}
      >
        Далее
      </Button>
    </nav>
  );
}

export function MediaPlanTab({
  result,
  plan,
  selectedScenarioId,
  controls,
  loading,
  error,
  onScenarioChange,
  onControlsChange,
  onPageChange,
  onRetry,
}: {
  result: JobResultViewV1;
  plan: ScenarioMediaPlanV1 | undefined;
  selectedScenarioId: ScenarioId | null;
  controls: MediaPlanControls;
  loading: boolean;
  error: unknown;
  onScenarioChange: (scenarioId: ScenarioId) => void;
  onControlsChange: (next: MediaPlanControls) => void;
  onPageChange: (page: number) => void;
  onRetry: () => void;
}) {
  const selectedScenario = selectedScenarioId === null
    ? null
    : result.scenarios.find((scenario) => scenario.scenario_id === selectedScenarioId) ?? null;
  const isCanonicalRecommendation =
    result.recommendation.status === "recommended" &&
    result.recommendation.scenario_id === plan?.scenario.scenario_id;
  const selectedBudgetLabel = isCanonicalRecommendation ? "Рекомендуется" : "Открытый сценарий";
  const channels = plan?.aggregates.by_channel.map((row) => row.channel) ?? [];
  const geographies = plan?.aggregates.by_geo.map((row) => row.geo) ?? [];

  return (
    <div className={styles.tabStack}>
      <section className={styles.mediaPlanIntro} aria-labelledby="media-plan-title">
        <div>
          <span className={styles.eyebrow}>Рассчитанные варианты</span>
          <h2 id="media-plan-title">
            {isCanonicalRecommendation
              ? "Медиаплан было → рекомендуется"
              : "Медиаплан было → открытый сценарий"}
          </h2>
          <p>
            Переключатель меняет только просмотр уже рассчитанного плана. Рекомендация системы,
            ранги и выводы расчета при этом не меняются.
          </p>
        </div>
        {selectedScenario ? (
          <div className={styles.viewOnlyNotice}>
            <span>Сейчас открыт</span>
            <strong>S{scenarioNumber(selectedScenario.scenario_id)} · {scenarioDisplayName(selectedScenario)}</strong>
            {scenarioAnchorLabel(selectedScenario.scenario_id) ? (
              <StatusBadge tone="neutral">{scenarioAnchorLabel(selectedScenario.scenario_id)}</StatusBadge>
            ) : null}
          </div>
        ) : null}
      </section>

      <fieldset className={styles.scenarioPicker}>
        <legend>Сценарий для просмотра</legend>
        {result.media_plan.scenario_options.map((option) => {
          const scenario = result.scenarios.find((item) => item.scenario_id === option.scenario_id);
          const available = option.status === "completed";
          return (
            <label key={option.scenario_id} className={selectedScenarioId === option.scenario_id ? styles.scenarioChoiceActive : styles.scenarioChoice}>
              <input
                type="radio"
                name="media-plan-scenario"
                value={option.scenario_id}
                checked={selectedScenarioId === option.scenario_id}
                disabled={!available}
                onChange={() => onScenarioChange(option.scenario_id)}
              />
              <span>S{scenarioNumber(option.scenario_id)}</span>
              <strong>{scenario ? scenarioDisplayName(scenario) : option.title}</strong>
              <small>{available ? "Рассчитан" : option.status === "failed" ? "Расчет завершился с ошибкой" : "Нет данных"}</small>
            </label>
          );
        })}
      </fieldset>

      {selectedScenarioId === null ? (
        <UnavailableBlock
          title="Медиаплан недоступен"
          description="Нет ни одного завершенного сценария, который можно безопасно показать."
        />
      ) : null}

      {selectedScenarioId !== null && loading && !plan ? (
        <div className={styles.inlineLoading} aria-live="polite" aria-busy="true">
          <span aria-hidden="true" />
          <p>Получаем рассчитанный медиаплан…</p>
        </div>
      ) : null}

      {selectedScenarioId !== null && error && !plan ? (
        <MediaPlanErrorState error={error} onRetry={onRetry} />
      ) : null}

      {plan ? (
        <>
          {error ? (
            <div className={styles.refreshNotice} role="status">
              <span>Не удалось обновить медиаплан. Последние полученные данные сохранены.</span>
              <Button onClick={onRetry}>Повторить</Button>
            </div>
          ) : null}

          <section className={styles.mediaSummary} aria-label="Итоги медиаплана">
            <dl>
              <div><dt>Запрошенный бюджет</dt><dd>{formatRub(plan.totals.requested_budget_rub)}</dd></div>
              <div><dt>Исходный бюджет</dt><dd>{formatRub(plan.totals.source_budget_rub)}</dd></div>
              <div><dt>Выбранный план</dt><dd>{formatRub(plan.totals.selected_budget_rub)}</dd></div>
              <div><dt>Изменение</dt><dd>{formatSignedRub(plan.totals.delta_rub)}</dd></div>
              <div className={plan.totals.unallocated_budget_rub > 0 ? styles.budgetWarning : ""}>
                <dt>Не распределено</dt><dd>{formatRub(plan.totals.unallocated_budget_rub)}</dd>
              </div>
            </dl>
            <div>
              <StatusBadge tone={qualityTone(plan.scenario.quality_status)}>
                {qualityLabel(plan.scenario.quality_status)}
              </StatusBadge>
              {isCanonicalRecommendation ? (
                <StatusBadge tone="accent">Каноническая рекомендация</StatusBadge>
              ) : (
                <StatusBadge tone="neutral">Только просмотр</StatusBadge>
              )}
            </div>
          </section>

          <section className={styles.budgetChartsSection} aria-labelledby="media-budget-changes-title">
            <div className={styles.sectionHeading}>
              <div>
                <span className={styles.eyebrow}>Было → {selectedBudgetLabel.toLowerCase()}</span>
                <h3 id="media-budget-changes-title">Изменение бюджета по каналам и географиям</h3>
              </div>
              <span>Готовые сводки сервиса</span>
            </div>
            <div className={styles.budgetChartsGrid}>
              <BudgetComparisonChart
                title="По каналам"
                rows={[...plan.aggregates.by_channel]}
                dimension="channel"
              />
              <BudgetComparisonChart
                title="По географиям"
                rows={[...plan.aggregates.by_geo]}
                dimension="geo"
                limit={10}
              />
            </div>
            <div className={styles.geoChannelSummary}>
              <strong>География × канал</strong>
              <span>{formatInteger(plan.aggregates.by_geo_channel.length)} рассчитанных связок</span>
              <p>{plan.aggregates.geo_channel_matrix.display_text}</p>
            </div>
          </section>

          <section className={styles.mediaFilters} aria-labelledby="media-filter-title">
            <div>
              <span className={styles.eyebrow}>Детализация</span>
              <h3 id="media-filter-title">Фильтры таблицы</h3>
            </div>
            <label>
              <span>Канал</span>
              <select
                value={controls.channel ?? ""}
                onChange={(event) => onControlsChange({ ...controls, channel: event.target.value || null, page: 1 })}
              >
                <option value="">Все каналы</option>
                {channels.map((channel) => <option key={channel} value={channel}>{channel}</option>)}
              </select>
            </label>
            <label>
              <span>География</span>
              <select
                value={controls.geo ?? ""}
                onChange={(event) => onControlsChange({ ...controls, geo: event.target.value || null, page: 1 })}
              >
                <option value="">Все географии</option>
                {geographies.map((geo) => <option key={geo} value={geo}>{geo}</option>)}
              </select>
            </label>
            <label>
              <span>Строк на странице</span>
              <select
                value={controls.pageSize}
                onChange={(event) => onControlsChange({ ...controls, pageSize: Number(event.target.value), page: 1 })}
              >
                {[10, 25, 50, 100].map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <Button onClick={() => onControlsChange({ channel: null, geo: null, page: 1, pageSize: controls.pageSize })}>
              Сбросить
            </Button>
          </section>

          <section className={styles.mediaTableSection} aria-labelledby="media-table-title">
            <div className={styles.sectionHeading}>
              <div>
                <span className={styles.eyebrow}>География × канал</span>
                <h3 id="media-table-title">Строки рассчитанного плана</h3>
              </div>
              <span>{formatInteger(plan.pagination.total_rows)} строк</span>
            </div>
            {plan.rows.length === 0 ? (
              <div className={styles.tableEmpty} role="status">
                <strong>По выбранным фильтрам строк нет</strong>
                <span>Это корректный пустой результат. Сбросьте фильтры, чтобы увидеть весь план.</span>
              </div>
            ) : (
              <div className={styles.tableScroll} tabIndex={0} role="region" aria-label="Таблица медиаплана, прокручивается по горизонтали">
                <table className={styles.mediaTable}>
                  <thead>
                    <tr>
                      <th>Сегмент</th>
                      <th>География</th>
                      <th>Канал</th>
                      <th className={styles.numericCell}>Было</th>
                      <th className={styles.numericCell}>{selectedBudgetLabel}</th>
                      <th className={styles.numericCell}>Изменение, ₽</th>
                      <th className={styles.numericCell}>Изменение, %</th>
                      <th className={styles.numericCell}>Доля выбранного</th>
                      <th>Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.rows.map((row) => (
                      <tr key={`${row.segment}:${row.geo}:${row.channel}`}>
                        <td>{row.segment}</td>
                        <td>{row.geo}</td>
                        <td>{row.channel}</td>
                        <td className={styles.numericCell}>{formatRub(row.source_budget_rub)}</td>
                        <td className={styles.numericCell}>{formatRub(row.selected_budget_rub)}</td>
                        <td className={`${styles.numericCell} ${row.delta_rub >= 0 ? styles.positiveDelta : styles.negativeDelta}`}>
                          {formatSignedRub(row.delta_rub)}
                        </td>
                        <td className={`${styles.numericCell} ${row.delta_pct === null ? "" : row.delta_pct < 0 ? styles.negativeDelta : styles.positiveDelta}`}>
                          {formatDeltaPercent(row.delta_pct)}
                        </td>
                        <td className={styles.numericCell}>{formatPercent(row.selected_budget_share)}</td>
                        <td><StatusBadge tone={qualityTone(row.quality_status)}>{qualityLabel(row.quality_status)}</StatusBadge></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Pagination plan={plan} onPageChange={onPageChange} />
          </section>

          <section className={styles.filteredSummary} aria-label="Итоги выбранных фильтров">
            <strong>В выбранном срезе</strong>
            <span>Было {formatRub(plan.filtered_totals.source_budget_rub)}</span>
            <span>{selectedBudgetLabel} {formatRub(plan.filtered_totals.selected_budget_rub)}</span>
            <span>Изменение {formatSignedRub(plan.filtered_totals.delta_rub)}</span>
          </section>

          <div className={styles.unavailableGrid}>
            <UnavailableBlock title="Карта" description={plan.map.display_text} />
            <UnavailableBlock title="Календарь активности" description={plan.aggregates.channel_date_matrix.display_text} />
            <UnavailableBlock title="План по дням" description={plan.aggregates.by_date.display_text} />
            <UnavailableBlock title="Рабочий Excel-медиаплан" description={plan.working_media_plan.display_text} />
          </div>

          <section className={styles.limitations} aria-labelledby="media-limitations-title">
            <h3 id="media-limitations-title">Ограничения представления</h3>
            <ul>{plan.limitations.map((limitation) => <li key={limitation.code}>{limitation.display_text}</li>)}</ul>
          </section>
        </>
      ) : null}
    </div>
  );
}
