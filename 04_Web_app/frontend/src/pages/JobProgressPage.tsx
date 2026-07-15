import { useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  cancelJob,
  getJob,
  getJobErrors,
  getJobProgress,
} from "../shared/api/lifecycle-client";
import { Button } from "../shared/ui/Button";
import { ErrorState } from "../shared/ui/ErrorState";
import { LoadingSkeleton } from "../shared/ui/LoadingSkeleton";
import { StatusBadge } from "../shared/ui/StatusBadge";
import styles from "./lifecycle.module.css";

const terminalStatuses = new Set(["succeeded", "failed", "cancelled", "timed_out"]);

export function JobProgressPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const jobQuery = useQuery({
    queryKey: ["job", id],
    queryFn: () => getJob(id),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      terminalStatuses.has(query.state.data?.status.code ?? "") ? false : 1000,
  });
  const progressQuery = useQuery({
    queryKey: ["job-progress", id],
    queryFn: () => getJobProgress(id),
    enabled: Boolean(id),
    refetchInterval: jobQuery.data && terminalStatuses.has(jobQuery.data.status.code) ? false : 1000,
  });
  const failed = jobQuery.data?.status.code === "failed" || jobQuery.data?.status.code === "timed_out";
  const errorsQuery = useQuery({
    queryKey: ["job-errors", id],
    queryFn: () => getJobErrors(id),
    enabled: Boolean(id) && failed,
  });
  const cancelMutation = useMutation({
    mutationFn: () => cancelJob(id),
    onSuccess: () => jobQuery.refetch(),
  });

  useEffect(() => {
    if (jobQuery.data?.status.code !== "succeeded") return;
    const timer = window.setTimeout(
      () => navigate(`/calculations/${id}/result`, { replace: true }),
      900,
    );
    return () => window.clearTimeout(timer);
  }, [id, jobQuery.data?.status.code, navigate]);

  if (jobQuery.isLoading) return <LoadingSkeleton />;
  if (jobQuery.isError || !jobQuery.data) {
    return <ErrorState title="Расчет не найден" description={jobQuery.error instanceof Error ? jobQuery.error.message : "Backend не вернул job."} />;
  }

  const job = jobQuery.data;
  const events = progressQuery.data ?? [];
  const latest = events.at(-1);
  const percent = latest?.percent_complete ?? (job.status.code === "succeeded" ? 100 : 0);
  const cancellable = ["queued", "running"].includes(job.status.code);

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <span className={styles.eyebrow}>Расчет кампании</span>
          <h1>{job.status.display_text}</h1>
          <p className={styles.muted}>{latest?.display_text ?? "Задача поставлена в очередь"}</p>
        </div>
        <StatusBadge tone={failed ? "danger" : job.status.code === "succeeded" ? "accent" : "warning"}>
          {job.status.display_text}
        </StatusBadge>
      </header>

      <section className={styles.progressPanel} aria-live="polite">
        <div className={styles.progressValue}>
          <div>
            <span className={styles.eyebrow}>{latest?.stage ?? "prepare"}</span>
            <p className={styles.muted}>{latest?.phase ?? "waiting"}</p>
          </div>
          <strong>{Math.round(percent)}%</strong>
        </div>
        <div className={styles.progressTrack} aria-label={`Готово ${Math.round(percent)}%`}>
          <span style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
        </div>
        <div className={styles.headerActions}>
          {cancellable ? (
            <Button disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate()}>
              {cancelMutation.isPending ? "Отменяем..." : "Отменить расчет"}
            </Button>
          ) : null}
          {job.status.code === "succeeded" ? (
            <Button variant="primary" onClick={() => navigate(`/calculations/${id}/result`)}>
              Открыть результат
            </Button>
          ) : null}
          <Link className={styles.textLink} to="/calculations">Все расчеты</Link>
        </div>
      </section>

      {errorsQuery.data?.length ? (
        <div className={styles.errorBox} role="alert">
          {errorsQuery.data.at(-1)?.display_text}
        </div>
      ) : null}

      <section>
        <div className={styles.validationHeader}>
          <div><span className={styles.eyebrow}>Progress events</span><h2>Ход расчета</h2></div>
        </div>
        <ol className={styles.timeline}>
          {events.map((event) => (
            <li key={event.progress_event_id}>
              <time>{new Date(event.emitted_at_utc).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
              <p>{event.display_text}</p>
              <span>{event.percent_complete == null ? "" : `${Math.round(event.percent_complete)}%`}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
