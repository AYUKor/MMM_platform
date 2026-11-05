import { describe, expect, it } from "vitest";
import fixture from "../../test/fixtures/campaign_catalog_v1_synthetic.json";
import { parseCampaignCatalogV1 } from "../../shared/api/campaign-catalog-client";
import type { Campaign } from "../../shared/api/generated/campaign-catalog-v1";
import {
  DEFAULT_FILTERS,
  citiesLine,
  filterCampaigns,
  filtersFromSearch,
  filtersToSearch,
  formatCount,
  formatMln,
  formatPeriod,
  formatRoas,
  formatShare,
  formatSigned,
  geographyLabel,
  matchesSearch,
  miniRoasGeometry,
  plural,
  tabCounts,
  trackGeometry,
  type CatalogFilters,
} from "./campaignCatalogModel";

const NBSP = " ";
const catalog = parseCampaignCatalogV1(structuredClone(fixture));
const rows = catalog.campaigns;

function campaign(number: number): Campaign {
  const item = rows.find((row) => row.number === number);
  if (!item) throw new Error(`no campaign ${number}`);
  return item;
}

function numbers(filters: Partial<CatalogFilters>): number[] {
  return filterCampaigns(rows, { ...DEFAULT_FILTERS, ...filters }).map((item) => item.number);
}

describe("catalog filters in the address bar", () => {
  it("round-trips every filter and leaves defaults out of the link", () => {
    const filters: CatalogFilters = {
      tab: "long",
      search: "Казань",
      direction: "ТСХ/Онлайн",
      channel: "Нац_ТВ",
      reliability: "1",
      sort: "roas",
    };
    const search = filtersToSearch(filters);
    expect(Object.fromEntries(search)).toEqual({
      tab: "long",
      q: "Казань",
      direction: "ТСХ/Онлайн",
      channel: "Нац_ТВ",
      reliable: "1",
      sort: "roas",
    });
    expect(filtersFromSearch(search)).toEqual(filters);
    expect(filtersToSearch(DEFAULT_FILTERS).toString()).toBe("");
  });

  it("ignores values it does not know", () => {
    const filters = filtersFromSearch(new URLSearchParams("tab=all&direction=ТС5/Склад&channel=TV&reliable=2&sort=random"));
    expect(filters).toEqual(DEFAULT_FILTERS);
  });
});

describe("catalog list", () => {
  it("splits campaigns by the 120-day rule", () => {
    expect(tabCounts(rows)).toEqual({ short: 9, long: 3 });
    expect(numbers({ tab: "long" })).toEqual([1, 7, 12]);
  });

  it("shows new campaigns first by default and old first on request", () => {
    expect(numbers({})).toEqual([8, 10, 2, 9, 5, 11, 3, 4, 13]);
    expect(numbers({ sort: "old" })).toEqual([13, 4, 3, 11, 5, 9, 2, 10, 8]);
  });

  it("puts campaigns without an estimate last when sorting by effect", () => {
    const byRoas = numbers({ sort: "roas" });
    expect(byRoas.at(-1)).toBe(5);
    const roas = byRoas.slice(0, -1).map((number) => campaign(number).roas?.estimate ?? 0);
    expect(roas).toEqual([...roas].sort((left, right) => right - left));
    expect(numbers({ sort: "turnover" }).at(-1)).toBe(5);
  });

  it("sorts by budget from the largest", () => {
    const budgets = numbers({ sort: "budget" }).map((number) => campaign(number).budget_rub);
    expect(budgets).toEqual([...budgets].sort((left, right) => right - left));
  });

  it("filters by direction, channel and reliability together", () => {
    expect(numbers({ direction: "ТСХ/Оффлайн" })).toEqual([9, 4, 13]);
    expect(numbers({ channel: "Нац_ТВ" })).toEqual([10, 5, 3]);
    expect(numbers({ reliability: "0" })).toEqual([9, 5, 3]);
    expect(numbers({ direction: "ТС5/Онлайн", channel: "Нац_ТВ", reliability: "1" })).toEqual([10]);
  });

  it("finds campaigns by name, number, city, channel and nationwide reach", () => {
    expect(matchesSearch(campaign(7), "кампания 7")).toBe(true);
    expect(matchesSearch(campaign(7), "№ 7")).toBe(true);
    expect(matchesSearch(campaign(7), "17")).toBe(false);
    expect(matchesSearch(campaign(8), "москва")).toBe(true);
    expect(matchesSearch(campaign(4), "радио")).toBe(true);
    expect(matchesSearch(campaign(3), "Нац. ТВ")).toBe(true);
    expect(matchesSearch(campaign(3), "вся страна")).toBe(true);
    expect(matchesSearch(campaign(8), "вся страна")).toBe(false);
    expect(numbers({ search: "Москва" })).toEqual([8, 11, 4]);
  });
});

describe("catalog text", () => {
  it("uses Russian plural forms", () => {
    expect([1, 2, 5, 11, 21, 22, 25, 111].map((value) => plural(value, "день", "дня", "дней")))
      .toEqual(["день", "дня", "дней", "дней", "день", "дня", "дней", "дней"]);
    expect(formatCount(164, "день", "дня", "дней")).toBe("164 дня");
  });

  it("writes periods within one year and across years", () => {
    expect(formatPeriod("2025-09-28", "2025-11-13")).toBe("28 сен – 13 ноя 2025");
    expect(formatPeriod("2025-12-29", "2026-01-11")).toBe("29 дек 2025 – 11 янв 2026");
  });

  it("formats money in millions, signed changes and ROAS", () => {
    expect(formatMln(10_490_200_000)).toBe(`10${NBSP}490,2`);
    expect(formatSigned(2.74)).toBe("+2,7");
    expect(formatSigned(-1.9)).toBe("−1,9");
    expect(formatSigned(-0.04)).toBe("0,0");
    expect(formatRoas(1.1666)).toBe("1,17");
    expect(formatShare(0.333)).toBe("33%");
  });

  it("lists four cities, a searched city first, and nationwide channels", () => {
    const line = citiesLine(campaign(10), "Самара");
    expect(line.shown.map((item) => item.name)).toEqual(["Самара", "Казань", "Екатеринбург", "Новосибирск"]);
    expect(line.shown[0].hit).toBe(true);
    expect(line.rest).toBe(5);
    expect(line.nationwide).toBe("вся страна (Нац. ТВ)");
    expect(geographyLabel(campaign(10))).toBe("9 городов и вся страна");
    expect(geographyLabel(campaign(3))).toBe("1 город и вся страна");
    expect(geographyLabel(campaign(8))).toBe("1 город");
  });
});

describe("range tracks", () => {
  it("keeps the range, the estimate and the reference on the track", () => {
    const geometry = trackGeometry({ estimate: 2.5, low: 1.8, high: 3.6 }, 1);
    expect(geometry.reference).toBeGreaterThan(0);
    expect(geometry.left).toBeGreaterThan(geometry.reference ?? 0);
    expect(geometry.dot).toBeGreaterThan(geometry.left);
    expect(geometry.left + geometry.width).toBeLessThan(100);
  });

  it("handles a range of zero width", () => {
    const geometry = trackGeometry({ estimate: 0, low: 0, high: 0 }, null);
    expect(geometry).toEqual({ left: 50, width: 0, dot: 50, reference: null });
  });

  it("clips the list ROAS bar to the 0–5 scale", () => {
    expect(miniRoasGeometry({ estimate: 7, low: -1, high: 9 })).toEqual({ left: 0, width: 100, dot: 100, reference: 20 });
  });
});
