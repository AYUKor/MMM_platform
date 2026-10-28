import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelPassportV1 } from "../../entities/model-passport/types";
import {
  getActiveModelPassport,
  ModelPassportRequestError,
  ModelPassportUnavailableError,
  UnsupportedModelPassportContractError,
} from "./model-passport-client";

const API_BASE_URL = "http://127.0.0.1:8765/";

function makePassport(): ModelPassportV1 {
  return {
    contract_name: "model_passport_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    serving: {
      deployment_profile: "local_development",
      display_name: "Тестовая исследовательская модель",
      calculation_allowed: true,
      decision_scope: "forecast_and_allocation_only",
      production_claim_allowed: false,
    },
    package: {
      registry_channel: "test-channel",
      registry_event_id: "test-event",
      package_id: "pkg_1111111111111111_2222222222222222",
      package_fingerprint: "a".repeat(64),
      model_run_id: "test-run",
      package_stage: "posterior_ready",
      activation_status: "preprod_restricted",
      package_schema_version: "0.0.0-test",
      gate_policy_version: "test-policy",
    },
    data: {
      grain: "daily",
      training_period: {
        start_date: "2025-01-01",
        end_date: "2025-12-31",
      },
      development_shadow_period: {
        start_date: null,
        end_date: null,
        purpose: "development_shadow_not_sealed_oot",
      },
    },
    coverage: {
      segments: ["Сегмент A"],
      channels: ["Канал A", "Канал B"],
      targets: [
        {
          target: "target_a",
          allowed_use_counts: { primary: 1, caution: 1 },
          objective_roles: ["primary_objective"],
        },
      ],
      geographies_n: 3,
      capability_cells_n: 2,
      allowed_use_counts: {
        primary: 1,
        caution: 1,
        diagnostic: 0,
        unavailable: 0,
      },
      channel_policies: [
        {
          segment: "Сегмент A",
          channel: "Канал A",
          target: "target_a",
          allowed_use: "primary",
          forecast_action: "allowed",
          optimizer_action: "allowed",
          display_text: "Доступно в тестовом контракте.",
        },
        {
          segment: "Сегмент A",
          channel: "Канал B",
          target: "target_a",
          allowed_use: "caution",
          forecast_action: "allowed_with_warning",
          optimizer_action: "no_increase",
          display_text: "Использовать с осторожностью.",
        },
      ],
    },
    validation: {
      historical_replay: {
        status: "passed",
        generated_at_utc: "2026-01-01T10:00:00+00:00",
        reason_code: null,
        display_text: "Replay пройден.",
      },
      sealed_oot: {
        status: "unavailable",
        generated_at_utc: null,
        reason_code: "TEST_OOT_UNAVAILABLE",
        display_text: "OOT пока недоступен.",
      },
      production_blockers: [
        {
          code: "TEST_PRODUCTION_BLOCKER",
          display_text: "Тестовый production blocker.",
        },
      ],
    },
    caveats: [
      {
        code: "research_model",
        display_text: "Только для исследовательского планирования.",
      },
    ],
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubPayload(payload: unknown, status = 200): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload, status));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Model Passport client", () => {
  it("loads a validated ModelPassport v1 from the active-model endpoint", async () => {
    const passport = makePassport();
    const fetchMock = stubPayload(passport);

    await expect(getActiveModelPassport(API_BASE_URL)).resolves.toEqual(passport);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/v1/models/active",
      {
        credentials: "include",
        headers: { Accept: "application/json" },
      },
    );
  });

  it("maps the explicit 503 catalog error to the unavailable state", async () => {
    stubPayload(
      {
        error: {
          code: "MODEL_PASSPORT_UNAVAILABLE",
          display_text: "RAW_BACKEND_UNAVAILABLE_TEXT",
          retryable: true,
          user_action: "RAW_BACKEND_USER_ACTION",
        },
      },
      503,
    );

    const error = await getActiveModelPassport(API_BASE_URL).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ModelPassportUnavailableError);
    expect((error as Error).message).not.toContain("MODEL_PASSPORT_UNAVAILABLE");
    expect((error as Error).message).not.toContain("RAW_BACKEND_UNAVAILABLE_TEXT");
  });

  it("rejects a malformed unavailable error envelope as a request error", async () => {
    stubPayload(
      {
        error: {
          code: "MODEL_PASSPORT_UNAVAILABLE",
          display_text: "RAW_BACKEND_UNAVAILABLE_TEXT",
        },
      },
      503,
    );

    await expect(getActiveModelPassport(API_BASE_URL)).rejects.toBeInstanceOf(
      ModelPassportRequestError,
    );
  });

  it.each([
    ["unknown contract", (value: Record<string, unknown>) => { value.contract_name = "future_contract"; }],
    ["unsupported version", (value: Record<string, unknown>) => { value.schema_version = "2.0.0"; }],
    ["missing field", (value: Record<string, unknown>) => { delete value.caveats; }],
    ["extra field", (value: Record<string, unknown>) => { value.internal_path = "relative-secret"; }],
  ])("rejects %s as an unsupported contract", async (_name, mutate) => {
    const passport = makePassport() as unknown as Record<string, unknown>;
    mutate(passport);
    stubPayload(passport);

    await expect(getActiveModelPassport(API_BASE_URL)).rejects.toBeInstanceOf(
      UnsupportedModelPassportContractError,
    );
  });

  it.each([
    ["invalid package id", (value: ModelPassportV1) => { value.package.package_id = "pkg_bad"; }],
    ["invalid fingerprint", (value: ModelPassportV1) => { value.package.package_fingerprint = "abc"; }],
    ["invalid calendar date", (value: ModelPassportV1) => { value.data.training_period.end_date = "2025-02-30"; }],
    ["reversed training period", (value: ModelPassportV1) => { value.data.training_period.end_date = "2024-12-31"; }],
    ["half-filled shadow period", (value: ModelPassportV1) => { value.data.development_shadow_period.start_date = "2026-01-01"; }],
    ["duplicate segment", (value: ModelPassportV1) => { value.coverage.segments.push("Сегмент A"); }],
    ["duplicate objective role", (value: ModelPassportV1) => { value.coverage.targets[0].objective_roles.push("primary_objective"); }],
    ["unknown policy coverage", (value: ModelPassportV1) => { value.coverage.channel_policies[0].channel = "Канал C"; }],
    ["duplicate policy", (value: ModelPassportV1) => { value.coverage.channel_policies[1].channel = "Канал A"; }],
    ["non-reconciled counts", (value: ModelPassportV1) => { value.coverage.allowed_use_counts.primary = 2; }],
    ["absolute POSIX path", (value: ModelPassportV1) => { value.caveats[0].display_text = "/Users/example/private"; }],
    ["absolute Windows path", (value: ModelPassportV1) => { value.caveats[0].display_text = "C:\\private\\model"; }],
  ])("fail-closes on semantic violation: %s", async (_name, mutate) => {
    const passport = makePassport();
    mutate(passport);
    stubPayload(passport);

    await expect(getActiveModelPassport(API_BASE_URL)).rejects.toBeInstanceOf(
      UnsupportedModelPassportContractError,
    );
  });

  function makeProductionPassport(): ModelPassportV1 {
    const passport = makePassport();
    passport.record_origin = "verified_model_package";
    passport.serving.production_claim_allowed = true;
    passport.package.activation_status = "production_ready";
    passport.validation.sealed_oot = {
      status: "passed",
      generated_at_utc: "2026-10-27T15:00:00+00:00",
      reason_code: null,
      display_text: "OOT-проверка засчитана.",
    };
    passport.validation.production_blockers = [];
    return passport;
  }

  it("accepts a production claim only when the passport's own record supports it", async () => {
    const passport = makeProductionPassport();
    stubPayload(passport);
    await expect(getActiveModelPassport(API_BASE_URL)).resolves.toEqual(passport);
  });

  it.each([
    ["historical replay did not pass", (value: ModelPassportV1) => { value.validation.historical_replay.status = "unavailable"; }],
    ["the OOT check did not pass", (value: ModelPassportV1) => { value.validation.sealed_oot.status = "failed"; }],
    ["a production blocker is open", (value: ModelPassportV1) => { value.validation.production_blockers = [{ code: "OPEN", display_text: "Нужна проверка." }]; }],
    ["the activation status is restricted", (value: ModelPassportV1) => { value.package.activation_status = "preprod_restricted"; }],
    ["the package is not posterior-ready", (value: ModelPassportV1) => { value.package.package_stage = "draft"; }],
    ["the record is a synthetic fixture", (value: ModelPassportV1) => { value.record_origin = "synthetic_fixture"; }],
  ])("rejects a production claim while %s", async (_name, mutate) => {
    const passport = makeProductionPassport();
    mutate(passport);
    stubPayload(passport);

    await expect(getActiveModelPassport(API_BASE_URL)).rejects.toBeInstanceOf(
      UnsupportedModelPassportContractError,
    );
  });

  it.each(["true", 1, null])("rejects a non-boolean production claim %s", async (claim) => {
    const passport = makeProductionPassport() as unknown as { serving: Record<string, unknown> };
    passport.serving.production_claim_allowed = claim;
    stubPayload(passport);

    await expect(getActiveModelPassport(API_BASE_URL)).rejects.toBeInstanceOf(
      UnsupportedModelPassportContractError,
    );
  });

  it("maps a missing API route to unsupported-contract state", async () => {
    stubPayload(
      { error: { code: "ROUTE_NOT_FOUND", display_text: "RAW_ROUTE_TEXT" } },
      404,
    );

    const error = await getActiveModelPassport(API_BASE_URL).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(UnsupportedModelPassportContractError);
    expect((error as Error).message).not.toContain("ROUTE_NOT_FOUND");
    expect((error as Error).message).not.toContain("RAW_ROUTE_TEXT");
  });

  it("maps other HTTP failures to a safe request error", async () => {
    stubPayload(
      { error: { code: "INTERNAL_PRIVATE_CODE", display_text: "RAW_PRIVATE_TEXT" } },
      500,
    );

    const error = await getActiveModelPassport(API_BASE_URL).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ModelPassportRequestError);
    expect(error).toMatchObject({ status: 500, retryable: true });
    expect((error as Error).message).not.toContain("INTERNAL_PRIVATE_CODE");
    expect((error as Error).message).not.toContain("RAW_PRIVATE_TEXT");
  });

  it("maps a network failure to a safe request error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("RAW_NETWORK_DETAIL")));

    const error = await getActiveModelPassport(API_BASE_URL).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ModelPassportRequestError);
    expect(error).toMatchObject({ status: null, retryable: true });
    expect((error as Error).message).not.toContain("RAW_NETWORK_DETAIL");
  });

  it("maps malformed JSON in a successful response to unsupported contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("{not-json", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(getActiveModelPassport(API_BASE_URL)).rejects.toBeInstanceOf(
      UnsupportedModelPassportContractError,
    );
  });

  it("maps malformed JSON in a failed response to a safe request error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("{not-json", {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(getActiveModelPassport(API_BASE_URL)).rejects.toBeInstanceOf(
      ModelPassportRequestError,
    );
  });
});
