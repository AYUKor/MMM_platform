import { Link } from "react-router-dom";
import type { CampaignCardV1, Range } from "../../shared/api/generated/campaign-card-v1";
import {
  SHORT_CHANNEL_NAMES,
  basketBelowKopeck,
  formatCount,
  formatMln,
  formatPeriod,
  formatShare,
  geographyLabel,
  measureFormat,
  plural,
  trackGeometry,
  type Measure,
} from "./campaignCatalogModel";
import styles from "./campaign-catalog.module.css";

interface CampaignCardViewProps {
  card: CampaignCardV1;
  backLink: string;
}

function BackIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15 6l-6 6 6 6" />
    </svg>
  );
}

interface MetricProps {
  title: string;
  value: Range;
  unit: string;
  measure: Measure;
  reference: number | null;
  referenceLabel?: string;
  rangeNote?: string | null;
}

function Metric({ title, value, unit, measure, reference, referenceLabel, rangeNote = null }: MetricProps) {
  const geometry = trackGeometry(value, reference);
  const format = measureFormat(measure, value);
  return (
    <section className={`${styles.panel} ${styles.metric}`}>
      <h2>{title}</h2>
      <div className={styles.metricValue}>{format(value.estimate)}</div>
      <div className={styles.metricUnit}>{unit}</div>
      <div className={styles.rangeValues}>
        {rangeNote ? <span>{rangeNote}</span> : (
          <>
            <span>от <b>{format(value.low)}</b></span>
            <span>до <b>{format(value.high)}</b></span>
          </>
        )}
      </div>
      <div className={styles.track} aria-hidden="true">
        <i className={styles.trackRange} style={{ left: `${geometry.left}%`, width: `${geometry.width}%` }} />
        <i className={styles.trackDot} style={{ left: `${geometry.dot}%` }} />
        {geometry.reference !== null ? (
          <i className={styles.trackReference} style={{ left: `${geometry.reference}%` }}><b>{referenceLabel}</b></i>
        ) : null}
      </div>
    </section>
  );
}

export function CampaignCardView({ card, backLink }: CampaignCardViewProps) {
  const item = card.campaign;
  const computed = item.status === "computed";
  const nationwide = item.channels.filter((row) => row.nationwide).map((row) => SHORT_CHANNEL_NAMES[row.channel_id]);
  const explain = card.notes.filter((note) => ["roas_industry_level", "campaign_effect_leave_one_out", "range_p10_p90"].includes(note.code));

  return (
    <section className={styles.page} aria-labelledby="campaign-card-title">
      <Link className={styles.back} to={backLink}>
        <BackIcon />
        Все кампании
      </Link>

      <header className={styles.hero}>
        <span className={styles.contour} aria-hidden="true" />
        <div className={styles.heroCopy}>
          <div className={styles.eyebrow}>Кампания № {item.number}</div>
          <h1 id="campaign-card-title">{item.name}</h1>
          <div className={styles.heroChips}>
            <span className={styles.heroChip}>{item.directions.join(", ")}</span>
            <span className={styles.heroChip}>{formatPeriod(item.start_date, item.end_date)}</span>
            <span className={styles.heroChip}>{formatCount(item.days_n, "день", "дня", "дней")}</span>
            <span className={styles.heroChip}>{geographyLabel(item)}</span>
            <span className={styles.heroChip}>{formatCount(item.channels.length, "канал", "канала", "каналов")}</span>
          </div>
        </div>
        <div className={`${styles.reliabilityTile} ${item.reliable === 1 ? styles.reliabilityOk : styles.reliabilityCaution}`}>
          <b>Надёжность</b>
          <div className={styles.reliabilityValue}>{item.reliable}</div>
          <span>{item.reliable === 1 ? "Оценке можно доверять" : "Смотреть с осторожностью"}</span>
        </div>
      </header>

      {computed && item.turnover_increment_rub && item.orders_per_1000_buyers && item.avg_basket_increment_rub && item.roas ? (
        <div className={styles.metrics}>
          <Metric
            title="Оборот, прирост"
            value={item.turnover_increment_rub}
            unit="млн ₽"
            measure="mln"
            reference={null}
          />
          <Metric
            title="Заказы, прирост"
            value={item.orders_per_1000_buyers}
            unit="на 1000 покупателей"
            measure="orders"
            reference={0}
            referenceLabel="0"
          />
          <Metric
            title="Средний чек, прирост"
            value={item.avg_basket_increment_rub}
            unit="₽ к среднему чеку"
            measure="basket"
            reference={0}
            referenceLabel="0"
            rangeNote={basketBelowKopeck(item.avg_basket_increment_rub) ? "меньше копейки в любую сторону" : null}
          />
          <Metric
            title="ROAS"
            value={item.roas}
            unit={`оборот ÷ бюджет ${formatMln(item.budget_rub)} млн ₽`}
            measure="roas"
            reference={1}
            referenceLabel="1,0"
          />
        </div>
      ) : (
        <div className={`${styles.panel} ${styles.notComputed}`} role="status">
          <strong>Нет оценки эффекта</strong>
          <p>{item.status_display_text}</p>
        </div>
      )}

      <div className={styles.cardGrid}>
        <section className={`${styles.panel} ${styles.section}`} aria-labelledby="campaign-channels-title">
          <div className={styles.sectionHead}>
            <h2 id="campaign-channels-title">Каналы и бюджет</h2>
            <span>млн ₽</span>
          </div>
          <div>
            <div className={styles.channelHead} aria-hidden="true">
              <span>Канал</span>
              <span>Доля бюджета</span>
              <span className={styles.right}>Бюджет</span>
              <span className={styles.right}>Доля</span>
            </div>
            {item.channels.map((row) => {
              const share = item.budget_rub > 0 ? row.budget_rub / item.budget_rub : 0;
              return (
                <div className={styles.channelRow} key={row.channel_id}>
                  <div className={styles.channelName}>
                    {row.display_name}
                    {row.nationwide ? <small>вся страна</small> : null}
                  </div>
                  <div className={styles.shareBar} aria-hidden="true"><i style={{ width: `${share * 100}%` }} /></div>
                  <div className={styles.channelSum}>{formatMln(row.budget_rub)}</div>
                  <div className={styles.channelShare}>{formatShare(share)}</div>
                </div>
              );
            })}
          </div>
          <div className={styles.channelTotal}>
            <span>Бюджет кампании</span>
            <span className={styles.num}>{formatMln(item.budget_rub)}</span>
          </div>
        </section>

        <div className={styles.sideColumn}>
          <section className={`${styles.panel} ${styles.section}`} aria-labelledby="campaign-cities-title">
            <div className={styles.sectionHead}>
              <h2 id="campaign-cities-title">География</h2>
              <span>{geographyLabel(item)}</span>
            </div>
            <div className={styles.cities}>
              {item.cities.map((city) => <span className={styles.city} key={city}>{city}</span>)}
              {nationwide.length ? <span className={`${styles.city} ${styles.cityNationwide}`}>Вся страна · {nationwide.join(", ")}</span> : null}
            </div>
          </section>
          <section className={`${styles.panel} ${styles.section}`} aria-labelledby="campaign-overlaps-title">
            <div className={styles.sectionHead}>
              <h2 id="campaign-overlaps-title">Пересечения</h2>
            </div>
            <div className={styles.overlapBig}>
              <b>{item.overlaps_n}</b>
              <span>
                {item.overlaps_n === 0
                  ? "других кампаний того же направления в те же дни и города не было"
                  : `${plural(item.overlaps_n, "кампания", "кампании", "кампаний")} того же направления ${item.overlaps_n % 10 === 1 && item.overlaps_n % 100 !== 11 ? "шла" : "шли"} в те же дни и города`}
              </span>
            </div>
          </section>
        </div>
      </div>

      {explain.length ? (
        <section className={`${styles.panel} ${styles.explain}`} aria-labelledby="campaign-explain-title">
          <h2 id="campaign-explain-title">Как читать оценку · {card.roas_level_label}</h2>
          <ul>
            {explain.map((note) => <li key={note.code}>{note.display_text}</li>)}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
