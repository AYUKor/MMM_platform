import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import type { DecisionJob } from "../entities/lifecycle/types";
import { listJobs, type JobListItem } from "../shared/api/lifecycle-client";
import { formatDate, formatRub } from "../shared/formatters/metrics";
import { ErrorState } from "../shared/ui/ErrorState";
import { LoadingSkeleton } from "../shared/ui/LoadingSkeleton";
import { StatusBadge } from "../shared/ui/StatusBadge";
import styles from "./lifecycle.module.css";

function destination(job: DecisionJob): string {
  return job.status.code === "succeeded"
    ? `/calculations/${job.job_id}/result`
    : `/calculations/${job.job_id}/progress`;
}

function statusTone(job: DecisionJob): "neutral" | "accent" | "warning" | "danger" {
  if (job.status.code === "succeeded") return "accent";
  if (["failed", "cancelled", "timed_out"].includes(job.status.code)) return "danger";
  return "warning";
}

function campaignLabel(item: JobListItem): string {
  const names = item.campaigns.map((campaign) => campaign.campaign_name);
  return names.length ? names.join(", ") : "Кампания без preview";
}

export function CalculationsPage() {
  const query = useQuery({
    queryKey: ["jobs"],
    queryFn: listJobs,
    refetchInterval: 3000,
  });

  if (query.isLoading) return <LoadingSkeleton />;
  if (query.isError || !query.data) {
    return <ErrorState title="Не удалось загрузить расчеты" description={query.error instanceof Error ? query.error.message : "Backend недоступен."} />;
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <span className={styles.eyebrow}>Рабочее пространство</span>
          <h1>Мои расчеты</h1>
          <p className={styles.muted}>{query.data.total} задач в локальном backend</p>
        </div>
        <Link className={styles.textLink} to="/calculations/new">+ Новый расчет</Link>
      </header>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead><tr><th>Кампания</th><th>Период</th><th>Бюджет</th><th>Создан</th><th>Статус</th><th /></tr></thead>
          <tbody>
            {query.data.items.length === 0 ? (
              <tr><td className={styles.emptyRow} colSpan={6}>Расчетов пока нет</td></tr>
            ) : query.data.items.map((item) => {
              const first = item.campaigns[0];
              const budget = item.campaigns.reduce((sum, campaign) => sum + campaign.uploaded_budget_rub, 0);
              return (
                <tr key={item.job.job_id}>
                  <td><strong>{campaignLabel(item)}</strong></td>
                  <td>{first ? `${formatDate(first.start_date)} — ${formatDate(first.end_date)}` : "Нет данных"}</td>
                  <td>{item.campaigns.length ? formatRub(budget) : "Нет данных"}</td>
                  <td>{new Date(item.job.created_at_utc).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" })}</td>
                  <td><StatusBadge tone={statusTone(item.job)}>{item.job.status.display_text}</StatusBadge></td>
                  <td><Link className={styles.textLink} to={destination(item.job)}>Открыть</Link></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
