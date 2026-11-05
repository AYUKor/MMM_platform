import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Campaign, CampaignCatalogV1, Range } from "../../shared/api/generated/campaign-catalog-v1";
import {
  CHANNEL_OPTIONS,
  DEFAULT_FILTERS,
  DIRECTION_OPTIONS,
  SORT_OPTIONS,
  citiesLine,
  filterCampaigns,
  formatCount,
  formatDay,
  formatMln,
  formatPeriod,
  formatRoas,
  formatSigned,
  miniRoasGeometry,
  shortChannels,
  tabCounts,
  type CatalogFilters,
  type CatalogSort,
  type ChannelId,
  type Direction,
  type DurationTab,
  type ReliabilityFilter,
} from "./campaignCatalogModel";
import styles from "./campaign-catalog.module.css";

interface CampaignCatalogViewProps {
  catalog: CampaignCatalogV1;
  filters: CatalogFilters;
  onFiltersChange: (filters: CatalogFilters) => void;
  canDownload: boolean;
  downloadUrl: string;
  cardLink: (number: number) => string;
  onOpen: (number: number) => void;
}

const TABS: readonly { id: DurationTab; label: string }[] = [
  { id: "short", label: "До 120 дней" },
  { id: "long", label: "Длиннее 120 дней" },
];

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </svg>
  );
}

export function ReliabilityPill({ value }: { value: 0 | 1 }) {
  return (
    <span
      className={`${styles.reliability} ${value === 1 ? styles.reliable1 : styles.reliable0}`}
      title={value === 1 ? "Оценке можно доверять" : "Смотреть с осторожностью"}
    >
      {value}
    </span>
  );
}

function CitiesText({ item, search }: { item: Campaign; search: string }) {
  const line = citiesLine(item, search);
  const parts: ReactNode[] = line.shown.map((city, index) => (
    <span key={city.name}>
      {index > 0 ? ", " : null}
      {city.hit ? <mark className={styles.hit}>{city.name}</mark> : city.name}
    </span>
  ));
  return (
    <div className={styles.citiesLine} title={item.cities.join(", ") || undefined}>
      <span className={styles.citiesLabel}>Города:</span>{" "}
      {parts}
      {line.rest > 0 ? ` и ещё ${line.rest}` : null}
      {line.nationwide ? `${line.shown.length ? " · " : ""}${line.nationwide}` : null}
      {!line.shown.length && !line.nationwide ? "нет" : null}
    </div>
  );
}

function RangeCell({ value, format, mini = false }: { value: Range | null; format: (number: number) => string; mini?: boolean }) {
  if (value === null) {
    return <td className={styles.right}><span className={styles.noEstimate}>нет оценки</span></td>;
  }
  const geometry = mini ? miniRoasGeometry(value) : null;
  return (
    <td className={styles.right}>
      <span className={styles.value}>{format(value.estimate)}</span>
      <span className={styles.range}>{format(value.low)} … {format(value.high)}</span>
      {geometry ? (
        <span className={styles.mini} aria-hidden="true">
          <i className={styles.trackRange} style={{ left: `${geometry.left}%`, width: `${geometry.width}%` }} />
          <i className={styles.trackReference} style={{ left: `${geometry.reference}%` }} />
          <i className={styles.trackDot} style={{ left: `${geometry.dot}%` }} />
        </span>
      ) : null}
    </td>
  );
}

const mln = (value: number) => formatMln(value);
const signed = (value: number) => formatSigned(value, 1);

function CampaignRow({ item, search, cardLink, onOpen }: { item: Campaign; search: string; cardLink: string; onOpen: () => void }) {
  return (
    <tr onClick={(event) => { if (!(event.target as HTMLElement).closest("a")) onOpen(); }}>
      <td>
        <span className={styles.number}>№ {item.number}</span>
        <Link className={styles.name} to={cardLink}>{item.name}</Link>
        <div className={styles.sub}>{item.directions.join(", ")} · {formatPeriod(item.start_date, item.end_date)}</div>
        <div className={styles.chips}>{shortChannels(item).map((name) => <span className={styles.chip} key={name}>{name}</span>)}</div>
        <CitiesText item={item} search={search} />
      </td>
      <td className={styles.right}><span className={styles.value}>{formatMln(item.budget_rub)}</span></td>
      <RangeCell value={item.turnover_increment_rub} format={mln} />
      <RangeCell value={item.orders_per_1000_buyers} format={signed} />
      <RangeCell value={item.avg_basket_increment_rub} format={signed} />
      <RangeCell value={item.roas} format={formatRoas} mini />
      <td className={styles.center}><span className={styles.value}>{item.overlaps_n}</span></td>
      <td className={styles.center}><ReliabilityPill value={item.reliable} /></td>
    </tr>
  );
}

function CampaignMobileCard({ item, search, cardLink, onOpen }: { item: Campaign; search: string; cardLink: string; onOpen: () => void }) {
  return (
    <article
      className={`${styles.panel} ${styles.mobileCard}`}
      onClick={(event) => { if (!(event.target as HTMLElement).closest("a")) onOpen(); }}
    >
      <div className={styles.mobileCardTop}>
        <div>
          <span className={styles.number}>№ {item.number}</span>
          <Link className={styles.name} to={cardLink}>{item.name}</Link>
          <div className={styles.sub}>{item.directions.join(", ")} · {formatPeriod(item.start_date, item.end_date)}</div>
        </div>
        <ReliabilityPill value={item.reliable} />
      </div>
      <div className={styles.chips}>{shortChannels(item).map((name) => <span className={styles.chip} key={name}>{name}</span>)}</div>
      <CitiesText item={item} search={search} />
      <div className={styles.mobileGrid}>
        <div><span>Бюджет, млн ₽</span><b>{formatMln(item.budget_rub)}</b></div>
        <div><span>Оборот, млн ₽</span><b>{item.turnover_increment_rub ? formatMln(item.turnover_increment_rub.estimate) : "нет оценки"}</b></div>
        <div><span>ROAS</span><b>{item.roas ? formatRoas(item.roas.estimate) : "нет оценки"}</b></div>
        <div><span>Пересечения</span><b>{item.overlaps_n}</b></div>
      </div>
    </article>
  );
}

export function CampaignCatalogView({
  catalog,
  filters,
  onFiltersChange,
  canDownload,
  downloadUrl,
  cardLink,
  onOpen,
}: CampaignCatalogViewProps) {
  const summary = catalog.summary;
  const rows = filterCampaigns(catalog.campaigns, filters);
  const counts = tabCounts(catalog.campaigns);
  const update = (patch: Partial<CatalogFilters>) => onFiltersChange({ ...filters, ...patch });
  const download = catalog.download;
  const footNotes = catalog.notes.filter((note) => ["reliability_flag", "overlaps", "range_p10_p90"].includes(note.code));

  return (
    <section className={styles.page} aria-labelledby="campaign-catalog-title">
      <header className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Каталог</div>
          <h1 id="campaign-catalog-title">Кампании прошлых периодов</h1>
          <p className={styles.meta}>
            <span>Модель «{catalog.model_display_name}»</span>
            {catalog.period_end ? <span>Данные по {formatDay(catalog.period_end)}</span> : null}
            {summary ? (
              <span>
                {formatCount(summary.campaigns_n, "кампания", "кампании", "кампаний")}, оценка есть у {summary.computed_n}
              </span>
            ) : null}
            {summary?.weighted_roas != null ? <span>ROAS всех кампаний {formatRoas(summary.weighted_roas)}</span> : null}
            {catalog.roas_level_label ? <span className={styles.levelLabel}>{catalog.roas_level_label}</span> : null}
          </p>
        </div>
        {canDownload && download ? (
          <div className={styles.pageActions}>
            <a className={styles.downloadButton} href={downloadUrl} download={download.file_name}>
              Скачать Excel <small>{formatCount(download.sheets.length, "лист", "листа", "листов")}</small>
            </a>
          </div>
        ) : null}
      </header>

      <div className={styles.tabs} role="tablist" aria-label="Длительность кампании">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            className={styles.tab}
            aria-selected={filters.tab === tab.id}
            onClick={() => update({ tab: tab.id })}
          >
            {tab.label} <span className={styles.tabCount}>{counts[tab.id]}</span>
          </button>
        ))}
      </div>

      <div className={styles.toolbar}>
        <label className={styles.search}>
          <SearchIcon />
          <input
            type="search"
            aria-label="Поиск кампании"
            placeholder="Название, город или канал"
            value={filters.search}
            autoComplete="off"
            maxLength={120}
            onChange={(event) => update({ search: event.target.value })}
          />
        </label>
        <label className={styles.field}>
          Направление
          <select
            value={filters.direction ?? ""}
            onChange={(event) => update({ direction: (event.target.value || null) as Direction | null })}
          >
            <option value="">Все</option>
            {DIRECTION_OPTIONS.map((direction) => <option key={direction} value={direction}>{direction}</option>)}
          </select>
        </label>
        <label className={styles.field}>
          Канал
          <select
            value={filters.channel ?? ""}
            onChange={(event) => update({ channel: (event.target.value || null) as ChannelId | null })}
          >
            <option value="">Все</option>
            {CHANNEL_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <div className={styles.field}>
          Надёжность
          <div className={styles.segmented} role="group" aria-label="Надёжность">
            {(["all", "1", "0"] as ReliabilityFilter[]).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={filters.reliability === value}
                onClick={() => update({ reliability: value })}
              >
                {value === "all" ? "Все" : value}
              </button>
            ))}
          </div>
        </div>
        <label className={styles.field}>
          Порядок
          <select value={filters.sort} onChange={(event) => update({ sort: event.target.value as CatalogSort })}>
            {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
      </div>

      <p className={styles.count} role="status" aria-live="polite">
        Показано {rows.length} из {counts[filters.tab]}
      </p>

      {rows.length === 0 ? (
        <div className={`${styles.panel} ${styles.empty}`}>
          <strong>Ничего не найдено</strong>
          <span>Измените запрос или сбросьте фильтры.</span>
          <button className={styles.secondaryButton} type="button" onClick={() => onFiltersChange({ ...DEFAULT_FILTERS, tab: filters.tab })}>
            Сбросить фильтры
          </button>
        </div>
      ) : (
        <>
          <div className={`${styles.panel} ${styles.tableWrap}`}>
            <table className={styles.table}>
              <caption className="sr-only">Кампании прошлых периодов</caption>
              <thead>
                <tr>
                  <th scope="col">Кампания</th>
                  <th scope="col" className={styles.right}>Бюджет<small>млн ₽</small></th>
                  <th scope="col" className={styles.right}>Оборот<small>млн ₽</small></th>
                  <th scope="col" className={styles.right}>Заказы<small>на 1000 покупателей</small></th>
                  <th scope="col" className={styles.right}>Средний чек<small>₽</small></th>
                  <th scope="col" className={styles.right}>ROAS</th>
                  <th scope="col" className={styles.center}>Пересечения</th>
                  <th scope="col" className={styles.center}>Надёжность</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => (
                  <CampaignRow
                    key={item.number}
                    item={item}
                    search={filters.search}
                    cardLink={cardLink(item.number)}
                    onOpen={() => onOpen(item.number)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className={styles.mobileCards}>
            {rows.map((item) => (
              <CampaignMobileCard
                key={item.number}
                item={item}
                search={filters.search}
                cardLink={cardLink(item.number)}
                onOpen={() => onOpen(item.number)}
              />
            ))}
          </div>
        </>
      )}

      {footNotes.length ? (
        <ul className={styles.notes}>
          {footNotes.map((note) => <li key={note.code}>{note.display_text}</li>)}
        </ul>
      ) : null}
    </section>
  );
}

export function CampaignCatalogUnpublished({ displayText }: { displayText: string }) {
  return (
    <section className={styles.page} aria-labelledby="campaign-catalog-title">
      <header className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Каталог</div>
          <h1 id="campaign-catalog-title">Кампании прошлых периодов</h1>
        </div>
      </header>
      <div className={`${styles.panel} ${styles.statePanel}`} role="status">
        <h2>Каталог пока не опубликован</h2>
        <p>{displayText}</p>
        <p>Он появится здесь после публикации для активной модели.</p>
      </div>
    </section>
  );
}
