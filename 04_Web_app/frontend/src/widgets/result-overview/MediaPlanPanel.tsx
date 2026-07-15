import { useMemo, useState } from "react";
import type {
  DownloadViewModel,
  ResultOverviewViewModel,
} from "../../features/calculation-result/buildResultOverviewModel";
import { appEnv } from "../../shared/config/env";
import {
  formatPercent,
  formatRub,
  formatSignedRub,
} from "../../shared/formatters/metrics";
import { Card } from "../../shared/ui/Card";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import styles from "./result-overview.module.css";

function artifactUrl(path: string): string {
  const baseUrl = appEnv.apiBaseUrl.replace(/\/+$/, "");
  return path.startsWith("http") ? path : `${baseUrl}${path.startsWith("/") ? "" : "/"}${path}`;
}

function PlanDownloadButton({ download, demoData }: { download: DownloadViewModel | null; demoData: boolean }) {
  const available = appEnv.resultProvider === "http" && !demoData && download !== null;
  return (
    <button
      type="button"
      className={styles.inlineAction}
      disabled={!available}
      onClick={() => {
        if (available && download) window.location.assign(artifactUrl(download.downloadPath));
      }}
    >
      Скачать медиаплан CSV
    </button>
  );
}

export function MediaPlanPanel({ model }: { model: ResultOverviewViewModel }) {
  const [channel, setChannel] = useState("all");
  const [geo, setGeo] = useState("all");
  const channels = useMemo(
    () => Array.from(new Set(model.allocations.map((line) => line.channel))),
    [model.allocations],
  );
  const geographies = useMemo(
    () => Array.from(new Set(model.allocations.map((line) => line.geo))),
    [model.allocations],
  );
  const visibleLines = model.allocations.filter(
    (line) => (channel === "all" || line.channel === channel) && (geo === "all" || line.geo === geo),
  );
  const planDownload = model.downloads.find((download) => download.kind === "media-plan") ?? null;

  return (
    <section className={styles.tabSection} aria-labelledby="plan-heading">
      <header className={styles.tabIntro}>
        <div>
          <span className={styles.panelLabel}>Медиаплан</span>
          <h2 id="plan-heading">Было → рекомендуется</h2>
        </div>
        <p>
          Каждая строка — готовое сравнение для сегмента, географии и канала. Дельты
          получены готовыми и не пересчитываются в браузере.
        </p>
      </header>

      <div className={styles.planSummary}>
        <Card><span>Загруженный бюджет</span><strong>{formatRub(model.coverage.uploadedBudgetRub)}</strong></Card>
        <Card><span>Перемещаемый бюджет</span><strong>{formatRub(model.recommendation.movedBudgetRub)}</strong></Card>
        <Card><span>Статус плана</span><strong>{model.recommendation.plan.label}</strong></Card>
        <Card><span>Сводные итоги по каналам и гео</span><strong>Нет данных</strong><small>В текущем контракте доступны только строки</small></Card>
      </div>

      <Card as="section" className={styles.planWorkspace}>
        <div className={styles.planToolbar}>
          <div className={styles.planFilters}>
            <label>
              Канал
              <select value={channel} onChange={(event) => setChannel(event.target.value)}>
                <option value="all">Все каналы</option>
                {channels.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label>
              География
              <select value={geo} onChange={(event) => setGeo(event.target.value)}>
                <option value="all">Все географии</option>
                {geographies.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          </div>
          <PlanDownloadButton download={planDownload} demoData={model.demoData} />
        </div>

        {visibleLines.length === 0 ? (
          <div className={styles.inlineEmpty} role="status">
            <strong>Нет данных</strong>
            <p>Для выбранных фильтров строки медиаплана отсутствуют.</p>
          </div>
        ) : (
          <>
            <div className={styles.planTableWrap}>
              <table className={styles.planTable}>
                <thead>
                  <tr>
                    <th>Сегмент</th><th>География</th><th>Канал</th><th>Было</th>
                    <th>Рекомендуется</th><th>Изменение</th><th>Доля было</th>
                    <th>Доля станет</th><th>Действие</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleLines.map((line) => (
                    <tr key={line.id}>
                      <td>{line.segment}</td><td>{line.geo}</td><td>{line.channel}</td>
                      <td>{formatRub(line.uploadedBudgetRub)}</td>
                      <td>{formatRub(line.recommendedBudgetRub)}</td>
                      <td>{formatSignedRub(line.deltaBudgetRub)}</td>
                      <td>{formatPercent(line.uploadedBudgetShare)}</td>
                      <td>{formatPercent(line.recommendedBudgetShare)}</td>
                      <td>
                        <div className={styles.planAction}>
                          <StatusBadge tone={line.action.tone === "positive" ? "accent" : line.action.tone}>{line.action.label}</StatusBadge>
                          {line.restriction ? <small>{line.restriction.label}</small> : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={styles.planCards}>
              {visibleLines.map((line) => (
                <article key={line.id} className={styles.planLineCard}>
                  <div className={styles.planLineHead}>
                    <div><strong>{line.channel}</strong><span>{line.geo} · {line.segment}</span></div>
                    <StatusBadge tone={line.action.tone === "positive" ? "accent" : line.action.tone}>{line.action.label}</StatusBadge>
                  </div>
                  <dl>
                    <div><dt>Было</dt><dd>{formatRub(line.uploadedBudgetRub)}</dd></div>
                    <div><dt>Рекомендуется</dt><dd>{formatRub(line.recommendedBudgetRub)}</dd></div>
                    <div><dt>Изменение</dt><dd>{formatSignedRub(line.deltaBudgetRub)}</dd></div>
                  </dl>
                  {line.restriction ? (
                    <p className={styles.planRestriction}>{line.restriction.label}. {line.restriction.action}</p>
                  ) : null}
                </article>
              ))}
            </div>
          </>
        )}
      </Card>
    </section>
  );
}
