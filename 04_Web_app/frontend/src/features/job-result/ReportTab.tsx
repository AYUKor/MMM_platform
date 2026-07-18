import type { JobResultViewV2 } from "../../shared/api/generated/job-result-view-v2";
import {
  UnsupportedReportArtifactsContractError,
  resolveReportArtifactDownloadUrl,
  type JobReportArtifacts,
  type ReportArtifact,
} from "../../shared/api/report-artifacts-client";
import { formatBytes } from "../../shared/formatters/metrics";
import { Button } from "../../shared/ui/Button";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import { UnavailableBlock } from "./ResultVisuals";
import styles from "./job-result.module.css";

interface ReportTabProps {
  artifacts?: JobReportArtifacts;
  loading: boolean;
  error: unknown;
  canDownload: boolean;
  limitations: JobResultViewV2["limitations"];
  onRetry: () => void;
}

function reportStatusLabel(status: JobReportArtifacts["status"]): string {
  if (status === "ready") return "Отчет готов";
  if (status === "failed") return "Не удалось сформировать отчет";
  return "Отчет недоступен";
}

function artifactDownloadUrl(artifact: ReportArtifact | null): string | null {
  if (artifact === null) return null;
  try {
    return resolveReportArtifactDownloadUrl(artifact);
  } catch {
    return null;
  }
}

function artifactGlyph(displayName: string): string {
  const extension = displayName.split(".").pop()?.toUpperCase() ?? "";
  return /^[A-Z0-9]{2,5}$/.test(extension) ? extension : "ФАЙЛ";
}

function generatedAtLabel(value: string | null): string | null {
  if (value === null) return null;
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return null;
  return `Опубликован ${new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "long",
    timeStyle: "short",
  }).format(parsed)}`;
}

function ReportQueryState({ loading, error, onRetry }: Pick<ReportTabProps, "loading" | "error" | "onRetry">) {
  if (loading) {
    return (
      <section className={styles.reportHero} aria-live="polite" aria-busy="true">
        <div>
          <span className={styles.eyebrow}>Итоговый артефакт</span>
          <h2>Получаем сведения об отчете</h2>
          <p>Проверяем статус публикации и безопасные ссылки на файлы.</p>
        </div>
        <StatusBadge>Загрузка</StatusBadge>
      </section>
    );
  }

  const unsupported = error instanceof UnsupportedReportArtifactsContractError;
  return (
    <section className={`${styles.reportHero} ${styles["report-unavailable"]}`} role="alert">
      <div>
        <span className={styles.eyebrow}>Итоговый артефакт</span>
        <h2>{unsupported ? "Формат сведений об отчете не поддерживается" : "Не удалось загрузить сведения об отчете"}</h2>
        <p>
          {unsupported
            ? "Ответ не прошел защитную проверку. Ссылки на файлы не показаны."
            : "Основной результат сохранен. Повторите загрузку сведений об отчете."}
        </p>
        <Button onClick={onRetry}>Повторить</Button>
      </div>
      <StatusBadge tone="warning">Нет данных</StatusBadge>
    </section>
  );
}

export function ReportTab({
  artifacts,
  loading,
  error,
  canDownload,
  limitations,
  onRetry,
}: ReportTabProps) {
  if (!artifacts) {
    return (
      <div className={styles.tabStack}>
        <section className={styles.tabIntro}>
          <div><span className={styles.eyebrow}>Отчет</span><h2>Выгрузка результата</h2></div>
          <p>Файлы доступны только после проверки опубликованных сведений об артефактах.</p>
        </section>
        <ReportQueryState loading={loading} error={error} onRetry={onRetry} />
      </div>
    );
  }

  const reportDownloadUrl = artifacts.status === "ready"
    ? artifactDownloadUrl(artifacts.artifact)
    : null;
  const workingPlan = artifacts.workingMediaPlan;
  const workingPlanDownloadUrl = workingPlan.status === "ready"
    ? artifactDownloadUrl(workingPlan.artifact)
    : null;
  const generatedAt = generatedAtLabel(artifacts.generatedAtUtc);
  const reportStatusClass = artifacts.status === "ready" ? "" : styles[`report-${artifacts.status}`];

  return (
    <div className={styles.tabStack}>
      <section className={styles.tabIntro}>
        <div><span className={styles.eyebrow}>Отчет</span><h2>Выгрузка результата</h2></div>
        <p>Статус, состав и ссылки на файлы получены из опубликованных сведений об артефактах.</p>
      </section>

      <section className={`${styles.reportHero} ${reportStatusClass}`} aria-labelledby="report-title">
        <div>
          <span className={styles.eyebrow}>Итоговый артефакт</span>
          <h2 id="report-title">{reportStatusLabel(artifacts.status)}</h2>
          <p>{artifacts.displayText}</p>
          {generatedAt ? <span className={styles.reportTimestamp}>{generatedAt}</span> : null}
        </div>
        <StatusBadge tone={artifacts.status === "ready" ? "accent" : artifacts.status === "failed" ? "danger" : "warning"}>
          {artifacts.status === "ready" ? "Готов к скачиванию" : artifacts.status === "failed" ? "Ошибка" : "Нет данных"}
        </StatusBadge>
      </section>

      {artifacts.status === "ready" && artifacts.artifact !== null ? (
        <section className={styles.reportDownload} aria-labelledby="report-download-title">
          <div>
            <span className={styles.fileGlyph} aria-hidden="true">XLSX</span>
            <div>
              <h3 id="report-download-title">{artifacts.artifact.displayName}</h3>
              <p>{formatBytes(artifacts.artifact.sizeBytes)} · Excel-отчет</p>
            </div>
          </div>
          {reportDownloadUrl && canDownload ? (
            <a className={styles.downloadButton} href={reportDownloadUrl} download>
              Скачать отчет
            </a>
          ) : reportDownloadUrl ? (
            <StatusBadge tone="warning">Нет доступа к скачиванию</StatusBadge>
          ) : (
            <StatusBadge tone="danger">Ссылка не прошла проверку</StatusBadge>
          )}
        </section>
      ) : (
        <UnavailableBlock
          title="Excel-отчет"
          description={artifacts.status === "failed"
            ? "Файл отчета не опубликован из-за ошибки формирования."
            : "Проверенная ссылка на файл отчета пока не опубликована."}
        />
      )}

      {artifacts.sheets.length > 0 ? (
        <section className={styles.sheetSection} aria-labelledby="report-sheets-title">
          <div className={styles.sectionHeading}>
            <div><span className={styles.eyebrow}>Состав файла</span><h3 id="report-sheets-title">Листы отчета</h3></div>
            <span>{artifacts.sheets.length}</span>
          </div>
          <ol className={styles.sheetList}>
            {artifacts.sheets.map((sheet, index) => (
              <li key={sheet.sheetName}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{sheet.title}</strong><p>{sheet.description ?? "Описание листа: нет данных."}</p></div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {workingPlan.status === "ready" && workingPlan.artifact !== null ? (
        <section className={styles.reportDownload} aria-labelledby="working-plan-download-title">
          <div>
            <span className={styles.fileGlyph} aria-hidden="true">{artifactGlyph(workingPlan.artifact.displayName)}</span>
            <div>
              <h3 id="working-plan-download-title">{workingPlan.artifact.displayName}</h3>
              <p>{formatBytes(workingPlan.artifact.sizeBytes)} · Рабочий медиаплан</p>
            </div>
          </div>
          {workingPlanDownloadUrl && canDownload ? (
            <a className={styles.downloadButton} href={workingPlanDownloadUrl} download>
              Скачать медиаплан
            </a>
          ) : workingPlanDownloadUrl ? (
            <StatusBadge tone="warning">Нет доступа к скачиванию</StatusBadge>
          ) : (
            <StatusBadge tone="danger">Ссылка не прошла проверку</StatusBadge>
          )}
        </section>
      ) : (
        <UnavailableBlock title="Рабочий Excel-медиаплан" description={workingPlan.displayText} />
      )}

      <section className={styles.reportGuidance} aria-labelledby="report-guidance-title">
        <span className={styles.eyebrow}>Как использовать результат</span>
        <h3 id="report-guidance-title">Рекомендация относится к распределению бюджета</h3>
        <p>
          Отчет не является автоматическим решением запускать кампанию. Перед запуском проверьте
          ограничения, доступность инвентаря и бизнес-контекст.
        </p>
      </section>

      {limitations.length > 0 ? (
        <section className={styles.limitations} aria-labelledby="report-limitations-title">
          <h3 id="report-limitations-title">Ограничения результата</h3>
          <ul>{limitations.map((limitation) => <li key={limitation.code}>{limitation.display_text}</li>)}</ul>
        </section>
      ) : null}
    </div>
  );
}
