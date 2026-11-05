import { describe, expect, it } from "vitest";
import fixture from "../../test/fixtures/campaign_catalog_v1_synthetic.json";
import { parseCampaignCatalogV1 } from "../../shared/api/campaign-catalog-client";
import type { Campaign } from "../../shared/api/generated/campaign-catalog-v1";
import {
  DEFAULT_FILTERS,
  basketBelowKopeck,
  citiesLine,
  decimalsFor,
  filterCampaigns,
  filtersFromSearch,
  filtersToSearch,
  formatCount,
  formatMln,
  formatPeriod,
  formatRoas,
  formatShare,
  formatSigned,
  splitPercents,
  geographyLabel,
  isRegionName,
  matchesSearch,
  measureFormat,
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
  it("rounds the three parts of the effect to whole percents that add up to 100, like the catalog build", () => {
    expect(splitPercents([0.335, 0.335, 0.33])).toEqual([34, 33, 33]);
    expect(splitPercents([0.201, 0.625819, 0.173181])).toEqual([20, 63, 17]);
    expect(splitPercents([0.125, 0.125, 0.75])).toEqual([13, 12, 75]);
    expect(splitPercents([0, 0, 0])).toEqual([0, 0, 0]);
    for (const row of catalog.campaigns) {
      const parts = row.explanation;
      if (!parts) continue;
      const percents = splitPercents([parts.kept_share, parts.own_saturation_share, parts.overlap_share]);
      expect(percents.reduce((sum, value) => sum + value, 0)).toBe(100);
    }
  });

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
    expect(formatMln(4_344_460)).toBe("4,3");
    expect(formatSigned(2.74)).toBe("+2,7");
    expect(formatSigned(-1.9)).toBe("−1,9");
    expect(formatSigned(-0.04)).toBe("0,0");
    expect(formatSigned(0.0158, 3)).toBe("+0,016");
    expect(formatRoas(1.1666)).toBe("1,17");
    expect(formatShare(0.333)).toBe("33%");
  });

  it("keeps about two significant digits of small real numbers", () => {
    expect(decimalsFor([13.7], 1, 3)).toBe(1);
    expect(decimalsFor([2.5, 1.8, 3.6], 1, 3)).toBe(1);
    expect(decimalsFor([0.5058, 0.31], 1, 3)).toBe(2);
    expect(decimalsFor([0.0609, 0.0427, 0.0727], 1, 3)).toBe(3);
    expect(decimalsFor([0.0131], 1, 3)).toBe(3);
    expect(decimalsFor([0.00002], 1, 3)).toBe(3);
    expect(decimalsFor([0, 0], 1, 3)).toBe(1);
    // budgets of a few hundred rubles still show a digit instead of «0,0»
    expect(formatMln(180.5)).toBe("0,0002");
    expect(formatMln(26_545)).toBe("0,027");
    expect(formatMln(310_370)).toBe("0,31");
  });

  it("writes the estimate and both ends of a range with the same decimals", () => {
    const orders = measureFormat("orders", { estimate: 0.0609, low: 0.0427, high: 0.0727 });
    expect([orders(0.0609), orders(0.0427), orders(0.0727)]).toEqual(["+0,061", "+0,043", "+0,073"]);
    const tiny = measureFormat("orders", { estimate: 0.0019, low: 0.0013, high: 0.0024 });
    expect([tiny(0.0019), tiny(0.0013), tiny(0.0024)]).toEqual(["+0,002", "+0,001", "+0,002"]);
    const turnover = measureFormat("mln", { estimate: 130_435, low: 95_000, high: 155_469 });
    expect([turnover(130_435), turnover(95_000), turnover(155_469)]).toEqual(["0,13", "0,10", "0,16"]);
    const wide = measureFormat("mln", { estimate: 1_200_000, low: 40_000, high: 3_500_000 });
    expect([wide(1_200_000), wide(40_000), wide(3_500_000)]).toEqual(["1,2", "0,0", "3,5"]);
    const basket = measureFormat("basket", { estimate: 0.167, low: 0.06, high: 0.38 });
    expect([basket(0.167), basket(0.06), basket(0.38)]).toEqual(["+0,17", "+0,06", "+0,38"]);
    expect(measureFormat("basket", { estimate: 1.51, low: 0.4, high: 3.28 })(1.51)).toBe("+1,5");
    expect(measureFormat("roas", { estimate: 0.0023, low: 0.001, high: 0.0055 })(0.0023)).toBe("0,00");
  });

  it("says when the basket moves by less than a kopeck", () => {
    expect(basketBelowKopeck({ estimate: 0.0007, low: -0.0021, high: 0.0034 })).toBe(true);
    expect(basketBelowKopeck({ estimate: 0.0007, low: -0.0021, high: 0.0087 })).toBe(false);
    expect(basketBelowKopeck({ estimate: -0.006, low: -0.01, high: 0.001 })).toBe(false);
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

  it("counts regions apart from cities", () => {
    expect(["Нижегородская область", "Алтайский край", "Республика Марий Эл", "Кабардино-Балкарская республика",
      "Ханты-Мансийский автономный округ", "Кстовский Район", "Ненецкий АО"].every(isRegionName)).toBe(true);
    expect(["Москва", "Краснодар", "Нижний Новгород", "Набережные Челны", "Гусь-Хрустальный", "Красногорск",
      "Ханты-Мансийск", "Великие Луки", "Сокол", "Королев", "Кировск"].some(isRegionName)).toBe(false);
    expect(geographyLabel(campaign(11))).toBe("1 город и 2 региона");
    const base = campaign(11);
    const nationwide = { ...base.channels[0], nationwide: true };
    expect(geographyLabel({ ...base, cities: ["Москва", "Казань", "Алтайский край"], channels: [nationwide] }))
      .toBe("2 города, 1 регион и вся страна");
    expect(geographyLabel({ ...base, cities: [], channels: [nationwide] })).toBe("вся страна");
    expect(geographyLabel({ ...base, cities: [], channels: [{ ...nationwide, nationwide: false }] })).toBe("география не указана");
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
