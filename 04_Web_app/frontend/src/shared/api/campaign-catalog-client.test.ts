import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../../test/fixtures/campaign_catalog_v1_synthetic.json";
import {
  CAMPAIGN_CATALOG_DOWNLOAD_PATH,
  CampaignCatalogNotPublishedError,
  CampaignCatalogRequestError,
  CampaignCatalogUnavailableError,
  CampaignNotFoundError,
  UnsupportedCampaignCatalogContractError,
  campaignCatalogDownloadUrl,
  getCampaignCard,
  getCampaignCatalog,
  parseCampaignCardV1,
  parseCampaignCatalogV1,
} from "./campaign-catalog-client";

const API_BASE_URL = "http://127.0.0.1:8765/";

type Json = Record<string, unknown>;

function catalog(): Json {
  return structuredClone(fixture) as unknown as Json;
}

function campaigns(value: Json): Json[] {
  return value.campaigns as Json[];
}

function card(number = 1): Json {
  const source = catalog();
  const item = campaigns(source).find((row) => row.number === number);
  return {
    contract_name: "campaign_card_v1",
    schema_version: "1.1.0",
    record_origin: "verified_model_package_artifact",
    package_id: source.package_id,
    model_version: source.model_version,
    model_display_name: source.model_display_name,
    artifact_id: source.artifact_id,
    catalog_version: source.catalog_version,
    period_start: source.period_start,
    period_end: source.period_end,
    roas_level_label: source.roas_level_label,
    notes: source.notes,
    campaign: item,
    updated_at_utc: source.updated_at_utc,
  };
}

function unavailable(): Json {
  return {
    contract_name: "campaign_catalog_v1",
    schema_version: "1.1.0",
    record_origin: "model_package_artifact_unavailable",
    status: "unavailable",
    title: "Прошлые кампании",
    display_text: "Каталог прошлых кампаний для активной модели пока не опубликован.",
    package_id: "pkg_abababababababab_2222222222222222",
    model_version: null,
    model_display_name: null,
    artifact_id: null,
    catalog_version: null,
    period_start: null,
    period_end: null,
    roas_level_label: null,
    summary: null,
    download: null,
    notes: [],
    campaigns: [],
    updated_at_utc: null,
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubResponse(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function errorBody(code: string) {
  return { error: { code, message: "test", retryable: false, user_action: "test" } };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("campaign catalog contract", () => {
  it("accepts the synthetic catalog built by the real service", () => {
    const parsed = parseCampaignCatalogV1(catalog());
    expect(parsed.status).toBe("available");
    expect(parsed.campaigns).toHaveLength(12);
    expect(parsed.summary?.computed_n).toBe(11);
    expect(parsed.download?.download_path).toBe(CAMPAIGN_CATALOG_DOWNLOAD_PATH);
  });

  it("accepts the not-published state only when it carries no catalog data", () => {
    expect(parseCampaignCatalogV1(unavailable()).status).toBe("unavailable");

    const leaking = unavailable();
    leaking.campaigns = campaigns(catalog()).slice(0, 1);
    expect(() => parseCampaignCatalogV1(leaking)).toThrow(UnsupportedCampaignCatalogContractError);

    const summary = unavailable();
    summary.summary = catalog().summary;
    expect(() => parseCampaignCatalogV1(summary)).toThrow(UnsupportedCampaignCatalogContractError);
  });

  const broken: [string, (value: Json) => void][] = [
    ["an extra top-level key", (value) => { value.extra = true; }],
    ["another title", (value) => { value.title = "Каталог"; }],
    ["a server path in a note", (value) => {
      (value.notes as Json[])[0].display_text = "/Users/aleks_main/Work/catalog.json";
    }],
    ["a summary that does not match the rows", (value) => {
      (value.summary as Json).campaigns_n = 13;
    }],
    ["a total ROAS that does not match the rows", (value) => {
      (value.summary as Json).weighted_roas = 30;
    }],
    ["campaigns out of order", (value) => {
      const rows = campaigns(value);
      [rows[0], rows[1]] = [rows[1], rows[0]];
    }],
    ["a channel budget that does not add up to the campaign budget", (value) => {
      const first = campaigns(value)[0];
      first.budget_rub = (first.budget_rub as number) + 1_000_000;
    }],
    ["a duration group that contradicts the days", (value) => {
      campaigns(value)[0].duration_group = "up_to_120_days";
    }],
    ["an estimate outside its range", (value) => {
      const roas = campaigns(value)[0].roas as Json;
      roas.low = (roas.estimate as number) + 1;
    }],
    ["a campaign without an estimate marked reliable", (value) => {
      const row = campaigns(value).find((item) => item.status === "not_computed") as Json;
      row.reliable = 1;
    }],
    ["a renamed channel", (value) => {
      ((campaigns(value)[0].channels as Json[])[0]).display_name = "Digital";
    }],
    ["an unknown direction", (value) => {
      campaigns(value)[0].directions = ["ТС5/Склад"];
    }],
    ["another download path", (value) => {
      (value.download as Json).download_path = "/api/v1/reports/download";
    }],
    ["a workbook without the long-campaign sheet", (value) => {
      (value.download as Json).sheets = ["Тех. информация", "Кампании до 120 дней"];
    }],
    ["a main channel the campaign did not use", (value) => {
      campaigns(value)[0].main_channel_id = "Рег_ТВ";
    }],
    ["reasons whose parts do not add up to the whole effect", (value) => {
      const reasons = campaigns(value)[0].explanation as Json;
      reasons.kept_share = (reasons.kept_share as number) + 0.1;
    }],
    ["reasons with more than three sentences", (value) => {
      const reasons = campaigns(value)[0].explanation as Json;
      reasons.reasons = ["one", "two", "three", "four"].map((code) => ({ code: `extra_${code}`, display_text: "Ещё причина." }));
    }],
    ["reasons without a rule file version", (value) => {
      (campaigns(value)[0].explanation as Json).rules_version = "";
    }],
    ["reasons for a campaign without an estimate", (value) => {
      const row = campaigns(value).find((item) => item.status === "not_computed") as Json;
      row.explanation = campaigns(value)[0].explanation;
    }],
  ];

  it.each(broken)("rejects %s", (_name, mutate) => {
    const value = catalog();
    mutate(value);
    expect(() => parseCampaignCatalogV1(value)).toThrow(UnsupportedCampaignCatalogContractError);
  });

  it("accepts a catalog built before the reasons existed only without reasons", () => {
    const value = catalog();
    for (const row of campaigns(value)) row.explanation = null;
    expect(parseCampaignCatalogV1(value).campaigns.every((row) => row.explanation === null)).toBe(true);

    const missing = catalog();
    delete campaigns(missing)[0].explanation;
    expect(() => parseCampaignCatalogV1(missing)).toThrow(UnsupportedCampaignCatalogContractError);
  });

  it("accepts a card only for the requested campaign", () => {
    expect(parseCampaignCardV1(card(7), 7).campaign.number).toBe(7);
    expect(() => parseCampaignCardV1(card(7), 8)).toThrow(UnsupportedCampaignCatalogContractError);

    const extra = card(7);
    extra.summary = catalog().summary;
    expect(() => parseCampaignCardV1(extra, 7)).toThrow(UnsupportedCampaignCatalogContractError);
  });
});

describe("campaign catalog requests", () => {
  it("reads the catalog with the session cookie", async () => {
    const fetchMock = stubResponse(jsonResponse(catalog()));
    const parsed = await getCampaignCatalog(undefined, API_BASE_URL);
    expect(parsed.campaigns).toHaveLength(12);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/v1/campaign-catalog",
      expect.objectContaining({ credentials: "include", headers: { Accept: "application/json" } }),
    );
  });

  it("reads one campaign card by number", async () => {
    const fetchMock = stubResponse(jsonResponse(card(9)));
    await expect(getCampaignCard(9, undefined, API_BASE_URL)).resolves.toMatchObject({ campaign: { number: 9 } });
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8765/api/v1/campaign-catalog/9");
  });

  it("never requests an impossible campaign number", async () => {
    const fetchMock = stubResponse(jsonResponse(card(1)));
    for (const number of [0, -1, 1.5, 10_000, Number.NaN]) {
      await expect(getCampaignCard(number, undefined, API_BASE_URL)).rejects.toBeInstanceOf(CampaignNotFoundError);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("treats any 404 on the list as a catalog that is not published yet", async () => {
    stubResponse(jsonResponse(errorBody("ROUTE_NOT_FOUND"), 404));
    await expect(getCampaignCatalog(undefined, API_BASE_URL)).rejects.toBeInstanceOf(CampaignCatalogNotPublishedError);
  });

  it("tells a missing campaign from a catalog that is not published", async () => {
    stubResponse(jsonResponse(errorBody("CAMPAIGN_NOT_FOUND"), 404));
    await expect(getCampaignCard(999, undefined, API_BASE_URL)).rejects.toBeInstanceOf(CampaignNotFoundError);

    stubResponse(jsonResponse(errorBody("CAMPAIGN_CATALOG_NOT_PUBLISHED"), 404));
    await expect(getCampaignCard(5, undefined, API_BASE_URL)).rejects.toBeInstanceOf(CampaignCatalogNotPublishedError);
  });

  it("reports a failed integrity check as a temporary outage", async () => {
    stubResponse(jsonResponse(errorBody("CAMPAIGN_CATALOG_UNAVAILABLE"), 503));
    await expect(getCampaignCatalog(undefined, API_BASE_URL)).rejects.toBeInstanceOf(CampaignCatalogUnavailableError);
  });

  it("keeps other HTTP and network failures apart from contract errors", async () => {
    stubResponse(jsonResponse(errorBody("FORBIDDEN"), 403));
    const forbidden = await getCampaignCatalog(undefined, API_BASE_URL).catch((error: unknown) => error);
    expect(forbidden).toBeInstanceOf(CampaignCatalogRequestError);
    expect(forbidden).toMatchObject({ status: 403, retryable: false });

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const offline = await getCampaignCatalog(undefined, API_BASE_URL).catch((error: unknown) => error);
    expect(offline).toBeInstanceOf(CampaignCatalogRequestError);
    expect(offline).toMatchObject({ status: null, retryable: true });

    stubResponse(new Response("<html>", { status: 200 }));
    await expect(getCampaignCatalog(undefined, API_BASE_URL)).rejects.toBeInstanceOf(UnsupportedCampaignCatalogContractError);
  });

  it("builds the Excel link from the API base", () => {
    expect(campaignCatalogDownloadUrl(API_BASE_URL)).toBe("http://127.0.0.1:8765/api/v1/campaign-catalog/download");
  });
});
