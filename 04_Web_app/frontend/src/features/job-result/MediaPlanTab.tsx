import type { JobResultViewV2 } from "../../shared/api/generated/job-result-view-v2";
import type {
  ScenarioId,
  ScenarioMediaPlanV2,
} from "../../shared/api/generated/scenario-media-plan-v2";
import { formatInteger, formatPercent, formatRub, formatSignedRub } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import { UnavailableBlock } from "./ResultVisuals";
import { scenarioDisplayName } from "./jobResultFormatting";
import styles from "./job-result.module.css";

export interface MediaPlanControls {
  channel: string | null;
  geo: string | null;
  page: number;
  pageSize: number;
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "Не удалось получить медиаплан.";
}

function AggregateList({
  title,
  rows,
}: {
  title: string;
  rows: Array<{
    id: string;
    label: string;
    source: number;
    selected: number;
    delta: number;
    deltaPct: number | null;
    status: string;
  }>;
}) {
  return (
    <section className={styles.mediaAggregate} aria-label={title}>
      <div className={styles.sectionHeading}><h3>{title}</h3><span>{formatInteger(rows.length)} позиций</span></div>
      <div className={styles.aggregateList}>
        {rows.map((row) => (
          <article key={row.id}>
            <strong>{row.label}</strong>
            <dl>
              <div><dt>Исходный</dt><dd>{formatRub(row.source)}</dd></div>
              <div><dt>Выбранный</dt><dd>{formatRub(row.selected)}</dd></div>
              <div><dt>Изменение</dt><dd>{formatSignedRub(row.delta)} · {formatPercent(row.deltaPct === null ? null : row.deltaPct / 100)}</dd></div>
            </dl>
            <span>{row.status}</span>
          </article>
        ))}
      </div>
    </section>
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
  result: JobResultViewV2;
  plan: ScenarioMediaPlanV2 | undefined;
  selectedScenarioId: ScenarioId | null;
  controls: MediaPlanControls;
  loading: boolean;
  error: unknown;
  onScenarioChange: (scenarioId: ScenarioId) => void;
  onControlsChange: (controls: MediaPlanControls) => void;
  onPageChange: (page: number) => void;
  onRetry: () => void;
}) {
  const completedScenarios = result.scenarios.filter((scenario) => scenario.status === "completed");
  const infeasibleS6 = result.scenarios.find((scenario) => scenario.scenario_id === "S06" && scenario.status === "infeasible");

  return (
    <div className={styles.tabStack}>
      <section className={styles.mediaPlanIntro}>
        <div>
          <span className={styles.eyebrow}>Просмотр рассчитанного плана</span>
          <h2>Исходный план → просматриваемый сценарий</h2>
          <p>Переключатель меняет только просмотр уже рассчитанного медиаплана и не влияет на рекомендацию.</p>
        </div>
        <label className={styles.scenarioSelect}>
          <span>Сценарий</span>
          <select
            value={selectedScenarioId ?? ""}
            onChange={(event) => onScenarioChange(event.target.value as ScenarioId)}
            disabled={completedScenarios.length === 0}
          >
            {completedScenarios.map((scenario) => (
              <option key={scenario.scenario_id} value={scenario.scenario_id}>
                S{Number(scenario.scenario_id.slice(1))} · {scenarioDisplayName(scenario)}
              </option>
            ))}
          </select>
        </label>
      </section>

      {infeasibleS6 ? (
        <section className={styles.mediaUnavailableNotice} role="status">
          <StatusBadge tone="neutral">S6 недоступен</StatusBadge>
          <div><strong>Полный план максимального эффекта недоступен</strong><span>Пустая таблица не подменяет отсутствующий рассчитанный план.</span></div>
        </section>
      ) : null}

      <section className={styles.mediaFilters} aria-label="Фильтры медиаплана">
        <label>
          <span>Канал</span>
          <select
            value={controls.channel ?? ""}
            onChange={(event) => onControlsChange({ ...controls, channel: event.target.value || null, page: 1 })}
          >
            <option value="">Все каналы</option>
            {result.campaign.channels.map((channel) => (
              <option key={channel.channel_id} value={channel.channel_id}>{channel.channel_display_name}</option>
            ))}
          </select>
        </label>
        <label>
          <span>География</span>
          <select
            value={controls.geo ?? ""}
            onChange={(event) => onControlsChange({ ...controls, geo: event.target.value || null, page: 1 })}
          >
            <option value="">Все географии</option>
            {result.campaign.geographies.map((geo) => (
              <option key={geo.geo_id} value={geo.geo_display_name}>{geo.geo_display_name}</option>
            ))}
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
      </section>

      {loading && !plan ? (
        <section className={styles.inlineLoading} aria-live="polite" aria-busy="true"><span /><p>Получаем медиаплан…</p></section>
      ) : null}
      {error && !plan ? (
        <section className={styles.mediaError} role="alert"><h3>Медиаплан недоступен</h3><p>{errorMessage(error)}</p><Button onClick={onRetry}>Повторить</Button></section>
      ) : null}

      {plan ? (
        <>
          {loading || error ? (
            <div className={styles.refreshNotice} role="status">
              <span>{error ? "Не удалось обновить медиаплан. Последний безопасный снимок сохранен." : "Обновляем медиаплан…"}</span>
              {error ? <Button onClick={onRetry}>Повторить</Button> : null}
            </div>
          ) : null}
          <section className={styles.mediaSummary} aria-labelledby="media-summary-title">
            <div className={styles.sectionHeading}>
              <div><span className={styles.eyebrow}>Сверка бюджета</span><h2 id="media-summary-title">План согласован с результатом</h2></div>
              <StatusBadge tone={plan.totals.unallocated_budget_rub > 0 ? "warning" : "accent"}>
                {plan.totals.unallocated_budget_rub > 0 ? "Частичное распределение" : "Весь бюджет распределен"}
              </StatusBadge>
            </div>
            <dl className={styles.budgetSummary}>
              <div><dt>Запрошено</dt><dd>{formatRub(plan.totals.requested_budget_rub)}</dd></div>
              <div><dt>Исходный план</dt><dd>{formatRub(plan.totals.source_budget_rub)}</dd></div>
              <div><dt>Распределено</dt><dd>{formatRub(plan.totals.selected_budget_rub)}</dd></div>
              <div className={plan.totals.unallocated_budget_rub > 0 ? styles.budgetWarning : ""}><dt>Не распределено</dt><dd>{formatRub(plan.totals.unallocated_budget_rub)}</dd></div>
            </dl>
          </section>

          <div className={styles.mediaAggregateGrid}>
            <AggregateList
              title="Бюджет по каналам"
              rows={plan.aggregates.by_channel.map((row) => ({
                id: row.channel_id,
                label: row.channel_display_name,
                source: row.source_budget_rub,
                selected: row.selected_budget_rub,
                delta: row.delta_rub,
                deltaPct: row.delta_pct,
                status: row.quality_display_text,
              }))}
            />
            <AggregateList
              title="Бюджет по географиям"
              rows={plan.aggregates.by_geo.map((row) => ({
                id: row.geo_id,
                label: row.geo_display_name,
                source: row.source_budget_rub,
                selected: row.selected_budget_rub,
                delta: row.delta_rub,
                deltaPct: row.delta_pct,
                status: row.quality_display_text,
              }))}
            />
          </div>

          {plan.pagination.total_rows === 0 ? (
            <section className={styles.mediaUnavailableNotice} role="status">
              <StatusBadge tone="neutral">Нет данных</StatusBadge>
              <div><strong>По выбранным фильтрам строк нет</strong><span>Измените канал или географию, чтобы увидеть рассчитанный медиаплан.</span></div>
            </section>
          ) : (
          <section className={styles.mediaTableSection} aria-labelledby="media-table-title">
            <div className={styles.sectionHeading}>
              <div><span className={styles.eyebrow}>География × канал</span><h2 id="media-table-title">Детальный медиаплан</h2></div>
              <span>{formatInteger(plan.pagination.total_rows)} строк · {formatInteger(result.campaign.geographies_n)} географий</span>
            </div>
            <div className={styles.tableScroll} tabIndex={0} aria-label="Таблица медиаплана">
              <table>
                <thead><tr><th scope="col">Сегмент</th><th scope="col">География</th><th scope="col">Канал</th><th scope="col">Исходный бюджет</th><th scope="col">Просматриваемый бюджет</th><th scope="col">Изменение</th><th scope="col">Надежность</th></tr></thead>
                <tbody>
                  {plan.rows.map((row, index) => (
                    <tr key={`${row.geo_id}-${row.channel_id}-${index}`}>
                      <td>{row.segment}</td>
                      <th scope="row">{row.geo_display_name}</th>
                      <td>{row.channel_display_name}</td>
                      <td>{formatRub(row.source_budget_rub)}</td>
                      <td>{formatRub(row.selected_budget_rub)}</td>
                      <td>{formatSignedRub(row.delta_rub)}</td>
                      <td>{row.quality_display_text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={styles.pagination}>
              <Button disabled={plan.pagination.page <= 1} onClick={() => onPageChange(plan.pagination.page - 1)}>Назад</Button>
              <span>Страница {formatInteger(plan.pagination.page)} из {formatInteger(plan.pagination.total_pages)}</span>
              <Button disabled={plan.pagination.page >= plan.pagination.total_pages} onClick={() => onPageChange(plan.pagination.page + 1)}>Далее</Button>
            </div>
          </section>
          )}

          <UnavailableBlock title="Карта географий" description="Карта будет доступна после подключения утвержденного справочника координат." />
        </>
      ) : null}
    </div>
  );
}
