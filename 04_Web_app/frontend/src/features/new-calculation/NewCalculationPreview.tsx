import { useMemo, type CSSProperties } from "react";
import type {
  BudgetByChannelPreview,
  BudgetByGeoPreview,
  ChannelFlightingPreview,
  PreviewStatus,
  ValidationPreview,
  ValidationPreviewCheck,
} from "../../entities/lifecycle/types";
import { formatDate, formatRub } from "../../shared/formatters/metrics";
import { StatusBadge } from "../../shared/ui/StatusBadge";
import styles from "./new-calculation-preview.module.css";

type StatusTone = "neutral" | "accent" | "warning" | "danger";

const checkStatusPresentation: Record<
  ValidationPreviewCheck["status"],
  { label: string; tone: StatusTone; symbol: string }
> = {
  passed: { label: "Пройдено", tone: "accent", symbol: "✓" },
  warning: { label: "Есть замечание", tone: "warning", symbol: "!" },
  failed: { label: "Нужно исправить", tone: "danger", symbol: "!" },
  unavailable: { label: "Недоступно", tone: "neutral", symbol: "—" },
};

function previewStatusTone(status: PreviewStatus | undefined): StatusTone {
  if (status?.code === "passed") return "accent";
  if (status?.code === "warning") return "warning";
  if (status?.code === "failed") return "danger";
  return "neutral";
}

function EmptyPreview({ title, message }: { title: string; message: string }) {
  return (
    <article className={styles.previewPanel}>
      <div className={styles.panelHeading}>
        <h3>{title}</h3>
        <StatusBadge tone="neutral">Нет данных</StatusBadge>
      </div>
      <div className={styles.emptyPattern} aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <p className={styles.emptyCopy}>{message}</p>
    </article>
  );
}

export function ValidationChecks({
  checks,
}: {
  checks: ValidationPreviewCheck[] | undefined;
}) {
  return (
    <section className={styles.checksSection} aria-labelledby="checks-title">
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>Проверки</span>
          <h2 id="checks-title">Результаты проверки</h2>
        </div>
        <p>Статусы и формулировки приходят вместе с результатом проверки.</p>
      </div>

      {checks?.length ? (
        <div className={styles.checkGrid}>
          {checks.map((check) => {
            const presentation = checkStatusPresentation[check.status];
            return (
              <article className={styles.checkItem} key={check.code}>
                <span
                  className={`${styles.checkSymbol} ${styles[`checkSymbol_${check.status}`]}`}
                  aria-hidden="true"
                >
                  {presentation.symbol}
                </span>
                <div>
                  <StatusBadge tone={presentation.tone}>{presentation.label}</StatusBadge>
                  <p>{check.display_text}</p>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className={styles.inlineEmpty}>
          <StatusBadge tone="neutral">Нет данных</StatusBadge>
          <p>Детализация проверок пока недоступна.</p>
        </div>
      )}
    </section>
  );
}

interface BudgetRow {
  label: string;
  total_budget_rub: number;
  max_daily_budget_rub: number;
  status?: PreviewStatus;
}

function BudgetBarChart({
  title,
  rows,
}: {
  title: string;
  rows: BudgetRow[];
}) {
  const maxBudget = Math.max(...rows.map((row) => row.total_budget_rub), 0);
  return (
    <article className={styles.previewPanel} aria-label={title}>
      <div className={styles.panelHeading}>
        <h3>{title}</h3>
        <span className={styles.rowCount}>{rows.length}</span>
      </div>
      <div className={styles.barChart}>
        {rows.map((row) => {
          const width = maxBudget > 0 ? Math.max((row.total_budget_rub / maxBudget) * 100, 2) : 0;
          const barStyle = { "--bar-width": `${width}%` } as CSSProperties;
          return (
            <div className={styles.barRow} key={row.label}>
              <div className={styles.barMeta}>
                <strong>{row.label}</strong>
                <span>{formatRub(row.total_budget_rub)}</span>
              </div>
              <div
                className={styles.barTrack}
                role="img"
                aria-label={`${row.label}: ${formatRub(row.total_budget_rub)}`}
              >
                <span style={barStyle} />
              </div>
              <div className={styles.barFootnote}>
                <span>Максимум за день: {formatRub(row.max_daily_budget_rub)}</span>
                {row.status ? (
                  <StatusBadge tone={previewStatusTone(row.status)}>
                    {row.status.display_text}
                  </StatusBadge>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}

function BudgetPreview({
  byChannel,
  byGeo,
}: {
  byChannel: BudgetByChannelPreview[] | undefined;
  byGeo: BudgetByGeoPreview[] | undefined;
}) {
  return (
    <>
      {byChannel?.length ? (
        <BudgetBarChart
          title="Бюджет по каналам"
          rows={byChannel.map((row) => ({ ...row, label: row.channel }))}
        />
      ) : (
        <EmptyPreview
          title="Бюджет по каналам"
          message="Данные по каналам пока недоступны."
        />
      )}
      {byGeo?.length ? (
        <BudgetBarChart
          title="Бюджет по географиям"
          rows={byGeo.map((row) => ({ ...row, label: row.geo }))}
        />
      ) : (
        <EmptyPreview
          title="Бюджет по географиям"
          message="Данные по географиям пока недоступны."
        />
      )}
    </>
  );
}

interface FlightingGroup {
  channel: string;
  points: Map<string, ChannelFlightingPreview>;
}

function ChannelFlightingChart({ rows }: { rows: ChannelFlightingPreview[] }) {
  const { channels, dates, maximum } = useMemo(() => {
    const byChannel = new Map<string, FlightingGroup>();
    const dateSet = new Set<string>();
    let max = 0;
    for (const row of rows) {
      dateSet.add(row.date);
      max = Math.max(max, row.daily_budget_rub);
      const group = byChannel.get(row.channel) ?? {
        channel: row.channel,
        points: new Map<string, ChannelFlightingPreview>(),
      };
      group.points.set(row.date, row);
      byChannel.set(row.channel, group);
    }
    return {
      channels: [...byChannel.values()].sort((left, right) => left.channel.localeCompare(right.channel, "ru")),
      dates: [...dateSet].sort(),
      maximum: max,
    };
  }, [rows]);

  const timelineStyle = {
    "--timeline-columns": dates.length,
    "--timeline-min-width": `${Math.max(580, 180 + dates.length * 28)}px`,
  } as CSSProperties;

  return (
    <article className={`${styles.previewPanel} ${styles.flightingPanel}`}>
      <div className={styles.panelHeading}>
        <div>
          <h3>Активность каналов</h3>
          <p>{formatDate(dates[0])} — {formatDate(dates[dates.length - 1])}</p>
        </div>
        <StatusBadge tone="neutral">{dates.length} дн.</StatusBadge>
      </div>
      <div className={styles.timelineLegend}>
        <span><i className={styles.legendLow} />Меньше</span>
        <span><i className={styles.legendHigh} />Больше</span>
        <strong>Максимум: {formatRub(maximum)}</strong>
      </div>
      <div className={styles.timelineScroll} tabIndex={0} aria-label="Временная диаграмма активности каналов">
        <div className={styles.timeline} style={timelineStyle} role="table">
          <div className={styles.timelineHeader} role="row">
            <span role="columnheader">Канал</span>
            <div className={styles.timelineDateGrid}>
              {dates.map((date, index) => (
                <span
                  role="columnheader"
                  className={styles.timelineDate}
                  key={date}
                  title={formatDate(date)}
                  aria-label={formatDate(date)}
                >
                  {index === 0 || index === dates.length - 1 || index % 7 === 0
                    ? new Date(`${date}T00:00:00`).getDate()
                    : ""}
                </span>
              ))}
            </div>
          </div>
          {channels.map((group) => (
            <div className={styles.timelineRow} role="row" key={group.channel}>
              <div className={styles.timelineChannel} role="rowheader">
                <strong>{group.channel}</strong>
              </div>
              <div className={styles.timelineCellGrid}>
                {dates.map((date) => {
                  const point = group.points.get(date);
                  const strength = point && point.daily_budget_rub > 0 && maximum > 0
                    ? Math.round(18 + (point.daily_budget_rub / maximum) * 82)
                    : 0;
                  const cellStyle = { "--cell-strength": `${strength}%` } as CSSProperties;
                  const status = point?.status?.display_text;
                  const label = point
                    ? `${group.channel}, ${formatDate(date)}: ${formatRub(point.daily_budget_rub)}${status ? `. Статус: ${status}` : ""}`
                    : `${group.channel}, ${formatDate(date)}: данных нет`;
                  return (
                    <span
                      role="cell"
                      className={
                        !point
                          ? styles.timelineCellEmpty
                          : point.daily_budget_rub > 0
                            ? styles.timelineCell
                            : styles.timelineCellZero
                      }
                      style={cellStyle}
                      key={date}
                      title={label}
                      aria-label={label}
                    />
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
      <details className={styles.timelineDetails}>
        <summary>Точные значения по дням</summary>
        <div className={styles.timelineTableScroll}>
          <table>
            <thead>
              <tr>
                <th scope="col">Канал</th>
                <th scope="col">Дата</th>
                <th scope="col">Бюджет</th>
                <th scope="col">Статус</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((point, index) => (
                <tr key={`${point.channel}-${point.date}-${index}`}>
                  <th scope="row">{point.channel}</th>
                  <td>{formatDate(point.date)}</td>
                  <td>{formatRub(point.daily_budget_rub)}</td>
                  <td>{point.status?.display_text ?? "Нет данных"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </article>
  );
}

export function CampaignPreviewVisuals({ preview }: { preview: ValidationPreview | undefined }) {
  return (
    <section className={styles.previews} aria-labelledby="preview-title">
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>Предпросмотр медиаплана</span>
          <h2 id="preview-title">Структура кампании</h2>
        </div>
        <p>Показываем готовые данные из результата проверки без пересчета в браузере.</p>
      </div>
      <div className={styles.previewGrid}>
        <BudgetPreview
          byChannel={preview?.budget_by_channel}
          byGeo={preview?.budget_by_geo}
        />
        {preview?.channel_flighting?.length ? (
          <ChannelFlightingChart rows={preview.channel_flighting} />
        ) : (
          <EmptyPreview
            title="Активность каналов"
            message="Дневная активность каналов пока недоступна."
          />
        )}
        <EmptyPreview
          title="География кампании"
          message="Данные для карты пока недоступны."
        />
      </div>
    </section>
  );
}
