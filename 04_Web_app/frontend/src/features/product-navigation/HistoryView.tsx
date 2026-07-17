import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type {
  CalculationHistoryV1,
  HistoryItem,
} from "../../shared/api/generated/calculation-history-v1";
import { formatDate, formatInteger, formatRub } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { RefreshNotice } from "./ProductNavigationPageState";
import {
  HISTORY_SORT_OPTIONS,
  HISTORY_STATUS_OPTIONS,
  hasHistoryFilters,
  historyEmptyCopy,
  type NormalizedHistoryQuery,
} from "./productNavigationModel";
import styles from "./product-navigation.module.css";

interface HistoryViewProps {
  history: CalculationHistoryV1;
  query: NormalizedHistoryQuery;
  refreshMessage?: string | null;
  onQueryChange: (query: NormalizedHistoryQuery) => void;
  onRefresh: () => void;
}

interface FilterDraft {
  search: string;
  createdFrom: string;
  createdTo: string;
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

function periodLabel(item: HistoryItem): string {
  return item.campaign_period
    ? `${formatDate(item.campaign_period.start_date)} — ${formatDate(item.campaign_period.end_date)}`
    : "Нет данных";
}

function joinedOrMissing(values: string[] | null): string {
  return values === null ? "Нет данных" : values.join(", ");
}

function statusClass(status: HistoryItem["status"]): string {
  if (status === "succeeded") return styles.statusSuccess;
  if (["failed", "timed_out"].includes(status)) return styles.statusDanger;
  if (["queued", "running", "cancel_requested"].includes(status)) return styles.statusActive;
  return styles.statusNeutral;
}

function directStatusCount(
  history: CalculationHistoryV1,
  status: string | null,
): number | null {
  if (status === null) return history.summary.all;
  if (status === "active") return history.summary.active;
  if (status === "succeeded") return history.summary.succeeded;
  if (status === "failed") return history.summary.failed;
  if (status === "cancelled") return history.summary.cancelled;
  if (status === "timed_out") return history.summary.timed_out;
  return null;
}

function HistoryActions({ item }: { item: HistoryItem }) {
  return (
    <div className={styles.historyActions}>
      {item.result_path ? (
        <Link className={styles.textLink} to={item.result_path}>Открыть результат</Link>
      ) : (
        <Link className={styles.textLink} to={item.progress_path}>Открыть расчет</Link>
      )}
    </div>
  );
}

function HistoryMobileCard({ item }: { item: HistoryItem }) {
  return (
    <article className={styles.historyCard}>
      <div className={styles.historyCardHeader}>
        <div>
          <strong>{item.campaign_name}</strong>
          <span>{periodLabel(item)}</span>
        </div>
        <span className={`${styles.statusTag} ${statusClass(item.status)}`}>
          {item.status_display_text}
        </span>
      </div>
      <dl className={styles.historyCardFacts}>
        <div><dt>Создан</dt><dd>{formatDateTime(item.created_at_utc)}</dd></div>
        <div><dt>Завершен</dt><dd>{formatDateTime(item.completed_at_utc)}</dd></div>
        <div><dt>Бюджет</dt><dd>{formatRub(item.total_budget_rub)}</dd></div>
        <div><dt>Сегменты</dt><dd>{joinedOrMissing(item.segments)}</dd></div>
        <div><dt>Каналы</dt><dd>{formatInteger(item.channels_n)}</dd></div>
        <div><dt>Географии</dt><dd>{formatInteger(item.geographies_n)}</dd></div>
        <div><dt>Замечания</dt><dd>{formatInteger(item.warnings_count)}</dd></div>
        <div><dt>Отчет</dt><dd>{item.report_available ? "Готов" : "Не готов"}</dd></div>
      </dl>
      <HistoryActions item={item} />
    </article>
  );
}

export function HistoryView({
  history,
  query,
  refreshMessage = null,
  onQueryChange,
  onRefresh,
}: HistoryViewProps) {
  const [draft, setDraft] = useState<FilterDraft>({
    search: query.search ?? "",
    createdFrom: query.createdFrom ?? "",
    createdTo: query.createdTo ?? "",
  });

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onQueryChange({
      ...query,
      search: draft.search.trim() || null,
      createdFrom: draft.createdFrom || null,
      createdTo: draft.createdTo || null,
      page: 1,
    });
  };
  const emptyCopy = historyEmptyCopy(history, query);

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <div className={styles.headerLabels}>
            <span className={styles.eyebrow}>Рабочее пространство</span>
            {history.record_origin === "synthetic_fixture" ? (
              <span className={styles.demoBadge}>Демонстрационные данные</span>
            ) : null}
          </div>
          <h1>История расчетов</h1>
          <p>Находите запуски по кампании, статусу и дате. Фильтры применяются ко всей сохраненной истории.</p>
        </div>
        <Link className={styles.primaryLink} to="/calculations/new">Новый расчет</Link>
      </header>

      {refreshMessage ? <RefreshNotice message={refreshMessage} onRetry={onRefresh} /> : null}

      <dl className={styles.historySummary} aria-label="Сводка по истории расчетов">
        <div><dt>Все</dt><dd>{formatInteger(history.summary.all)}</dd></div>
        <div><dt>В работе</dt><dd>{formatInteger(history.summary.active)}</dd></div>
        <div><dt>Завершены</dt><dd>{formatInteger(history.summary.succeeded)}</dd></div>
        <div><dt>С ошибкой</dt><dd>{formatInteger(history.summary.failed)}</dd></div>
        <div><dt>Отменены</dt><dd>{formatInteger(history.summary.cancelled)}</dd></div>
        <div><dt>Превышено время</dt><dd>{formatInteger(history.summary.timed_out)}</dd></div>
      </dl>

      <section className={styles.historyWorkspace} aria-labelledby="history-list-title">
        <div className={styles.statusFilters} aria-label="Фильтр по статусу">
          {HISTORY_STATUS_OPTIONS.map((option) => {
            const count = directStatusCount(history, option.value);
            const active = query.status === option.value;
            return (
              <button
                type="button"
                key={option.label}
                className={active ? styles.statusFilterActive : styles.statusFilter}
                aria-pressed={active}
                onClick={() => onQueryChange({ ...query, status: option.value, page: 1 })}
              >
                <span>{option.label}</span>
                {count !== null ? <strong>{formatInteger(count)}</strong> : null}
              </button>
            );
          })}
        </div>

        <form className={styles.historyFilters} onSubmit={applyFilters}>
          <label className={styles.searchField}>
            <span>Поиск</span>
            <input
              type="search"
              value={draft.search}
              maxLength={120}
              placeholder="Поиск по названию кампании"
              onChange={(event) => setDraft((current) => ({ ...current, search: event.target.value }))}
            />
          </label>
          <label>
            <span>Создан с</span>
            <input
              type="date"
              value={draft.createdFrom}
              onChange={(event) => setDraft((current) => ({ ...current, createdFrom: event.target.value }))}
            />
          </label>
          <label>
            <span>Создан по</span>
            <input
              type="date"
              value={draft.createdTo}
              onChange={(event) => setDraft((current) => ({ ...current, createdTo: event.target.value }))}
            />
          </label>
          <label>
            <span>Сортировка</span>
            <select
              value={query.sort}
              onChange={(event) => onQueryChange({
                ...query,
                sort: event.target.value as NormalizedHistoryQuery["sort"],
                page: 1,
              })}
            >
              {HISTORY_SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <div className={styles.filterActions}>
            <Button variant="primary" type="submit">Применить</Button>
            {hasHistoryFilters(query) ? (
              <Button
                type="button"
                onClick={() => onQueryChange({
                  ...query,
                  status: null,
                  search: null,
                  createdFrom: null,
                  createdTo: null,
                  page: 1,
                })}
              >
                Очистить
              </Button>
            ) : null}
          </div>
        </form>

        <div className={styles.sectionHeading}>
          <div>
            <span className={styles.eyebrow}>Запуски</span>
            <h2 id="history-list-title">Результаты</h2>
          </div>
          <span>{formatInteger(history.pagination.total_items)} записей</span>
        </div>

        {history.items.length === 0 ? (
          <div className={styles.largeEmpty} role="status">
            <strong>{emptyCopy.title}</strong>
            <p>{emptyCopy.description}</p>
            {hasHistoryFilters(query) ? (
              <Button
                onClick={() => onQueryChange({
                  ...query,
                  status: null,
                  search: null,
                  createdFrom: null,
                  createdTo: null,
                  page: 1,
                })}
              >
                Очистить фильтры
              </Button>
            ) : null}
          </div>
        ) : (
          <>
            <div className={styles.historyTableWrap}>
              <table className={styles.historyTable}>
                <thead>
                  <tr>
                    <th>Кампания</th>
                    <th>Статус</th>
                    <th>Создан</th>
                    <th>Завершен</th>
                    <th>Период</th>
                    <th>Бюджет</th>
                    <th>Сегменты</th>
                    <th>Каналы</th>
                    <th>Географии</th>
                    <th>Замечания</th>
                    <th>Результат</th>
                    <th>Отчет</th>
                    <th><span className="sr-only">Действия</span></th>
                  </tr>
                </thead>
                <tbody>
                  {history.items.map((item) => (
                    <tr key={item.job_id}>
                      <td><strong>{item.campaign_name}</strong></td>
                      <td><span className={`${styles.statusTag} ${statusClass(item.status)}`}>{item.status_display_text}</span></td>
                      <td>{formatDateTime(item.created_at_utc)}</td>
                      <td>{formatDateTime(item.completed_at_utc)}</td>
                      <td>{periodLabel(item)}</td>
                      <td>{formatRub(item.total_budget_rub)}</td>
                      <td>{joinedOrMissing(item.segments)}</td>
                      <td>{formatInteger(item.channels_n)}</td>
                      <td>{formatInteger(item.geographies_n)}</td>
                      <td>{formatInteger(item.warnings_count)}</td>
                      <td>{item.result_available ? "Доступен" : "Не готов"}</td>
                      <td>{item.report_available ? "Готов" : "Не готов"}</td>
                      <td><HistoryActions item={item} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={styles.historyCards}>
              {history.items.map((item) => <HistoryMobileCard key={item.job_id} item={item} />)}
            </div>
          </>
        )}

        <nav className={styles.pagination} aria-label="Страницы истории">
          <Button
            disabled={history.pagination.page <= 1}
            onClick={() => onQueryChange({ ...query, page: history.pagination.page - 1 })}
          >
            Назад
          </Button>
          <span>
            {history.pagination.total_pages === 0
              ? "Нет страниц"
              : `Страница ${formatInteger(history.pagination.page)} из ${formatInteger(history.pagination.total_pages)}`}
          </span>
          <label>
            <span>Записей на странице</span>
            <select
              value={query.pageSize}
              onChange={(event) => onQueryChange({
                ...query,
                pageSize: Number(event.target.value),
                page: 1,
              })}
            >
              {[10, 25, 50, 100].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <Button
            disabled={history.pagination.total_pages === 0 || history.pagination.page >= history.pagination.total_pages}
            onClick={() => onQueryChange({ ...query, page: history.pagination.page + 1 })}
          >
            Далее
          </Button>
        </nav>
      </section>
    </div>
  );
}
