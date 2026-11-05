import type { Campaign, CampaignCatalogV1 } from "./generated/campaign-catalog-v1";
import type { CampaignCardV1 } from "./generated/campaign-card-v1";
import { appEnv } from "../config/env";
import { credentialedFetch } from "./credentialed-fetch";

type JsonRecord = Record<string, unknown>;

export const CAMPAIGN_CATALOG_PATH = "/api/v1/campaign-catalog";
export const CAMPAIGN_CATALOG_DOWNLOAD_PATH = "/api/v1/campaign-catalog/download";
export const CAMPAIGN_DIRECTIONS = ["ТС5/Онлайн", "ТС5/Оффлайн", "ТСХ/Онлайн", "ТСХ/Оффлайн"] as const;
export const CAMPAIGN_CHANNEL_DISPLAY_NAMES = {
  Digital_Performance: "Цифровая реклама",
  OOH_Total: "Наружная реклама",
  Indoor: "Indoor",
  "Радио": "Радио",
  "Нац_ТВ": "Национальное ТВ",
  "Рег_ТВ": "Региональное ТВ",
} as const satisfies Record<Campaign["main_channel_id"], Campaign["channels"][number]["display_name"]>;
export const CAMPAIGN_LONG_DAYS = 120;

const TITLE = "Прошлые кампании";
const WORKBOOK_SHEETS = ["Тех. информация", "Кампании до 120 дней", "Кампании длиннее 120 дней"] as const;
const CATALOG_KEYS = ["contract_name", "schema_version", "record_origin", "status", "title", "display_text", "package_id", "model_version", "model_display_name", "artifact_id", "catalog_version", "period_start", "period_end", "roas_level_label", "summary", "download", "notes", "campaigns", "updated_at_utc"] as const;
const CARD_KEYS = ["contract_name", "schema_version", "record_origin", "package_id", "model_version", "model_display_name", "artifact_id", "catalog_version", "period_start", "period_end", "roas_level_label", "notes", "campaign", "updated_at_utc"] as const;
const CAMPAIGN_KEYS = ["number", "name", "directions", "start_date", "end_date", "days_n", "duration_group", "budget_rub", "channels", "main_channel_id", "cities", "nationwide_channels", "status", "status_display_text", "turnover_increment_rub", "orders_per_1000_buyers", "avg_basket_increment_rub", "roas", "overlaps_n", "reliable"] as const;
const SUMMARY_KEYS = ["campaigns_n", "computed_n", "reliable_n", "up_to_120_days_n", "longer_120_days_n", "budget_rub", "computed_budget_rub", "turnover_increment_rub", "weighted_roas"] as const;
const DOWNLOAD_KEYS = ["file_name", "size_bytes", "sha256", "download_path", "sheets"] as const;
const CHANNEL_KEYS = ["channel_id", "display_name", "budget_rub", "nationwide"] as const;
const RANGE_KEYS = ["estimate", "low", "high"] as const;
const EFFECT_KEYS = ["turnover_increment_rub", "orders_per_1000_buyers", "avg_basket_increment_rub", "roas"] as const;
const PACKAGE_ID = /^pkg_[A-Za-z0-9._-]{8,128}$/;
const ARTIFACT_ID = /^artifact_[0-9a-f]{24}$/;
const NOTE_CODE = /^[a-z][a-z0-9_]{2,63}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const FILE_NAME = /^[^/\\]{1,200}\.xlsx$/;
const ABSOLUTE_PATH = /^(?:\/(?!api\/v1\/)|[A-Za-z]:[\\/]|file:\/\/)/i;
const MONEY_TOLERANCE_RUB = 1;
const RANGE_TOLERANCE = 1e-9;

export class CampaignCatalogNotPublishedError extends Error {
  readonly status = 404;
  constructor() { super("Каталог прошлых кампаний для активной модели пока не опубликован."); this.name = "CampaignCatalogNotPublishedError"; }
}
export class CampaignNotFoundError extends Error {
  readonly status = 404;
  constructor() { super("Кампании с таким номером нет в каталоге активной модели."); this.name = "CampaignNotFoundError"; }
}
export class CampaignCatalogUnavailableError extends Error {
  readonly status = 503;
  constructor() { super("Каталог прошлых кампаний временно недоступен."); this.name = "CampaignCatalogUnavailableError"; }
}
export class CampaignCatalogRequestError extends Error {
  readonly retryable: boolean;
  constructor(readonly status: number | null = null) {
    super("Не удалось получить каталог прошлых кампаний.");
    this.name = "CampaignCatalogRequestError";
    this.retryable = status === null || status >= 500;
  }
}
/** A malformed catalog is never shown: it is indistinguishable from an unsupported contract. */
export class UnsupportedCampaignCatalogContractError extends Error {
  constructor(readonly status: number | null = null) { super("Каталог прошлых кампаний имеет неподдерживаемый формат."); this.name = "UnsupportedCampaignCatalogContractError"; }
}

function record(value: unknown): value is JsonRecord { return value !== null && typeof value === "object" && !Array.isArray(value); }
function exact(value: JsonRecord, keys: readonly string[]): boolean { const actual = Object.keys(value); return actual.length === keys.length && keys.every((key) => key in value); }
function text(value: unknown): value is string { return typeof value === "string" && value.trim().length > 0; }
function finite(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function nonNegative(value: unknown): value is number { return finite(value) && value >= 0; }
function nonNegativeInteger(value: unknown): value is number { return nonNegative(value) && Number.isInteger(value); }
function isoDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}
function zonedDateTime(value: unknown): value is string { return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value) && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value)); }
function uniqueTexts(value: unknown): value is string[] { return Array.isArray(value) && value.every(text) && new Set(value).size === value.length; }
function hasUnsafePath(value: unknown): boolean {
  if (typeof value === "string") return ABSOLUTE_PATH.test(value);
  if (Array.isArray(value)) return value.some(hasUnsafePath);
  return record(value) && Object.values(value).some(hasUnsafePath);
}
function range(value: unknown): boolean {
  return record(value) && exact(value, RANGE_KEYS) && finite(value.estimate) && finite(value.low) && finite(value.high)
    && value.low <= value.estimate + RANGE_TOLERANCE && value.estimate <= value.high + RANGE_TOLERANCE;
}
function channel(value: unknown): boolean {
  if (!record(value) || !exact(value, CHANNEL_KEYS) || typeof value.channel_id !== "string") return false;
  const display = (CAMPAIGN_CHANNEL_DISPLAY_NAMES as Record<string, string>)[value.channel_id];
  return display !== undefined && value.display_name === display && nonNegative(value.budget_rub) && typeof value.nationwide === "boolean";
}

function campaign(value: unknown): value is Campaign {
  if (!record(value) || !exact(value, CAMPAIGN_KEYS)) return false;
  if (!nonNegativeInteger(value.number) || value.number < 1 || !text(value.name)) return false;
  if (!Array.isArray(value.directions) || value.directions.length === 0 || new Set(value.directions).size !== value.directions.length
    || !value.directions.every((item) => (CAMPAIGN_DIRECTIONS as readonly unknown[]).includes(item))) return false;
  if (!isoDate(value.start_date) || !isoDate(value.end_date) || value.start_date > value.end_date) return false;
  if (!nonNegativeInteger(value.days_n) || value.days_n < 1) return false;
  const expectedGroup = value.days_n >= CAMPAIGN_LONG_DAYS ? "120_days_and_longer" : "up_to_120_days";
  if (value.duration_group !== expectedGroup || !nonNegative(value.budget_rub)) return false;
  if (!Array.isArray(value.channels) || value.channels.length === 0 || !value.channels.every(channel)) return false;
  const channels = value.channels as JsonRecord[];
  const channelIds = channels.map((item) => item.channel_id as string);
  if (new Set(channelIds).size !== channelIds.length || typeof value.main_channel_id !== "string" || !channelIds.includes(value.main_channel_id)) return false;
  const channelBudget = channels.reduce((sum, item) => sum + (item.budget_rub as number), 0);
  if (Math.abs(channelBudget - value.budget_rub) > Math.max(MONEY_TOLERANCE_RUB, value.budget_rub * 1e-9)) return false;
  if (!uniqueTexts(value.cities) || !uniqueTexts(value.nationwide_channels)) return false;
  if (!nonNegativeInteger(value.overlaps_n) || (value.reliable !== 0 && value.reliable !== 1)) return false;
  if (value.status === "computed") {
    return value.status_display_text === null && EFFECT_KEYS.every((key) => range(value[key]));
  }
  if (value.status === "not_computed") {
    return text(value.status_display_text) && value.reliable === 0 && EFFECT_KEYS.every((key) => value[key] === null);
  }
  return false;
}

function notes(value: unknown): boolean {
  return Array.isArray(value)
    && value.every((item) => record(item) && exact(item, ["code", "display_text"]) && typeof item.code === "string" && NOTE_CODE.test(item.code) && text(item.display_text))
    && new Set(value.map((item) => (item as JsonRecord).code)).size === value.length;
}

function campaignList(value: unknown): value is Campaign[] {
  if (!Array.isArray(value) || !value.every(campaign)) return false;
  return value.every((item, index) => index === 0 || (value[index - 1] as Campaign).number < item.number);
}

function summaryMatches(value: unknown, campaigns: Campaign[]): boolean {
  if (!record(value) || !exact(value, SUMMARY_KEYS)) return false;
  const computed = campaigns.filter((item) => item.status === "computed");
  const budget = campaigns.reduce((sum, item) => sum + item.budget_rub, 0);
  const computedBudget = computed.reduce((sum, item) => sum + item.budget_rub, 0);
  const turnover = computed.reduce((sum, item) => sum + (item.turnover_increment_rub?.estimate ?? 0), 0);
  const tolerance = (total: number) => Math.max(MONEY_TOLERANCE_RUB, Math.abs(total) * 1e-9);
  if (value.campaigns_n !== campaigns.length || value.computed_n !== computed.length
    || value.reliable_n !== campaigns.filter((item) => item.reliable === 1).length
    || value.up_to_120_days_n !== campaigns.filter((item) => item.duration_group === "up_to_120_days").length
    || value.longer_120_days_n !== campaigns.filter((item) => item.duration_group === "120_days_and_longer").length) return false;
  if (!nonNegative(value.budget_rub) || Math.abs(value.budget_rub - budget) > tolerance(budget)
    || !nonNegative(value.computed_budget_rub) || Math.abs(value.computed_budget_rub - computedBudget) > tolerance(computedBudget)
    || !finite(value.turnover_increment_rub) || Math.abs(value.turnover_increment_rub - turnover) > tolerance(turnover)) return false;
  if (computedBudget <= 0) return value.weighted_roas === null;
  return finite(value.weighted_roas) && Math.abs(value.weighted_roas - turnover / computedBudget) <= 1e-6;
}

function download(value: unknown): boolean {
  return record(value) && exact(value, DOWNLOAD_KEYS)
    && typeof value.file_name === "string" && FILE_NAME.test(value.file_name)
    && nonNegativeInteger(value.size_bytes) && value.size_bytes > 0
    && typeof value.sha256 === "string" && SHA256.test(value.sha256)
    && value.download_path === CAMPAIGN_CATALOG_DOWNLOAD_PATH
    && Array.isArray(value.sheets) && value.sheets.length === WORKBOOK_SHEETS.length
    && value.sheets.every((item, index) => item === WORKBOOK_SHEETS[index]);
}

function boundIdentity(value: JsonRecord): boolean {
  return typeof value.package_id === "string" && PACKAGE_ID.test(value.package_id)
    && text(value.model_version) && text(value.model_display_name)
    && typeof value.artifact_id === "string" && ARTIFACT_ID.test(value.artifact_id)
    && text(value.catalog_version) && text(value.roas_level_label)
    && isoDate(value.period_start) && isoDate(value.period_end) && value.period_start <= value.period_end
    && notes(value.notes) && zonedDateTime(value.updated_at_utc);
}

export function parseCampaignCatalogV1(value: unknown): CampaignCatalogV1 {
  if (!record(value) || !exact(value, CATALOG_KEYS) || value.contract_name !== "campaign_catalog_v1"
    || value.schema_version !== "1.0.0" || value.title !== TITLE || !text(value.display_text)
    || hasUnsafePath(value)) throw new UnsupportedCampaignCatalogContractError();
  if (value.status === "unavailable") {
    if (value.record_origin !== "model_package_artifact_unavailable"
      || typeof value.package_id !== "string" || !PACKAGE_ID.test(value.package_id)
      || !(value.model_version === null || text(value.model_version))
      || value.model_display_name !== null || value.artifact_id !== null || value.catalog_version !== null
      || value.period_start !== null || value.period_end !== null || value.roas_level_label !== null
      || value.summary !== null || value.download !== null || value.updated_at_utc !== null
      || !Array.isArray(value.notes) || value.notes.length !== 0
      || !Array.isArray(value.campaigns) || value.campaigns.length !== 0) throw new UnsupportedCampaignCatalogContractError();
    return value as unknown as CampaignCatalogV1;
  }
  if (value.status !== "available" || value.record_origin !== "verified_model_package_artifact"
    || !boundIdentity(value) || !campaignList(value.campaigns) || value.campaigns.length === 0
    || !summaryMatches(value.summary, value.campaigns) || !download(value.download)) throw new UnsupportedCampaignCatalogContractError();
  return value as unknown as CampaignCatalogV1;
}

export function parseCampaignCardV1(value: unknown, number: number): CampaignCardV1 {
  if (!record(value) || !exact(value, CARD_KEYS) || value.contract_name !== "campaign_card_v1"
    || value.schema_version !== "1.0.0" || value.record_origin !== "verified_model_package_artifact"
    || hasUnsafePath(value) || !boundIdentity(value) || !campaign(value.campaign)
    || value.campaign.number !== number) throw new UnsupportedCampaignCatalogContractError();
  return value as unknown as CampaignCardV1;
}

function endpoint(baseUrl: string, path: string): string { return `${baseUrl.replace(/\/+$/, "")}${path}`; }
function errorCode(value: unknown): string | null {
  return record(value) && record(value.error) && typeof value.error.code === "string" ? value.error.code : null;
}

/** A 404 on the list means the catalog is not on this server yet; on a card it can also mean a wrong number. */
type NotFoundMapper = (code: string | null) => Error;
const catalogNotFound: NotFoundMapper = () => new CampaignCatalogNotPublishedError();
const cardNotFound: NotFoundMapper = (code) => code === "CAMPAIGN_CATALOG_NOT_PUBLISHED"
  ? new CampaignCatalogNotPublishedError()
  : new CampaignNotFoundError();

async function get<T>(path: string, parse: (value: unknown) => T, notFound: NotFoundMapper, signal: AbortSignal | undefined, baseUrl: string): Promise<T> {
  let response: Response;
  try {
    response = await credentialedFetch(endpoint(baseUrl, path), { headers: { Accept: "application/json" }, signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new CampaignCatalogRequestError();
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (response.ok) throw new UnsupportedCampaignCatalogContractError(response.status);
    throw new CampaignCatalogRequestError(response.status);
  }
  if (!response.ok) {
    const code = errorCode(payload);
    if (response.status === 404) throw notFound(code);
    if (response.status === 503) throw new CampaignCatalogUnavailableError();
    throw new CampaignCatalogRequestError(response.status);
  }
  return parse(payload);
}

export function getCampaignCatalog(signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<CampaignCatalogV1> {
  return get(CAMPAIGN_CATALOG_PATH, parseCampaignCatalogV1, catalogNotFound, signal, baseUrl);
}

export function getCampaignCard(number: number, signal?: AbortSignal, baseUrl = appEnv.apiBaseUrl): Promise<CampaignCardV1> {
  if (!Number.isInteger(number) || number < 1 || number > 9999) return Promise.reject(new CampaignNotFoundError());
  return get(`${CAMPAIGN_CATALOG_PATH}/${number}`, (value) => parseCampaignCardV1(value, number), cardNotFound, signal, baseUrl);
}

export function campaignCatalogDownloadUrl(baseUrl = appEnv.apiBaseUrl): string {
  return endpoint(baseUrl, CAMPAIGN_CATALOG_DOWNLOAD_PATH);
}
