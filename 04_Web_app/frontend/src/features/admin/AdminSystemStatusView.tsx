import { useQuery } from "@tanstack/react-query";
import { getAdminSystemStatus } from "../../shared/api/auth-admin-client";
import {
  SYSTEM_FACT_LABELS,
  SYSTEM_STATUS_LABELS,
  SUBSYSTEM_LABELS,
  formatAdminDate,
  formatSystemFact,
} from "./adminModel";
import { AdminError, AdminLoading, AdminPage } from "./AdminPageState";
import styles from "./admin.module.css";

export function AdminSystemStatusView() {
  const query = useQuery({
    queryKey: ["phase-e", "admin-system-status"],
    queryFn: ({ signal }) => getAdminSystemStatus(signal),
    refetchOnWindowFocus: false,
  });
  return (
    <AdminPage eyebrow="Администрирование" title="Состояние системы" description="Безопасная сводка готовности сервисов, необходимых для расчета.">
      {query.isPending ? <AdminLoading label="Проверяем состояние системы" /> : null}
      {query.isError ? <AdminError error={query.error} onRetry={() => { void query.refetch(); }} /> : null}
      {query.data && !query.isError ? (
        <>
          <section className={`${styles.overallStatus} ${styles[`system_${query.data.overall_status}`]}`}>
            <div><span>Общее состояние</span><h2>{SYSTEM_STATUS_LABELS[query.data.overall_status]}</h2></div>
            <p>Проверено {formatAdminDate(query.data.checked_at_utc)}</p>
          </section>
          <div className={styles.systemGrid}>
            {Object.entries(query.data.subsystems).map(([key, subsystem]) => (
              <article className={styles.systemCard} key={key}>
                <header><h3>{SUBSYSTEM_LABELS[key as keyof typeof SUBSYSTEM_LABELS]}</h3><span className={`${styles.statusPill} ${styles[`system_${subsystem.status}`]}`}>{SYSTEM_STATUS_LABELS[subsystem.status]}</span></header>
                <p>{subsystem.display_text}</p>
                <dl>{Object.entries(subsystem.facts).map(([factKey, value]) => SYSTEM_FACT_LABELS[factKey] ? <div key={factKey}><dt>{SYSTEM_FACT_LABELS[factKey]}</dt><dd>{formatSystemFact(factKey, value)}</dd></div> : null)}</dl>
              </article>
            ))}
          </div>
          <section className={styles.buildStrip} aria-label="Версии приложения">
            <div><span>Приложение</span><strong>{query.data.build.application_version}</strong></div>
            <div><span>Контракт сервиса</span><strong>{query.data.build.api_version}</strong></div>
            <div><span>Конфигурация</span><strong>{query.data.build.config_schema_version}</strong></div>
          </section>
        </>
      ) : null}
    </AdminPage>
  );
}
