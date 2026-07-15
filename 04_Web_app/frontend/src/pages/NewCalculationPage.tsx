import { useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { CampaignUpload, ValidationResult } from "../entities/lifecycle/types";
import {
  createJob,
  getUpload,
  getValidation,
  pollUntil,
  requestValidation,
  uploadCampaign,
} from "../shared/api/lifecycle-client";
import { formatDate, formatRub } from "../shared/formatters/metrics";
import { Button } from "../shared/ui/Button";
import { StatusBadge } from "../shared/ui/StatusBadge";
import styles from "./lifecycle.module.css";

type PreparationStage = "idle" | "upload" | "validation" | "review" | "job";

const stageText: Record<PreparationStage, string> = {
  idle: "Файл еще не выбран",
  upload: "Файл загружается и разбирается",
  validation: "План проверяется против текущей модели",
  review: "Проверка завершена",
  job: "Создается расчет",
};

function stepState(stage: PreparationStage, step: number): string {
  const position = { idle: 0, upload: 1, validation: 2, review: 3, job: 3 }[stage];
  if (position > step) return `${styles.step} ${styles.stepDone}`;
  if (position === step) return `${styles.step} ${styles.stepActive}`;
  return styles.step;
}

export function NewCalculationPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<PreparationStage>("idle");
  const [upload, setUpload] = useState<CampaignUpload | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
    setStage("idle");
    setUpload(null);
    setValidation(null);
    setError(null);
  };

  const prepare = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setError(null);
    setValidation(null);
    try {
      setStage("upload");
      const accepted = await uploadCampaign(file);
      setUpload(accepted);
      const parsed = await pollUntil(
        () => getUpload(accepted.upload_id),
        (record) => record.status.code !== "received",
        setUpload,
      );
      if (parsed.status.code !== "parsed") {
        throw new Error("Backend не смог разобрать загруженный файл.");
      }

      setStage("validation");
      const started = await requestValidation(parsed.upload_id);
      setValidation(started);
      const checked = await pollUntil(
        () => getValidation(started.validation_id),
        (record) => record.status.code !== "running",
        setValidation,
      );
      setStage("review");
      if (checked.status.code === "invalid" && checked.blocking_errors.length === 0) {
        throw new Error("План не прошел validation, но backend не вернул причину.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось проверить кампанию.");
      setStage("idle");
    }
  };

  const startJob = async () => {
    if (!validation?.job_creation_allowed) return;
    setError(null);
    setStage("job");
    try {
      const job = await createJob(validation.validation_id);
      navigate(`/calculations/${job.job_id}/progress`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось создать расчет.");
      setStage("review");
    }
  };

  const busy = stage === "upload" || stage === "validation" || stage === "job";
  const valid = validation?.status.code === "valid" && validation.job_creation_allowed;

  return (
    <div className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <span className={styles.eyebrow}>Новый расчет</span>
          <h1>Будущая рекламная кампания</h1>
          <p className={styles.muted}>Forecast, Scenarios 1-6 и рекомендация по распределению бюджета</p>
        </div>
      </header>

      <div className={styles.stepRow} aria-label="Этапы подготовки">
        <div className={stepState(stage, 1)}><strong>1</strong><span>Загрузка</span></div>
        <div className={stepState(stage, 2)}><strong>2</strong><span>Проверка</span></div>
        <div className={stepState(stage, 3)}><strong>3</strong><span>Запуск</span></div>
      </div>

      <form className={styles.uploadPanel} onSubmit={prepare}>
        <label className={styles.filePicker}>
          <input
            type="file"
            accept=".csv,.tsv,.xlsx,.xls"
            onChange={selectFile}
            disabled={busy}
          />
          <span>
            <strong>{file ? file.name : "Выберите медиаплан"}</strong>
            {file ? `${(file.size / 1024).toFixed(1)} КБ` : "CSV, TSV, XLSX или XLS"}
          </span>
        </label>
        <section className={styles.actionPanel}>
          <div>
            <h2>Статус</h2>
            <p className={styles.statusLine}>
              <span className={styles.statusDot} aria-hidden="true" />
              {stageText[stage]}
            </p>
            {upload?.source_rows_n != null ? (
              <p className={styles.muted}>{upload.source_rows_n} строк · {upload.detected_campaigns_n ?? 0} кампаний</p>
            ) : null}
          </div>
          <Button variant="primary" type="submit" disabled={!file || busy}>
            {busy ? "Проверяем..." : "Загрузить и проверить"}
          </Button>
        </section>
      </form>

      {error ? <div className={styles.errorBox} role="alert">{error}</div> : null}

      {validation ? (
        <section className={styles.validation} aria-label="Результат проверки">
          <div className={styles.validationHeader}>
            <div>
              <span className={styles.eyebrow}>Validation preview</span>
              <h2>{validation.status.display_text}</h2>
            </div>
            <StatusBadge tone={valid ? "accent" : "danger"}>
              {valid ? "Можно запускать" : "Нужны исправления"}
            </StatusBadge>
          </div>

          {validation.totals ? (
            <div className={styles.metricStrip}>
              <div className={styles.metric}><span>Кампаний</span><strong>{validation.campaigns.length}</strong></div>
              <div className={styles.metric}><span>Бюджет</span><strong>{formatRub(validation.totals.uploaded_budget_rub)}</strong></div>
              <div className={styles.metric}><span>В модели</span><strong>{formatRub(validation.totals.model_input_budget_rub)}</strong></div>
              <div className={styles.metric}><span>Вне модели</span><strong>{formatRub(validation.totals.unmodeled_budget_rub)}</strong></div>
            </div>
          ) : null}

          {validation.campaigns.length > 0 ? (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr><th>Кампания</th><th>Период</th><th>Каналы</th><th>Гео</th><th>Бюджет</th></tr></thead>
                <tbody>
                  {validation.campaigns.map((campaign) => (
                    <tr key={campaign.campaign_id}>
                      <td><strong>{campaign.campaign_name}</strong><br /><span className={styles.muted}>{campaign.segments.join(", ")}</span></td>
                      <td>{formatDate(campaign.start_date)}<br />{formatDate(campaign.end_date)}</td>
                      <td>{campaign.channels.join(", ")}</td>
                      <td>{campaign.geographies.length}</td>
                      <td>{formatRub(campaign.uploaded_budget_rub)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {[...validation.blocking_errors, ...validation.warnings].length > 0 ? (
            <ul className={styles.issueList}>
              {[...validation.blocking_errors, ...validation.warnings].map((issue) => (
                <li className={styles.issue} key={`${issue.code}-${issue.display_text}`}>
                  <StatusBadge tone={issue.severity === "blocking" ? "danger" : "warning"}>
                    {issue.severity === "blocking" ? "Ошибка" : "Важно"}
                  </StatusBadge>
                  <p>{issue.display_text}</p>
                </li>
              ))}
            </ul>
          ) : null}

          <div className={styles.headerActions}>
            <Button variant="primary" disabled={!valid || stage === "job"} onClick={startJob}>
              {stage === "job" ? "Создаем расчет..." : "Запустить расчет"}
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
