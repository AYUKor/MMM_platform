import { useMemo, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { getAdminAudit } from "../../shared/api/auth-admin-client";
import { Button } from "../../shared/ui/Button";
import {
  AUDIT_EVENT_TYPES,
  AUDIT_SORTS,
  EVENT_LABELS,
  RESULT_LABELS,
  auditUrlParams,
  formatAdminDate,
  fromDateTimeLocal,
  readAuditUrlState,
  toDateTimeLocal,
  type AdminAuditUrlState,
} from "./adminModel";
import { AdminError, AdminLoading, AdminPage, EmptyAdminState } from "./AdminPageState";
import styles from "./admin.module.css";

const TARGET_LABELS: Record<string, string> = {
  user: "Учетная запись",
  session: "Сессия",
  administration: "Администрирование",
};

export function AdminAuditView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = readAuditUrlState(searchParams);
  const [fromDraft, setFromDraft] = useState(toDateTimeLocal(state.occurredFromUtc));
  const [toDraft, setToDraft] = useState(toDateTimeLocal(state.occurredToUtc));
  const query = useQuery({
    queryKey: ["phase-e", "admin-audit", state],
    queryFn: ({ signal }) => getAdminAudit(state, signal),
    refetchOnWindowFocus: false,
  });
  const actorOptions = useMemo(() => {
    const options = new Map<string, string>();
    for (const item of query.isError ? [] : query.data?.items ?? []) {
      if (item.actor_user_id && item.actor_display_name) options.set(item.actor_user_id, item.actor_display_name);
    }
    if (state.actorUserId && !options.has(state.actorUserId)) options.set(state.actorUserId, "Выбранный участник");
    return [...options.entries()];
  }, [query.data?.items, query.isError, state.actorUserId]);
  function update(patch: Partial<AdminAuditUrlState>) {
    setSearchParams(auditUrlParams({ ...state, ...patch }), { replace: true });
  }
  const rows = query.data?.items ?? [];
  return (
    <AdminPage eyebrow="Администрирование" title="Журнал действий" description="Безопасная история входов и административных изменений.">
      <form className={styles.auditFilters} onSubmit={(event: FormEvent) => {
        event.preventDefault();
        update({ occurredFromUtc: fromDateTimeLocal(fromDraft), occurredToUtc: fromDateTimeLocal(toDraft), page: 1 });
      }}>
        <label><span>Участник</span><select value={state.actorUserId ?? ""} onChange={(event) => update({ actorUserId: event.target.value || null, page: 1 })}><option value="">Все участники</option>{actorOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label><span>Событие</span><select value={state.eventType ?? ""} onChange={(event) => update({ eventType: event.target.value ? event.target.value as AdminAuditUrlState["eventType"] : null, page: 1 })}><option value="">Все события</option>{AUDIT_EVENT_TYPES.map((eventType) => <option key={eventType} value={eventType}>{EVENT_LABELS[eventType]}</option>)}</select></label>
        <label><span>С даты</span><input type="datetime-local" value={fromDraft} onChange={(event) => setFromDraft(event.target.value)} /></label>
        <label><span>По дату</span><input type="datetime-local" value={toDraft} onChange={(event) => setToDraft(event.target.value)} /></label>
        <label><span>Порядок</span><select value={state.sort} onChange={(event) => update({ sort: event.target.value as AdminAuditUrlState["sort"], page: 1 })}>{AUDIT_SORTS.map((sort) => <option key={sort} value={sort}>{sort === "occurred_desc" ? "Сначала новые" : "Сначала старые"}</option>)}</select></label>
        <Button type="submit">Применить</Button>
      </form>
      {query.isPending ? <AdminLoading label="Загружаем журнал действий" /> : null}
      {query.isError ? <AdminError error={query.error} onRetry={() => { void query.refetch(); }} /> : null}
      {query.data && !query.isError && rows.length === 0 ? <EmptyAdminState title="События не найдены" description="Измените период или фильтры журнала." /> : null}
      {query.data && !query.isError && rows.length > 0 ? (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.dataTable}>
              <thead><tr><th>Время</th><th>Участник</th><th>Событие</th><th>Объект</th><th>Результат</th><th>Описание</th></tr></thead>
              <tbody>{rows.map((event) => <tr key={event.event_id}><td>{formatAdminDate(event.occurred_at_utc)}</td><td>{event.actor_display_name ?? "Системное событие"}</td><td>{EVENT_LABELS[event.event_type]}</td><td>{TARGET_LABELS[event.target_type] ?? "Объект операции"}</td><td><span className={`${styles.statusPill} ${styles[`result_${event.result}`]}`}>{RESULT_LABELS[event.result]}</span></td><td>{event.browser_safe_summary}</td></tr>)}</tbody>
            </table>
          </div>
          <div className={styles.mobileCards}>{rows.map((event) => <article className={styles.auditCard} key={event.event_id}><header><span>{formatAdminDate(event.occurred_at_utc)}</span><span className={`${styles.statusPill} ${styles[`result_${event.result}`]}`}>{RESULT_LABELS[event.result]}</span></header><h2>{EVENT_LABELS[event.event_type]}</h2><p>{event.browser_safe_summary}</p><dl><div><dt>Участник</dt><dd>{event.actor_display_name ?? "Системное событие"}</dd></div><div><dt>Объект</dt><dd>{TARGET_LABELS[event.target_type] ?? "Объект операции"}</dd></div></dl></article>)}</div>
          <div className={styles.pagination}><span>Показано {rows.length} из {query.data.pagination.total_items}</span><div><Button disabled={state.page <= 1} onClick={() => update({ page: state.page - 1 })}>Назад</Button><span>Страница {state.page} из {Math.max(query.data.pagination.total_pages, 1)}</span><Button disabled={state.page >= query.data.pagination.total_pages} onClick={() => update({ page: state.page + 1 })}>Далее</Button></div></div>
        </>
      ) : null}
    </AdminPage>
  );
}
