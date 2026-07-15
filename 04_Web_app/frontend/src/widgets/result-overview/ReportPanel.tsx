import type {
  DownloadViewModel,
  ResultOverviewViewModel,
} from "../../features/calculation-result/buildResultOverviewModel";
import { appEnv } from "../../shared/config/env";
import { formatBytes } from "../../shared/formatters/metrics";
import { Card } from "../../shared/ui/Card";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import styles from "./result-overview.module.css";

function artifactUrl(path: string): string {
  const baseUrl = appEnv.apiBaseUrl.replace(/\/+$/, "");
  return path.startsWith("http") ? path : `${baseUrl}${path.startsWith("/") ? "" : "/"}${path}`;
}

function DownloadCard({ download, demoData }: { download: DownloadViewModel; demoData: boolean }) {
  const available = appEnv.resultProvider === "http" && !demoData;
  return (
    <Card className={styles.downloadCard}>
      <div className={styles.downloadIcon} aria-hidden="true">{download.kind === "report" ? "XLSX" : "CSV"}</div>
      <div>
        <div className={styles.sectionHeading}>
          <h3>{download.title}</h3>
          <StatusBadge tone={available ? "accent" : "warning"}>
            {available ? "Готов к скачиванию" : "Недоступно в демо"}
          </StatusBadge>
        </div>
        <p>{download.description}</p>
        <span className={styles.fileMeta}>{formatBytes(download.sizeBytes)}</span>
      </div>
      <button
        type="button"
        className={styles.inlineAction}
        disabled={!available}
        onClick={() => {
          if (available) window.location.assign(artifactUrl(download.downloadPath));
        }}
      >
        Скачать {download.kind === "report" ? "Excel" : "CSV"}
      </button>
    </Card>
  );
}

export function ReportPanel({ model }: { model: ResultOverviewViewModel }) {
  return (
    <section className={styles.tabSection} aria-labelledby="report-heading">
      <header className={styles.tabIntro}>
        <div>
          <span className={styles.panelLabel}>Отчет</span>
          <h2 id="report-heading">Готовые файлы результата</h2>
        </div>
        <p>
          Интерфейс показывает только пользовательские файлы из готового результата.
          Технические файлы и внутренние идентификаторы скрыты.
        </p>
      </header>

      {model.downloads.length > 0 ? (
        <div className={styles.downloadGrid}>
          {model.downloads.map((download) => (
            <DownloadCard key={download.kind} download={download} demoData={model.demoData} />
          ))}
        </div>
      ) : (
        <Card className={styles.inlineEmpty} role="status">
          <strong>Нет данных</strong>
          <p>Сервис не передал готовый Excel-отчет или CSV медиаплана.</p>
        </Card>
      )}

      <Card className={styles.reportBoundary}>
        <span className={styles.panelLabel}>Граница текущего контракта</span>
        <h3>Предпросмотр отчета в браузере недоступен</h3>
        <p>
          Статус генерации, список листов и отдельный повторный запуск отчета не входят в
          текущий контракт. Значения не восстанавливаются из Excel в браузере.
        </p>
      </Card>
    </section>
  );
}
