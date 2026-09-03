import { describe, expect, it } from "vitest";
import { adaptValidationGeoBudget } from "../features/geo-budget-map/geoBudgetMapModel";
import { parseValidationViewV2 } from "../shared/api/business-semantics-client";
import d1r2FederalPayload from "./fixtures/d1r2-production-validation_b30b5467e757248ef0b1.json";
import {
  analyzeValidationTrace,
  type AnalyzeValidationTraceInput,
} from "./validationAcceptanceTrace";

const VALIDATION_ID = "validation_1f1be143ce746638c5da";
const RESPONSE_URL = `https://mmm.x5.ru/api/v1/validations/${VALIDATION_ID}/view-v2`;
const ROUTE_URL = `https://mmm.x5.ru/calculations/new?validationId=${VALIDATION_ID}&step=review`;
const runtime = { parseValidationViewV2, adaptValidationGeoBudget };
const exactD1r4cSemanticObject = {
  ...d1r2FederalPayload,
  validation_id: VALIDATION_ID,
};

function input(overrides: Partial<AnalyzeValidationTraceInput> = {}): AnalyzeValidationTraceInput {
  const rawBody = JSON.stringify(exactD1r4cSemanticObject);
  return {
    scenario: "D1R4-C exact reconstructed federal payload",
    capturedAtUtc: "2026-09-03T00:00:00.000Z",
    method: "GET",
    responseUrl: RESPONSE_URL,
    httpStatus: 200,
    rawBody,
    rawBodySha256: "a".repeat(64),
    rawBodyBytes: new TextEncoder().encode(rawBody).byteLength,
    browserRouteUrl: ROUTE_URL,
    ...overrides,
  };
}

describe("validation acceptance response binding", () => {
  it("accepts the exact reconstructed D1R4-C payload before DOM assertions", () => {
    const analysis = analyzeValidationTrace(input(), runtime);

    expect(analysis.ok).toBe(true);
    if (!analysis.ok) return;
    expect(analysis.validation).toMatchObject({
      validation_id: VALIDATION_ID,
      job_creation_allowed: true,
      federal_allocation: {
        status: "available",
        declared_geo_count: 211,
        ready_geo_count: 175,
        excluded_geo_count: 36,
        allocated_budget_rub: 100_000_000,
        difference_rub: 0,
      },
    });
    expect(analysis.evidence.contract_parse.status).toBe("pass");
    expect(analysis.evidence.projection).toMatchObject({
      status: "pass",
      validation_id: VALIDATION_ID,
      requested_budget_rub: 100_000_000,
      points_n: 175,
    });
    expect(analysis.evidence.browser_route.status).toBe("pass");
  });

  it("fails on a stale browser route even when the payload parses and projects", () => {
    const analysis = analyzeValidationTrace(input({
      browserRouteUrl: "https://mmm.x5.ru/calculations/new?validationId=validation_stale1234567890&step=review",
    }), runtime);

    expect(analysis.ok).toBe(false);
    expect(analysis.evidence.contract_parse.status).toBe("pass");
    expect(analysis.evidence.projection.status).toBe("pass");
    expect(analysis.evidence.browser_route.status).toBe("fail");
    expect(analysis.evidence.failure?.stage).toBe("browser_route");
  });

  it("fails closed when the response URL and payload validation ids differ", () => {
    const payload = { ...exactD1r4cSemanticObject, validation_id: "validation_unrelated123456" };
    const rawBody = JSON.stringify(payload);
    const analysis = analyzeValidationTrace(input({
      rawBody,
      rawBodyBytes: new TextEncoder().encode(rawBody).byteLength,
    }), runtime);

    expect(analysis.ok).toBe(false);
    expect(analysis.evidence.failure?.stage).toBe("contract_parse");
    expect(analysis.evidence.browser_route.status).toBe("not_run");
  });

  it("records HTTP failures without attributing a generic DOM state to the payload", () => {
    const analysis = analyzeValidationTrace(input({ httpStatus: 503 }), runtime);

    expect(analysis.ok).toBe(false);
    expect(analysis.evidence.failure?.stage).toBe("http_status");
    expect(analysis.evidence.contract_parse.status).toBe("not_run");
    expect(analysis.evidence.projection.status).toBe("not_run");
    expect(analysis.evidence.browser_route.status).toBe("not_run");
  });
});
