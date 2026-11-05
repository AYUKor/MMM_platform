import type { Campaign, Range } from "../../shared/api/generated/campaign-catalog-v1";
import {
  CAMPAIGN_CHANNEL_DISPLAY_NAMES,
  CAMPAIGN_DIRECTIONS,
} from "../../shared/api/campaign-catalog-client";

export type ChannelId = Campaign["main_channel_id"];
export type Direction = (typeof CAMPAIGN_DIRECTIONS)[number];
export type DurationTab = "short" | "long";
export type ReliabilityFilter = "all" | "1" | "0";
export type CatalogSort = "new" | "old" | "turnover" | "roas" | "budget";

export interface CatalogFilters {
  tab: DurationTab;
  search: string;
  direction: Direction | null;
  channel: ChannelId | null;
  reliability: ReliabilityFilter;
  sort: CatalogSort;
}

export const DEFAULT_FILTERS: CatalogFilters = {
  tab: "short",
  search: "",
  direction: null,
  channel: null,
  reliability: "all",
  sort: "new",
};

export const SORT_OPTIONS: readonly { value: CatalogSort; label: string }[] = [
  { value: "new", label: "Новые сверху" },
  { value: "old", label: "Старые сверху" },
  { value: "turnover", label: "По обороту" },
  { value: "roas", label: "По ROAS" },
  { value: "budget", label: "По бюджету" },
];

export const SHORT_CHANNEL_NAMES: Readonly<Record<ChannelId, string>> = {
  Digital_Performance: "Цифровая",
  OOH_Total: "Наружная",
  Indoor: "Indoor",
  "Радио": "Радио",
  "Нац_ТВ": "Нац. ТВ",
  "Рег_ТВ": "Рег. ТВ",
};

export const CHANNEL_OPTIONS: readonly { value: ChannelId; label: string }[] = (
  Object.keys(CAMPAIGN_CHANNEL_DISPLAY_NAMES) as ChannelId[]
).map((value) => ({ value, label: CAMPAIGN_CHANNEL_DISPLAY_NAMES[value] }));

export const DIRECTION_OPTIONS: readonly Direction[] = CAMPAIGN_DIRECTIONS;

const SORTS: ReadonlySet<string> = new Set(SORT_OPTIONS.map((item) => item.value));
const CHANNEL_IDS: ReadonlySet<string> = new Set(Object.keys(CAMPAIGN_CHANNEL_DISPLAY_NAMES));
const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const fixed = (digits: number) => new Intl.NumberFormat("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const F0 = fixed(0);
const F1 = fixed(1);
const F2 = fixed(2);

/* ------------------------------------------------------------------ filters in the address bar */

export function filtersFromSearch(params: URLSearchParams): CatalogFilters {
  const direction = params.get("direction");
  const channel = params.get("channel");
  const reliability = params.get("reliable");
  const sort = params.get("sort");
  return {
    tab: params.get("tab") === "long" ? "long" : "short",
    search: (params.get("q") ?? "").slice(0, 120),
    direction: direction && (CAMPAIGN_DIRECTIONS as readonly string[]).includes(direction) ? direction as Direction : null,
    channel: channel && CHANNEL_IDS.has(channel) ? channel as ChannelId : null,
    reliability: reliability === "1" || reliability === "0" ? reliability : "all",
    sort: sort && SORTS.has(sort) ? sort as CatalogSort : "new",
  };
}

export function filtersToSearch(filters: CatalogFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.tab !== DEFAULT_FILTERS.tab) params.set("tab", filters.tab);
  if (filters.search.trim()) params.set("q", filters.search);
  if (filters.direction) params.set("direction", filters.direction);
  if (filters.channel) params.set("channel", filters.channel);
  if (filters.reliability !== "all") params.set("reliable", filters.reliability);
  if (filters.sort !== DEFAULT_FILTERS.sort) params.set("sort", filters.sort);
  return params;
}

/* ------------------------------------------------------------------ list */

export function isLong(item: Campaign): boolean {
  return item.duration_group === "120_days_and_longer";
}

function normalized(value: string): string {
  return value.toLocaleLowerCase("ru-RU").replace(/ё/g, "е").trim();
}

export function searchText(item: Campaign): string {
  return normalized([
    item.name,
    String(item.number),
    item.directions.join(" "),
    item.cities.join(" "),
    item.channels.map((row) => `${row.display_name} ${SHORT_CHANNEL_NAMES[row.channel_id]}`).join(" "),
    item.nationwide_channels.length ? "вся страна" : "",
  ].join(" "));
}

export function matchesSearch(item: Campaign, search: string): boolean {
  const query = normalized(search).replace(/^№\s*/, "");
  if (!query) return true;
  if (/^\d+$/.test(query)) return String(item.number) === query || searchText(item).includes(query);
  return searchText(item).includes(query);
}

function estimate(value: Range | null): number {
  return value === null ? Number.NEGATIVE_INFINITY : value.estimate;
}

export function filterCampaigns(campaigns: readonly Campaign[], filters: CatalogFilters): Campaign[] {
  const rows = campaigns.filter((item) =>
    isLong(item) === (filters.tab === "long")
    && matchesSearch(item, filters.search)
    && (filters.direction === null || (item.directions as readonly string[]).includes(filters.direction))
    && (filters.channel === null || item.channels.some((row) => row.channel_id === filters.channel))
    && (filters.reliability === "all" || String(item.reliable) === filters.reliability));
  const byNumber = (left: Campaign, right: Campaign) => right.number - left.number;
  const compare: Record<CatalogSort, (left: Campaign, right: Campaign) => number> = {
    new: (left, right) => right.start_date.localeCompare(left.start_date) || byNumber(left, right),
    old: (left, right) => left.start_date.localeCompare(right.start_date) || -byNumber(left, right),
    turnover: (left, right) => estimate(right.turnover_increment_rub) - estimate(left.turnover_increment_rub) || byNumber(left, right),
    roas: (left, right) => estimate(right.roas) - estimate(left.roas) || byNumber(left, right),
    budget: (left, right) => right.budget_rub - left.budget_rub || byNumber(left, right),
  };
  return rows.sort(compare[filters.sort]);
}

export function tabCounts(campaigns: readonly Campaign[]): Record<DurationTab, number> {
  const long = campaigns.filter(isLong).length;
  return { short: campaigns.length - long, long };
}

/* ------------------------------------------------------------------ text */

export function plural(value: number, one: string, few: string, many: string): string {
  const hundred = Math.abs(value) % 100;
  const ten = hundred % 10;
  if (hundred > 10 && hundred < 20) return many;
  if (ten === 1) return one;
  if (ten >= 2 && ten <= 4) return few;
  return many;
}

function day(value: string): number { return Number(value.slice(8, 10)); }
function month(value: string): string { return MONTHS[Number(value.slice(5, 7)) - 1] ?? ""; }
function year(value: string): string { return value.slice(0, 4); }

export function formatDay(value: string): string {
  return `${day(value)} ${month(value)} ${year(value)}`;
}

export function formatPeriod(start: string, end: string): string {
  return year(start) === year(end)
    ? `${day(start)} ${month(start)} – ${day(end)} ${month(end)} ${year(end)}`
    : `${day(start)} ${month(start)} ${year(start)} – ${day(end)} ${month(end)} ${year(end)}`;
}

export function formatMln(value: number): string {
  return F1.format(value / 1e6);
}

export function formatSigned(value: number, digits = 1): string {
  const formatter = digits === 2 ? F2 : digits === 0 ? F0 : F1;
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return formatter.format(0);
  return `${rounded > 0 ? "+" : "−"}${formatter.format(Math.abs(rounded))}`;
}

export function formatRoas(value: number): string {
  return F2.format(value);
}

export function formatShare(value: number): string {
  return `${F0.format(value * 100)}%`;
}

export function formatCount(value: number, one: string, few: string, many: string): string {
  return `${F0.format(value)} ${plural(value, one, few, many)}`;
}

export function shortChannels(item: Campaign): string[] {
  return item.channels.map((row) => SHORT_CHANNEL_NAMES[row.channel_id]);
}

export interface CitiesLine {
  shown: { name: string; hit: boolean }[];
  rest: number;
  nationwide: string | null;
}

/** First four cities (a searched city first), the rest as a count, nationwide channels at the end. */
export function citiesLine(item: Campaign, search = "", limit = 4): CitiesLine {
  const query = normalized(search);
  const hit = (name: string) => query.length > 0 && normalized(name).includes(query);
  const ordered = [...item.cities].sort((left, right) => Number(hit(right)) - Number(hit(left)));
  const shown = ordered.slice(0, limit).map((name) => ({ name, hit: hit(name) }));
  const nationwide = item.channels.filter((row) => row.nationwide).map((row) => SHORT_CHANNEL_NAMES[row.channel_id]);
  return {
    shown,
    rest: ordered.length - shown.length,
    nationwide: nationwide.length ? `вся страна (${nationwide.join(", ")})` : null,
  };
}

export function geographyLabel(item: Campaign): string {
  const nationwide = item.channels.some((row) => row.nationwide);
  if (!item.cities.length) return nationwide ? "вся страна" : "города не указаны";
  const cities = formatCount(item.cities.length, "город", "города", "городов");
  return nationwide ? `${cities} и вся страна` : cities;
}

/* ------------------------------------------------------------------ range tracks */

export interface TrackGeometry {
  left: number;
  width: number;
  dot: number;
  reference: number | null;
}

/** Positions in percent: the domain covers the range and the reference point with a small margin. */
export function trackGeometry(value: Range, reference: number | null): TrackGeometry {
  const points = [value.low, value.high, ...(reference === null ? [] : [reference])];
  let low = Math.min(...points);
  let high = Math.max(...points);
  const pad = (high - low) * 0.14 || 1;
  low -= pad;
  high += pad;
  const position = (point: number) => ((point - low) / (high - low)) * 100;
  return {
    left: position(value.low),
    width: position(value.high) - position(value.low),
    dot: position(value.estimate),
    reference: reference === null ? null : position(reference),
  };
}

/** Mini ROAS bar of the list: fixed 0…5 scale with the 1.0 tick. */
export function miniRoasGeometry(value: Range, max = 5): TrackGeometry {
  const position = (point: number) => (Math.max(0, Math.min(point, max)) / max) * 100;
  return {
    left: position(value.low),
    width: position(value.high) - position(value.low),
    dot: position(value.estimate),
    reference: position(1),
  };
}
