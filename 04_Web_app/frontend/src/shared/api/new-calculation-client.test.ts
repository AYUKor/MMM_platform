import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CalculationProfileRequestError,
  CalculationProfileUnavailableError,
  UnsupportedCalculationProfileError,
  campaignPlanTemplateUrl,
  getCalculationProfile,
  parseCalculationProfile,
  type CalculationProfile,
} from "./new-calculation-client";

function profile(): CalculationProfile {
  return {
    contract_name: "calculation_profile_v1",
    schema_version: "1.0.0",
    scenario6_attempt_budget: 3_217,
    profile_label: "Синтетический профиль",
    model_version_label: "Синтетическая модель",
  };
}

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("new calculation Product API client", () => {
  it("loads and validates the active calculation profile", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(profile()));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getCalculationProfile()).resolves.toEqual(profile());
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/v1/calculation-profile",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("builds the template URL from the configured API boundary", () => {
    expect(campaignPlanTemplateUrl()).toBe(
      "http://127.0.0.1:8765/api/v1/templates/campaign-plan.xlsx",
    );
  });

  it.each([
    ["unknown contract", { ...profile(), contract_name: "future_profile" }],
    ["unsupported version", { ...profile(), schema_version: "2.0.0" }],
    ["zero attempts", { ...profile(), scenario6_attempt_budget: 0 }],
    ["fractional attempts", { ...profile(), scenario6_attempt_budget: 1.5 }],
    ["missing label", { ...profile(), profile_label: "" }],
    ["extra field", { ...profile(), internal_path: "/private/model" }],
  ])("rejects %s", (_name, payload) => {
    expect(() => parseCalculationProfile(payload)).toThrow(
      UnsupportedCalculationProfileError,
    );
  });

  it("maps 503 to a controlled unavailable error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ error: {} }, 503)));
    await expect(getCalculationProfile()).rejects.toBeInstanceOf(
      CalculationProfileUnavailableError,
    );
  });

  it("maps another HTTP failure without exposing its payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ raw_internal_code: "PRIVATE" }, 500)),
    );
    const error = await getCalculationProfile().catch((value: unknown) => value);
    expect(error).toBeInstanceOf(CalculationProfileRequestError);
    expect((error as Error).message).not.toContain("PRIVATE");
  });
});
