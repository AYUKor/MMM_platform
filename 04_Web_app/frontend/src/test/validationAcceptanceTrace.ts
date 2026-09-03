import type { ValidationResultV2 } from "../shared/api/generated/validation-result-v2";

const VALIDATION_VIEW_PATH = /^\/api\/v1\/validations\/(validation_[a-z0-9]+)\/view-v2$/;
const SHA256 = /^[a-f0-9]{64}$/;

export type ValidationTraceFailureStage =
  | "response_url"
  | "http_status"
  | "raw_json"
  | "contract_parse"
  | "projection"
  | "browser_route";

export interface ValidationTraceEvidence {
  scenario: string;
  captured_at_utc: string;
  api: {
    method: string;
    url: string;
    validation_id: string | null;
  };
  http: {
    status: number;
    raw_body_sha256: string;
    raw_body_bytes: number;
  };
  contract_parse: {
    status: "pass" | "fail" | "not_run";
    contract_name: string | null;
    schema_version: string | null;
    validation_id: string | null;
    job_creation_allowed: boolean | null;
    federal_status: string | null;
    federal_warnings_n: number | null;
  };
  projection: {
    status: "pass" | "fail" | "not_run";
    validation_id: string | null;
    requested_budget_rub: number | null;
    points_n: number | null;
  };
  browser_route: {
    status: "pass" | "fail" | "not_run";
    url: string;
    validation_id: string | null;
  };
  failure: {
    stage: ValidationTraceFailureStage;
    error_name: string;
    message: string;
    stack: string | null;
  } | null;
}

export type ValidationTraceAnalysis =
  | {
    ok: true;
    evidence: ValidationTraceEvidence;
    validation: ValidationResultV2;
  }
  | {
    ok: false;
    evidence: ValidationTraceEvidence;
  };

export interface AnalyzeValidationTraceInput {
  scenario: string;
  capturedAtUtc: string;
  method: string;
  responseUrl: string;
  httpStatus: number;
  rawBody: string;
  rawBodySha256: string;
  rawBodyBytes: number;
  browserRouteUrl: string;
}

export interface ValidationTraceRuntime {
  parseValidationViewV2: (value: unknown, expectedValidationId: string) => ValidationResultV2;
  adaptValidationGeoBudget: (value: ValidationResultV2) => {
    validationId: string;
    requestedBudgetRub: number;
    points: readonly unknown[];
  };
}

function errorDetails(stage: ValidationTraceFailureStage, error: unknown) {
  const resolved = error instanceof Error ? error : new Error(String(error));
  return {
    stage,
    error_name: resolved.name,
    message: resolved.message,
    stack: resolved.stack ?? null,
  };
}

function routeValidationId(url: string): string | null {
  try {
    return new URL(url).searchParams.get("validationId");
  } catch {
    return null;
  }
}

export function responseValidationId(url: string): string | null {
  try {
    return VALIDATION_VIEW_PATH.exec(new URL(url).pathname)?.[1] ?? null;
  } catch {
    return null;
  }
}

/**
 * Binds one live validation response to the exact parser, map projection and
 * browser route before any DOM message can be used as acceptance evidence.
 */
export function analyzeValidationTrace(
  input: AnalyzeValidationTraceInput,
  runtime: ValidationTraceRuntime,
): ValidationTraceAnalysis {
  const responseId = responseValidationId(input.responseUrl);
  const browserId = routeValidationId(input.browserRouteUrl);
  const evidence: ValidationTraceEvidence = {
    scenario: input.scenario,
    captured_at_utc: input.capturedAtUtc,
    api: {
      method: input.method,
      url: input.responseUrl,
      validation_id: responseId,
    },
    http: {
      status: input.httpStatus,
      raw_body_sha256: input.rawBodySha256,
      raw_body_bytes: input.rawBodyBytes,
    },
    contract_parse: {
      status: "not_run",
      contract_name: null,
      schema_version: null,
      validation_id: null,
      job_creation_allowed: null,
      federal_status: null,
      federal_warnings_n: null,
    },
    projection: {
      status: "not_run",
      validation_id: null,
      requested_budget_rub: null,
      points_n: null,
    },
    browser_route: {
      status: "not_run",
      url: input.browserRouteUrl,
      validation_id: browserId,
    },
    failure: null,
  };

  if (!responseId || input.method !== "GET") {
    evidence.failure = errorDetails(
      "response_url",
      new Error("Response is not an exact GET validation view-v2 request."),
    );
    return { ok: false, evidence };
  }
  const encodedBodyBytes = new TextEncoder().encode(input.rawBody).byteLength;
  if (
    !SHA256.test(input.rawBodySha256)
    || input.rawBodyBytes < 1
    || input.rawBodyBytes !== encodedBodyBytes
  ) {
    evidence.failure = errorDetails(
      "raw_json",
      new Error("Raw response identity is missing, invalid or inconsistent with the body."),
    );
    return { ok: false, evidence };
  }
  if (input.httpStatus !== 200) {
    evidence.failure = errorDetails(
      "http_status",
      new Error(`Expected HTTP 200, received ${input.httpStatus}.`),
    );
    return { ok: false, evidence };
  }

  let rawPayload: unknown;
  try {
    rawPayload = JSON.parse(input.rawBody);
  } catch (error) {
    evidence.failure = errorDetails("raw_json", error);
    return { ok: false, evidence };
  }

  let validation: ValidationResultV2;
  try {
    validation = runtime.parseValidationViewV2(rawPayload, responseId);
    evidence.contract_parse = {
      status: "pass",
      contract_name: validation.contract_name,
      schema_version: validation.schema_version,
      validation_id: validation.validation_id,
      job_creation_allowed: validation.job_creation_allowed,
      federal_status: validation.federal_allocation.status,
      federal_warnings_n: validation.federal_allocation.warnings.length,
    };
  } catch (error) {
    evidence.contract_parse.status = "fail";
    evidence.failure = errorDetails("contract_parse", error);
    return { ok: false, evidence };
  }

  try {
    const projection = runtime.adaptValidationGeoBudget(validation);
    evidence.projection = {
      status: "pass",
      validation_id: projection.validationId,
      requested_budget_rub: projection.requestedBudgetRub,
      points_n: projection.points.length,
    };
  } catch (error) {
    evidence.projection.status = "fail";
    evidence.failure = errorDetails("projection", error);
    return { ok: false, evidence };
  }

  if (browserId !== responseId) {
    evidence.browser_route.status = "fail";
    evidence.failure = errorDetails(
      "browser_route",
      new Error(`Browser route validationId ${browserId ?? "<missing>"} does not match response ${responseId}.`),
    );
    return { ok: false, evidence };
  }
  evidence.browser_route.status = "pass";
  return { ok: true, evidence, validation };
}
