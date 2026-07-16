import type { Artifact, JobResultViewV1 } from "../../shared/api/generated/job-result-view-v1";
import { resolveArtifactDownloadUrl } from "../../shared/api/job-result-client";
import { formatBytes } from "../../shared/formatters/metrics";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import { formatGeneratedAt } from "./jobResultFormatting";
import { UnavailableBlock } from "./ResultVisuals";
import styles from "./job-result.module.css";

function reportStatusLabel(status: JobResultViewV1["report"]["status"]): string {
  if (status === "ready") return "Отчет готов";
  if (status === "failed") return "Не удалось сформировать отчет";
  return "Отчет недоступен";
}

function artifactDownloadUrl(artifact: Artifact | null): string | null {
  if (artifact === null) return null;
  try {
    return resolveArtifactDownloadUrl(artifact.download_path);
  } catch {
    return null;
  }
}

function artifactGlyph(displayName: string): string {
  const extension = displayName.split(".").pop()?.toUpperCase() ?? "";
  return /^[A-Z0-9]{2,5}$/.test(extension) ? extension : "ФАЙЛ";
}

export function ReportTab({ result }: { result: JobResultViewV1 }) {
  const { report } = result;
  const downloadUrl = report.status === "ready" ? artifactDownloadUrl(report.artifact) : null;
  const workingPlan = report.working_media_plan;
  const workingPlanDownloadUrl = workingPlan.status === "ready"
    ? artifactDownloadUrl(workingPlan.artifact)
    : null;

  return (
    <div className={styles.tabStack}>
      <section className={`${styles.reportHero} ${styles[`report-${report.status}`]}`} aria-labelledby="report-title">
        <div>
          <span className={styles.eyebrow}>Итоговый артефакт</span>
          <h2 id="report-title">{reportStatusLabel(report.status)}</h2>
          <p>{report.display_text}</p>
          <span className={styles.reportTimestamp}>{formatGeneratedAt(report.generated_at_utc)}</span>
        </div>
        <StatusBadge tone={report.status === "ready" ? "accent" : report.status === "failed" ? "danger" : "warning"}>
          {report.status === "ready" ? "Готов к скачиванию" : report.status === "failed" ? "Ошибка" : "Нет данных"}
        </StatusBadge>
      </section>

      {report.status === "ready" && report.artifact !== null ? (
        <section className={styles.reportDownload} aria-labelledby="report-download-title">
          <div>
            <span className={styles.fileGlyph} aria-hidden="true">XLSX</span>
            <div>
              <h3 id="report-download-title">{report.artifact.display_name}</h3>
              <p>{formatBytes(report.artifact.size_bytes)} · Excel-отчет</p>
            </div>
          </div>
          {downloadUrl ? (
            <a className={styles.downloadButton} href={downloadUrl} download>
              Скачать отчет
            </a>
          ) : (
            <StatusBadge tone="danger">Ссылка не прошла проверку</StatusBadge>
          )}
        </section>
      ) : (
        <UnavailableBlock title="Excel-отчет" description={report.display_text} />
      )}

      {report.sheets.length > 0 ? (
        <section className={styles.sheetSection} aria-labelledby="report-sheets-title">
          <div className={styles.sectionHeading}>
            <div><span className={styles.eyebrow}>Состав файла</span><h3 id="report-sheets-title">Листы отчета</h3></div>
            <span>{report.sheets.length}</span>
          </div>
          <ol className={styles.sheetList}>
            {report.sheets.map((sheet, index) => (
              <li key={sheet.sheet_name}>
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
            <span className={styles.fileGlyph} aria-hidden="true">{artifactGlyph(workingPlan.artifact.display_name)}</span>
            <div>
              <h3 id="working-plan-download-title">{workingPlan.artifact.display_name}</h3>
              <p>{formatBytes(workingPlan.artifact.size_bytes)} · Рабочий медиаплан</p>
            </div>
          </div>
          {workingPlanDownloadUrl ? (
            <a className={styles.downloadButton} href={workingPlanDownloadUrl} download>
              Скачать медиаплан
            </a>
          ) : (
            <StatusBadge tone="danger">Ссылка не прошла проверку</StatusBadge>
          )}
        </section>
      ) : (
        <UnavailableBlock
          title="Рабочий Excel-медиаплан"
          description={workingPlan.display_text}
        />
      )}

      <section className={styles.reportGuidance} aria-labelledby="report-guidance-title">
        <span className={styles.eyebrow}>Как использовать результат</span>
        <h3 id="report-guidance-title">Рекомендация относится к распределению бюджета</h3>
        <p>
          Отчет не является автоматическим решением запускать кампанию. Перед запуском проверьте
          ограничения, доступность инвентаря и бизнес-контекст.
        </p>
      </section>

      <section className={styles.limitations} aria-labelledby="report-limitations-title">
        <h3 id="report-limitations-title">Ограничения результата</h3>
        <ul>{result.limitations.map((limitation) => <li key={limitation.code}>{limitation.display_text}</li>)}</ul>
      </section>
    </div>
  );
}
