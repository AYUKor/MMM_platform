import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import type { JobProgressViewV1 } from "../../shared/api/generated/job-progress-view-v1";
import { formatDate, formatRub } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import {
  currentStage,
  currentStatusCopy,
  formatCount,
  formatCounterPair,
  formatStageTime,
  jobStatusLabel,
  jobStatusTone,
  queuePositionText,
  scenario6StatusText,
  sortProgressErrors,
  stageStatusLabel,
  type MMMFact,
} from "./jobProgressModel";
import styles from "./job-progress.module.css";

interface RefreshNotice {
  description: string;
  actionLabel: string;
}

interface JobProgressViewProps {
  view: JobProgressViewV1;
  fact: MMMFact | null;
  refreshNotice?: RefreshNotice | null;
  onRefresh: () => void;
  onCancel: () => Promise<void>;
  cancelPending: boolean;
  cancelError?: string | null;
}

interface CancelDialogProps {
  open: boolean;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}

function CancelDialog({
  open,
  pending,
  error,
  onClose,
  onConfirm,
}: CancelDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    const firstEnabledControl = dialog?.querySelector<HTMLButtonElement>("button:not(:disabled)");
    (firstEnabledControl ?? dialog)?.focus();
  }, [open, pending]);

  if (!open) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && !pending) {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const controls = Array.from(
      dialogRef.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [],
    );
    if (controls.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      className={styles.dialogBackdrop}
      onMouseDown={(event) => {
        if (event.currentTarget === event.target && !pending) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cancel-dialog-title"
        aria-describedby="cancel-dialog-description"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <span className={styles.eyebrow}>Подтверждение действия</span>
        <h2 id="cancel-dialog-title">Отменить расчет?</h2>
        <p id="cancel-dialog-description">
          Система безопасно остановит задачу. Уже выполненные этапы не станут готовым результатом.
        </p>
        {error ? <p className={styles.dialogError} role="alert">{error}</p> : null}
        <div className={styles.dialogActions}>
          <Button disabled={pending} onClick={onClose}>
            Продолжить расчет
          </Button>
          <Button
            disabled={pending}
            onClick={() => {
              void onConfirm();
            }}
          >
            {pending ? "Отправляем запрос…" : "Отменить расчет"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function StageGlyph({ status }: { status: JobProgressViewV1["stages"][number]["status"] }) {
  const glyph = {
    pending: "·",
    active: "●",
    completed: "✓",
    warning: "!",
    failed: "×",
    skipped: "—",
  }[status];
  return <span className={styles.stageGlyph} aria-hidden="true">{glyph}</span>;
}

function StageProgress({ stage }: { stage: JobProgressViewV1["stages"][number] }) {
  if (!stage.progress) return null;
  const value = stage.progress.total === null
    ? `${formatCount(stage.progress.current)} ${stage.progress.unit}`
    : `${formatCounterPair(stage.progress.current, stage.progress.total)} ${stage.progress.unit}`;
  return <span className={styles.stageCounter} aria-label={`Прогресс этапа: ${value}`}>{value}</span>;
}

function Scenario6Panel({ view }: { view: JobProgressViewV1 }) {
  const state = view.scenario6;
  const showCounters = state.status === "running" || state.status === "completed";
  const relatedError = sortProgressErrors(view.errors).find((error) => error.stage_id === "P06");
  return (
    <section className={styles.contextPanel} aria-labelledby="scenario6-title">
      <span className={styles.panelIndex}>06</span>
      <h2 id="scenario6-title">Адаптивный поиск</h2>
      <p className={styles.panelLead}>{scenario6StatusText(state.status)}</p>
      {showCounters ? (
        <dl className={styles.counterList}>
          {state.attempts_checked !== null ? (
            <div>
              <dt>Проверено вариантов</dt>
              <dd>
                {state.attempt_budget === null
                  ? formatCount(state.attempts_checked)
                  : formatCounterPair(state.attempts_checked, state.attempt_budget)}
              </dd>
            </div>
          ) : null}
          {state.finalists_scored !== null ? (
            <div>
              <dt>Пересчитано финалистов</dt>
              <dd>
                {state.finalists_total === null
                  ? formatCount(state.finalists_scored)
                  : formatCounterPair(state.finalists_scored, state.finalists_total)}
              </dd>
            </div>
          ) : null}
          {state.safe_candidates !== null ? (
            <div><dt>Прошли проверку</dt><dd>{formatCount(state.safe_candidates)}</dd></div>
          ) : null}
          {state.blocked_candidates !== null ? (
            <div><dt>Требуют проверки</dt><dd>{formatCount(state.blocked_candidates)}</dd></div>
          ) : null}
        </dl>
      ) : null}
      {state.status === "failed" && relatedError ? (
        <p className={styles.contextError}>{relatedError.display_text}</p>
      ) : null}
    </section>
  );
}

function ReportPanel({ view }: { view: JobProgressViewV1 }) {
  const title = view.report.status === "completed"
    ? "Excel-отчет готов"
    : view.report.status === "failed"
      ? "Отчет не сформирован"
      : "Отчет";
  return (
    <section className={styles.contextPanel} aria-labelledby="report-title">
      <span className={styles.panelIndex}>08</span>
      <h2 id="report-title">{title}</h2>
      <p className={styles.panelLead}>{view.report.display_text}</p>
      {view.report.status === "failed" && view.report.retryable ? (
        <span className={styles.inlineStatus}>Формирование можно повторить позже</span>
      ) : null}
    </section>
  );
}

export function JobProgressView({
  view,
  fact,
  refreshNotice = null,
  onRefresh,
  onCancel,
  cancelPending,
  cancelError = null,
}: JobProgressViewProps) {
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const fallbackFocusRef = useRef<HTMLHeadingElement>(null);
  const statusCopy = currentStatusCopy(view);
  const stage = currentStage(view);
  const queueText = queuePositionText(view);
  const errors = sortProgressErrors(view.errors);
  const primaryError = errors[0];
  const isInProgress = ["queued", "running", "cancel_requested"].includes(view.job_status.code);
  const showIndeterminate = isInProgress && (
    view.job_status.code !== "running" || stage.progress === null
  );

  const closeDialog = useCallback(() => {
    setCancelDialogOpen(false);
    window.requestAnimationFrame(() => {
      const trigger = returnFocusRef.current;
      if (trigger?.isConnected && !trigger.hasAttribute("disabled")) {
        trigger.focus();
      } else {
        fallbackFocusRef.current?.focus();
      }
    });
  }, []);

  useEffect(() => {
    if (!cancelDialogOpen || view.can_cancel) return;
    const frame = window.requestAnimationFrame(() => {
      setCancelDialogOpen(false);
      fallbackFocusRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [cancelDialogOpen, view.can_cancel]);

  const confirmCancel = async () => {
    try {
      await onCancel();
      closeDialog();
    } catch {
      // The parent exposes a browser-safe message inside the dialog.
    }
  };

  return (
    <div className={styles.page}>
      <nav className={styles.breadcrumbs} aria-label="Хлебные крошки">
        <Link to="/calculations">Мои расчеты</Link>
        <span aria-hidden="true">/</span>
        <span aria-current="page">Ход расчета</span>
      </nav>

      <header className={styles.campaignHeader}>
        <div className={styles.campaignTitle}>
          <div className={styles.headerLabels}>
            <span className={styles.eyebrow}>Расчет кампании</span>
            {view.record_origin === "synthetic_fixture" ? (
              <span className={styles.demoBadge}>Демонстрационные данные</span>
            ) : null}
          </div>
          <h1>{view.campaign.campaign_name}</h1>
        </div>
        <div
          className={`${styles.campaignStatus} ${
            view.job_status.code === "succeeded" ? styles.campaignStatusSuccess : ""
          }`}
        >
          <StatusBadge tone={jobStatusTone(view.job_status.code)}>
            {jobStatusLabel(view.job_status.code)}
          </StatusBadge>
        </div>
        <dl className={styles.campaignMeta}>
          <div><dt>Сегменты</dt><dd>{view.campaign.segment.join(", ")}</dd></div>
          <div><dt>Период</dt><dd>{formatDate(view.campaign.start_date)} — {formatDate(view.campaign.end_date)}</dd></div>
          <div><dt>Бюджет</dt><dd>{formatRub(view.campaign.total_budget_rub)}</dd></div>
          <div><dt>Каналы</dt><dd>{formatCount(view.campaign.channels_n)}</dd></div>
          <div><dt>Географии</dt><dd>{formatCount(view.campaign.geographies_n)}</dd></div>
        </dl>
      </header>

      {refreshNotice ? (
        <div className={styles.refreshNotice} role="status">
          <span>{refreshNotice.description}</span>
          <Button onClick={onRefresh}>{refreshNotice.actionLabel}</Button>
        </div>
      ) : null}

      <div className={styles.layout}>
        <div className={styles.mainColumn}>
          <section
            className={`${styles.statusCard} ${styles[`status-${view.job_status.code}`]}`}
            aria-labelledby="current-status-title"
            aria-live="polite"
          >
            <div className={styles.statusCardTopline}>
              <span className={styles.eyebrow}>Текущий статус</span>
              <span>Обновлено {formatStageTime(view.updated_at_utc)}</span>
            </div>
            <h2 ref={fallbackFocusRef} id="current-status-title" tabIndex={-1}>
              {statusCopy.title}
            </h2>
            <p>{statusCopy.description}</p>
            {queueText ? <strong className={styles.queuePosition}>{queueText}</strong> : null}
            {view.job_status.code === "running" ? <StageProgress stage={stage} /> : null}
            {showIndeterminate ? (
              <div className={styles.indeterminate} aria-hidden="true"><span /></div>
            ) : null}
            {(view.job_status.code === "failed" || view.job_status.code === "timed_out") && primaryError ? (
              <div className={styles.primaryError}>
                <strong>{primaryError.display_text}</strong>
                <span>Что можно сделать: {primaryError.recommended_action}</span>
              </div>
            ) : null}
            <div className={styles.statusActions}>
              {view.can_cancel ? (
                <Button
                  disabled={cancelPending}
                  onClick={(event) => {
                    returnFocusRef.current = event.currentTarget;
                    setCancelDialogOpen(true);
                  }}
                >
                  Отменить расчет
                </Button>
              ) : null}
              {view.result_available ? (
                <Link className={styles.primaryLink} to={`/calculations/${encodeURIComponent(view.job_id)}/result`}>
                  Открыть результат
                </Link>
              ) : null}
              <Link className={styles.secondaryLink} to="/calculations">Все расчеты</Link>
            </div>
          </section>

          <section className={styles.timelineSection} aria-labelledby="timeline-title">
            <div className={styles.sectionHeading}>
              <div><span className={styles.eyebrow}>Последовательность</span><h2 id="timeline-title">Этапы расчета</h2></div>
              <span>9 этапов</span>
            </div>
            <ol className={styles.timeline}>
              {view.stages.map((item) => (
                <li key={item.stage_id} className={`${styles.timelineItem} ${styles[`stage-${item.status}`]}`}>
                  <div className={styles.stageRail}>
                    <span className={styles.stageOrder}>{String(item.order).padStart(2, "0")}</span>
                    <StageGlyph status={item.status} />
                  </div>
                  <div className={styles.stageBody}>
                    <div className={styles.stageTitleRow}>
                      <h3>{item.title}</h3>
                      <span>{stageStatusLabel(item.status)}</span>
                    </div>
                    <p>{item.display_text}</p>
                    <div className={styles.stageDetails}>
                      {item.started_at_utc ? <span>Начат {formatStageTime(item.started_at_utc)}</span> : null}
                      {item.finished_at_utc ? <span>Завершен {formatStageTime(item.finished_at_utc)}</span> : null}
                      <StageProgress stage={item} />
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>

        <aside className={styles.contextColumn} aria-label="Дополнительные сведения о расчете">
          <Scenario6Panel view={view} />
          <ReportPanel view={view} />
          {fact ? (
            <section className={`${styles.contextPanel} ${styles.factPanel}`} aria-labelledby="mmm-fact-title">
              <span className={styles.eyebrow}>Коротко о методе</span>
              <h2 id="mmm-fact-title">MMM за минуту</h2>
              <p>{fact.text}</p>
              <small>Источник: {fact.source_label}</small>
            </section>
          ) : null}
          {isInProgress ? (
            <section className={styles.leaveNotice} aria-label="Расчет продолжится в фоне">
              <strong>Можно перейти на другую страницу</strong>
              <p>Расчет продолжится, а его статус сохранится в разделе «Мои расчеты».</p>
            </section>
          ) : null}
        </aside>
      </div>

      {errors.length > 0 ? (
        <section className={styles.errorsSection} aria-labelledby="errors-title">
          <div className={styles.sectionHeading}>
            <div><span className={styles.eyebrow}>Требует внимания</span><h2 id="errors-title">Замечания по расчету</h2></div>
          </div>
          <ul className={styles.errorList}>
            {errors.map((error) => {
              const errorStage = view.stages.find((item) => item.stage_id === error.stage_id);
              return (
                <li
                  key={error.error_id}
                  className={error.severity === "error" ? styles.blockingError : styles.warningError}
                >
                  <div className={styles.errorHeading}>
                    <strong>{error.severity === "error" ? "Ошибка" : "Предупреждение"}</strong>
                    <span>{errorStage?.title ?? "Этап расчета"}</span>
                  </div>
                  <p>{error.display_text}</p>
                  <span>Что можно сделать: {error.recommended_action}</span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <CancelDialog
        open={cancelDialogOpen && view.can_cancel}
        pending={cancelPending}
        error={cancelError}
        onClose={closeDialog}
        onConfirm={confirmCancel}
      />
    </div>
  );
}
