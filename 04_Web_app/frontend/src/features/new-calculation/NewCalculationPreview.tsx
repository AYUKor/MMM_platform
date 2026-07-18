import { useMemo, type CSSProperties } from "react";
import type {
  BudgetByChannelPreview,
  BudgetByGeoPreview,
  ChannelFlightingPreview,
  PreviewStatus,
  ValidationPreview,
  ValidationPreviewCheck,
} from "../../entities/lifecycle/types";
import type { ValidationResultV2 } from "../../shared/api/generated/validation-result-v2";
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

function validationTone(status: ValidationResultV2["file_validation"]["status"]): StatusTone {
  if (status === "passed") return "accent";
  if (status === "warning") return "warning";
  if (status === "failed") return "danger";
  return "neutral";
}

function validationStatusLabel(status: ValidationResultV2["file_validation"]["status"]): string {
  if (status === "passed") return "Пройдено";
  if (status === "warning") return "Нужна проверка";
  if (status === "failed") return "Нужно исправить";
  return "Нет данных";
}

function limitationTone(
  severity: ValidationResultV2["model_limitations"][number]["severity"],
): StatusTone {
  if (severity === "blocking") return "danger";
  if (severity === "manual_review" || severity === "warning") return "warning";
  return "neutral";
}

function limitationTypeLabel(
  limitation: ValidationResultV2["model_limitations"][number],
): string {
  if (limitation.blocks_calculation || limitation.severity === "blocking") return "За пределами доступного расчета";
  if (limitation.allowed_use === "unsupported") return "Канал вне области применения";
  if (limitation.allowed_use === "diagnostic") return "Только диагностическое использование";
  if (limitation.allowed_use === "unavailable") return "Оценка недоступна";
  if (limitation.allowed_use === "caution" || limitation.severity === "manual_review") return "Требуется осторожная интерпретация";
  return "Допустимое применение модели";
}

export function BusinessValidationReview({ validation }: { validation: ValidationResultV2 }) {
  const ready = validation.job_creation_allowed && validation.file_validation.status !== "failed";
  const fileFailed = validation.file_validation.status === "failed";
  const unavailable = validation.file_validation.status === "unavailable" || validation.status === "unavailable";
  const lead = ready
    ? {
      title: "Кампания готова к расчету",
      description: "Файл прочитан. Ограничения модели будут учтены при расчете.",
      badge: "Можно продолжить",
      tone: "accent" as const,
    }
    : fileFailed
      ? {
        title: "Файл нужно исправить",
        description: "Исправьте ошибки файла и запустите проверку повторно.",
        badge: "Расчет недоступен",
        tone: "danger" as const,
      }
      : unavailable
        ? {
          title: "Результат проверки пока недоступен",
          description: "Сервис не опубликовал достаточные сведения. Повторите проверку позже.",
          badge: "Нет данных",
          tone: "neutral" as const,
        }
        : {
          title: "Расчет ограничен возможностями модели",
          description: "Файл прочитан, но ограничения модели пока не позволяют запустить расчет.",
          badge: "Нужна ручная проверка",
          tone: "warning" as const,
        };
  const leadClass = ready
    ? styles.validationLeadReady
    : lead.tone === "danger"
      ? styles.validationLeadBlocked
      : lead.tone === "warning"
        ? styles.validationLeadWarning
        : styles.validationLeadNeutral;
  return (
    <div className={styles.businessValidation}>
      <section className={`${styles.validationLead} ${leadClass}`}>
        <div>
          <span className={styles.eyebrow}>Результат проверки</span>
          <h2>{lead.title}</h2>
          <p>{lead.description}</p>
        </div>
        <StatusBadge tone={lead.tone}>{lead.badge}</StatusBadge>
      </section>

      <section className={styles.fileValidationSection} aria-labelledby="file-validation-title">
        <div className={styles.sectionHeading}>
          <div><span className={styles.eyebrow}>Входные данные</span><h2 id="file-validation-title">Проверка файла</h2></div>
          <StatusBadge tone={validationTone(validation.file_validation.status)}>
            {validationStatusLabel(validation.file_validation.status)}
          </StatusBadge>
        </div>
        <dl className={styles.validationFacts}>
          <div><dt>Строк</dt><dd>{validation.file_validation.rows_n}</dd></div>
          <div><dt>Кампаний</dt><dd>{validation.file_validation.campaigns_n}</dd></div>
          <div><dt>Географий</dt><dd>{validation.file_validation.geographies_n}</dd></div>
          <div><dt>Каналов</dt><dd>{validation.file_validation.channels_n}</dd></div>
          <div><dt>Запрошенный бюджет</dt><dd>{formatRub(validation.file_validation.requested_budget_rub)}</dd></div>
          <div><dt>Создание расчета</dt><dd>{validation.job_creation_allowed ? "Разрешено" : "Недоступно"}</dd></div>
        </dl>
        {validation.file_validation.checks.length > 0 ? (
          <div className={styles.compactChecks}>
            {validation.file_validation.checks.map((check) => (
              <article key={check.code}>
                <StatusBadge tone={validationTone(check.status)}>{validationStatusLabel(check.status)}</StatusBadge>
                <p>{check.display_text}</p>
              </article>
            ))}
          </div>
        ) : (
          <div className={styles.inlineEmpty}><StatusBadge tone="neutral">Нет данных</StatusBadge><p>Детализация проверки файла недоступна.</p></div>
        )}
      </section>

      <section className={styles.modelLimitationsSection} aria-labelledby="model-limitations-title">
        <div className={styles.sectionHeading}>
          <div><span className={styles.eyebrow}>Границы применения</span><h2 id="model-limitations-title">Ограничения модели</h2></div>
          <span className={styles.rowCount}>{validation.model_limitations.length}</span>
        </div>
        {validation.model_limitations.length === 0 ? (
          <div className={styles.inlineEmpty}><StatusBadge tone="accent">Нет ограничений</StatusBadge><p>Дополнительные ограничения для этой кампании не опубликованы.</p></div>
        ) : (
          <div className={styles.limitationList}>
            {validation.model_limitations.map((limitation, index) => (
              <article key={`${limitation.channel_id}-${limitation.limitation_type}-${index}`}>
                <header>
                  <div><span>Оборот · {limitation.channel_display_name}</span><h3>{limitation.what}</h3></div>
                  <StatusBadge tone={limitationTone(limitation.severity)}>
                    {limitation.blocks_calculation ? "Блокирует расчет" : "Будет учтено"}
                  </StatusBadge>
                </header>
                <dl>
                  <div><dt>Тип ограничения</dt><dd>{limitationTypeLabel(limitation)}</dd></div>
                  <div><dt>Затронуто географий</dt><dd>{limitation.affected_geos_n}</dd></div>
                  <div><dt>Почему это важно</dt><dd>{limitation.why}</dd></div>
                  <div><dt>Что можно сделать</dt><dd>{limitation.recommended_action}</dd></div>
                </dl>
                <details>
                  <summary>Показать географии ({limitation.affected_geos_n})</summary>
                  <ul>{limitation.affected_geos.map((geo) => <li key={geo}>{geo}</li>)}</ul>
                </details>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className={styles.geoReadinessSection} aria-labelledby="validation-geos-title">
        <div className={styles.sectionHeading}>
          <div><span className={styles.eyebrow}>Географии кампании</span><h2 id="validation-geos-title">{validation.geo_points.length} географий сохранены</h2></div>
        </div>
        <div className={styles.geoList}>
          {validation.geo_points.map((geo) => (
            <article key={geo.geo_id}>
              <strong>{geo.geo_display_name}</strong>
              <span>{formatRub(geo.budget_rub)}</span>
              <small>{geo.channels.map((channel) => channel.channel_display_name).join(", ")}</small>
            </article>
          ))}
        </div>
        <div className={styles.mapUnavailable} role="status">
          <strong>Карта пока недоступна</strong>
          <span>Карта будет доступна после подключения утвержденного справочника координат.</span>
        </div>
      </section>
    </div>
  );
}
