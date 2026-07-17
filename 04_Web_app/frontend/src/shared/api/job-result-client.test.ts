import { afterEach, describe, expect, it, vi } from "vitest";
import type { JobResultViewV1, ScenarioId } from "./generated/job-result-view-v1";
import type { ScenarioMediaPlanV1 } from "./generated/scenario-media-plan-v1";
import {
  getJobResultView,
  getScenarioMediaPlan,
  JobResultInconsistentError,
  JobResultNotFoundError,
  JobResultNotReadyError,
  JobResultRequestError,
  JobResultUnavailableError,
  MediaPlanQueryUnsupportedError,
  MediaPlanRequestError,
  MediaPlanUnavailableError,
  normalizeScenarioMediaPlanQuery,
  parseJobResultView,
  parseScenarioMediaPlan,
  resolveArtifactDownloadUrl,
  UnsupportedJobResultContractError,
  UnsupportedScenarioMediaPlanContractError,
} from "./job-result-client";
import {
  createBestRawJobResultFixture,
  createJobResultViewFixture,
  createNoSafeJobResultFixture,
  createRecommendedJobResultFixture,
  createReportFailedJobResultFixture,
  createUnavailableJobResultFixture,
  createScenarioMediaPlanFixture,
  JOB_RESULT_FIXTURE_IDS,
} from "../../test/jobResultFixtures";

const API_BASE_URL = "http://127.0.0.1:8765/";
const { jobId: JOB_ID } = JOB_RESULT_FIXTURE_IDS;

type MutableRecord = Record<string, unknown>;

function asRecord(value: unknown): MutableRecord {
  return value as MutableRecord;
}

function resultFixture(): JobResultViewV1 {
  return structuredClone(createRecommendedJobResultFixture());
}

function planFixture(
  scenarioId: ScenarioId = "S06",
  options: { page?: number; pageSize?: number; channel?: string | null; geo?: string | null } = {},
): ScenarioMediaPlanV1 {
  return structuredClone(createScenarioMediaPlanFixture({
    resultView: resultFixture(),
    scenarioId,
    ...options,
  }));
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function productErrorResponse(code: string, status: number): Response {
  return jsonResponse({
    error: {
      code,
      display_text: "Контролируемое состояние.",
      retryable: code === "RESOURCE_NOT_READY",
      user_action: "Следуйте инструкции на экране.",
    },
  }, status);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("job result-view runtime parser", () => {
  it("accepts the exact v1 product projection and preserves zero values", () => {
    const value = resultFixture();
    const turnover = value.scenarios[5].metrics.incremental_turnover_rub;
    turnover.p10 = 0;
    turnover.p50 = 0;
    turnover.p90 = 0;
    const range = value.overview.scenario_range.rows.find((row) => row.scenario_id === "S06");
    if (!range) throw new Error("Test fixture S06 range is missing");
    range.p10 = 0;
    range.p50 = 0;
    range.p90 = 0;
    const headline = value.overview.headline_metrics[0];
    headline.p10 = 0;
    headline.p50 = 0;
    headline.p90 = 0;

    expect(parseJobResultView(value, JOB_ID)).toBe(value);
    expect(value.scenarios[5].metrics.incremental_turnover_rub.p50).toBe(0);
  });

  it("accepts honest no-safe, unavailable and report-failed states without synthesizing values", () => {
    const noSafe = createNoSafeJobResultFixture();
    const unavailable = createUnavailableJobResultFixture();
    const reportFailed = createReportFailedJobResultFixture();

    expect(parseJobResultView(noSafe, JOB_ID).recommendation.scenario_id).toBeNull();
    expect(parseJobResultView(unavailable, JOB_ID).scenarios[5].metrics.incremental_turnover_rub.p50).toBeNull();
    expect(parseJobResultView(reportFailed, JOB_ID).report.artifact).toBeNull();
  });

  it("accepts a future ready working media-plan only when both published views match", () => {
    const value = resultFixture();
    const workingPlan = {
      status: "ready" as const,
      display_text: "Рабочий медиаплан готов.",
      artifact: {
        artifact_id: "artifact_1234567890abcdef",
        display_name: "working_media_plan.xlsx",
        media_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes: 32_768,
        sha256: "c".repeat(64),
        download_path: "/api/v1/artifacts/artifact_1234567890abcdef/download",
      },
    };
    value.media_plan.working_media_plan = structuredClone(workingPlan);
    value.report.working_media_plan = structuredClone(workingPlan);
    expect(parseJobResultView(value, JOB_ID).report.working_media_plan.status).toBe("ready");

    const mismatched = structuredClone(value);
    mismatched.media_plan.working_media_plan.display_text = "Другая публикация.";
    expect(() => parseJobResultView(mismatched, JOB_ID)).toThrow(UnsupportedJobResultContractError);
  });

  it.each([
    ["unknown contract", (value: MutableRecord) => { value.contract_name = "job_result_view_v2"; }],
    ["extra top-level field", (value: MutableRecord) => { value.internal_path = "private"; }],
    ["route job mismatch", (value: MutableRecord) => { value.job_id = "job_ffffffffffff"; }],
    ["absolute workstation path", (value: MutableRecord) => {
      const limitations = value.limitations as MutableRecord[];
      limitations[0].display_text = "/Users/example/private";
    }],
    ["scenario order drift", (value: MutableRecord) => {
      const scenarios = value.scenarios as unknown[];
      [scenarios[0], scenarios[1]] = [scenarios[1], scenarios[0]];
    }],
    ["duplicate safe rank", (value: MutableRecord) => {
      const scenarios = value.scenarios as MutableRecord[];
      scenarios[1].safe_rank = scenarios[0].safe_rank;
    }],
    ["out-of-order quantiles", (value: MutableRecord) => {
      const scenarios = value.scenarios as MutableRecord[];
      const metrics = asRecord(scenarios[0].metrics);
      asRecord(metrics.incremental_turnover_rub).p10 = 99_000_000;
    }],
    ["zero in unavailable metric", (value: MutableRecord) => {
      const scenarios = value.scenarios as MutableRecord[];
      const metrics = asRecord(scenarios[0].metrics);
      asRecord(metrics.avg_basket_delta_rub).p50 = 0;
    }],
    ["scenario budget mismatch", (value: MutableRecord) => {
      const scenarios = value.scenarios as MutableRecord[];
      asRecord(scenarios[5].budget).unallocated_budget_rub = 0;
    }],
    ["aggregate mismatch", (value: MutableRecord) => {
      const overview = asRecord(value.overview);
      const row = (overview.channel_summary as MutableRecord[])[0];
      row.selected_budget_rub = (row.selected_budget_rub as number) + 100;
    }],
    ["recommendation flag mismatch", (value: MutableRecord) => {
      const scenarios = value.scenarios as MutableRecord[];
      scenarios[5].is_recommended = false;
    }],
    ["invented reliability score", (value: MutableRecord) => {
      asRecord(value.reliability).score = 8;
    }],
    ["non-canonical report artifact", (value: MutableRecord) => {
      const report = asRecord(value.report);
      asRecord(report.artifact).download_path = "/api/v1/artifacts/artifact_ffffffffffff/download";
    }],
    ["invented map points", (value: MutableRecord) => {
      const mediaPlan = asRecord(value.media_plan);
      asRecord(mediaPlan.map).geo_points = [];
    }],
  ])("rejects %s", (_name, mutate) => {
    const value = resultFixture() as unknown as MutableRecord;
    mutate(value);
    expect(() => parseJobResultView(value, JOB_ID)).toThrow(UnsupportedJobResultContractError);
  });

  it("requires canonical S01 source, S05 benchmark and recommendation-selected overview", () => {
    const source = resultFixture();
    source.overview.source_scenario_id = "S05" as "S01";
    expect(() => parseJobResultView(source, JOB_ID)).toThrow(UnsupportedJobResultContractError);

    const selected = resultFixture();
    selected.overview.selected_scenario_id = "S05";
    expect(() => parseJobResultView(selected, JOB_ID)).toThrow(UnsupportedJobResultContractError);
  });

  it("enforces the optional best-raw scenario flag without inventing a displayed candidate", () => {
    const unflaggedAvailable = createBestRawJobResultFixture();
    expect(unflaggedAvailable.scenarios.every((scenario) => !scenario.is_best_raw)).toBe(true);
    expect(parseJobResultView(unflaggedAvailable, JOB_ID).best_raw.available).toBe(true);

    const matchingFlag = createBestRawJobResultFixture();
    matchingFlag.scenarios[5].is_best_raw = true;
    matchingFlag.best_raw.raw_rank = matchingFlag.scenarios[5].raw_rank;
    matchingFlag.best_raw.safe_rank = matchingFlag.scenarios[5].safe_rank;
    expect(parseJobResultView(matchingFlag, JOB_ID).scenarios[5].is_best_raw).toBe(true);

    const mismatchedRanks = structuredClone(matchingFlag);
    mismatchedRanks.best_raw.safe_rank = 99;
    expect(() => parseJobResultView(mismatchedRanks, JOB_ID)).toThrow(UnsupportedJobResultContractError);

    const duplicateFlags = structuredClone(matchingFlag);
    duplicateFlags.scenarios[4].is_best_raw = true;
    expect(() => parseJobResultView(duplicateFlags, JOB_ID)).toThrow(UnsupportedJobResultContractError);

    const wrongScenario = createBestRawJobResultFixture();
    wrongScenario.scenarios[4].is_best_raw = true;
    expect(() => parseJobResultView(wrongScenario, JOB_ID)).toThrow(UnsupportedJobResultContractError);

    const canonicalRecommendedS6 = resultFixture();
    canonicalRecommendedS6.scenarios[5].is_best_raw = true;
    expect(parseJobResultView(canonicalRecommendedS6, JOB_ID).best_raw.available).toBe(false);

    const recommendedS5 = createJobResultViewFixture({ recommendedScenarioId: "S05" });
    recommendedS5.scenarios[5].is_best_raw = true;
    expect(() => parseJobResultView(recommendedS5, JOB_ID)).toThrow(UnsupportedJobResultContractError);
  });
});

describe("scenario media-plan runtime parser", () => {
  it("accepts the exact page and cross-checks it against result-view", () => {
    const result = resultFixture();
    const value = planFixture();
    expect(parseScenarioMediaPlan(value, JOB_ID, result, { scenarioId: "S06" })).toBe(value);
  });

  it("accepts an empty exact filter result without turning global totals into zero", () => {
    const result = resultFixture();
    const value = planFixture("S06", { channel: "Неизвестный канал" });
    expect(value.rows).toEqual([]);
    expect(parseScenarioMediaPlan(value, JOB_ID, result, {
      scenarioId: "S06",
      channel: "Неизвестный канал",
    }).totals.selected_budget_rub).toBeGreaterThan(0);
  });

  it.each([
    ["result id mismatch", (value: MutableRecord) => { value.result_id = "result_ffffffffffff"; }],
    ["scenario mismatch", (value: MutableRecord) => { asRecord(value.scenario).scenario_id = "S05"; }],
    ["rank mismatch", (value: MutableRecord) => { asRecord(value.scenario).safe_rank = 99; }],
    ["filter echo mismatch", (value: MutableRecord) => { asRecord(value.filters).channel = "Другой"; }],
    ["pagination mismatch", (value: MutableRecord) => { asRecord(value.pagination).total_pages = 7; }],
    ["row order mismatch", (value: MutableRecord) => {
      const rows = value.rows as unknown[];
      [rows[0], rows[1]] = [rows[1], rows[0]];
    }],
    ["row share mismatch", (value: MutableRecord) => {
      (value.rows as MutableRecord[])[0].selected_budget_share = 0;
    }],
    ["requested budget mismatch", (value: MutableRecord) => {
      asRecord(value.totals).requested_budget_rub = 42;
    }],
    ["aggregate mismatch", (value: MutableRecord) => {
      const aggregates = asRecord(value.aggregates);
      const row = (aggregates.by_channel as MutableRecord[])[0];
      row.selected_budget_rub = (row.selected_budget_rub as number) + 10;
    }],
    ["daily rows invented", (value: MutableRecord) => {
      const aggregates = asRecord(value.aggregates);
      asRecord(aggregates.by_date).rows = [];
    }],
    ["map invented", (value: MutableRecord) => { asRecord(value.map).status = "ready"; }],
    ["working XLSX invented", (value: MutableRecord) => {
      asRecord(value.working_media_plan).artifact = {};
    }],
    ["local path leaked", (value: MutableRecord) => {
      (value.limitations as MutableRecord[])[0].display_text = "file:///private/result.csv";
    }],
  ])("rejects %s", (_name, mutate) => {
    const result = resultFixture();
    const value = planFixture() as unknown as MutableRecord;
    mutate(value);
    expect(() => parseScenarioMediaPlan(value, JOB_ID, result, { scenarioId: "S06" })).toThrow(
      UnsupportedScenarioMediaPlanContractError,
    );
  });

  it("rejects query values outside the published contract before a request", () => {
    expect(() => normalizeScenarioMediaPlanQuery({ scenarioId: "S06", page: 0 })).toThrow(MediaPlanQueryUnsupportedError);
    expect(() => normalizeScenarioMediaPlanQuery({ scenarioId: "S06", pageSize: 501 })).toThrow(MediaPlanQueryUnsupportedError);
    expect(() => normalizeScenarioMediaPlanQuery({ scenarioId: "S06", channel: "" })).toThrow(MediaPlanQueryUnsupportedError);
  });
});

describe("result and media-plan HTTP clients", () => {
  it("uses only result-view and validates the successful response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(resultFixture()));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getJobResultView(JOB_ID, undefined, API_BASE_URL)).resolves.toMatchObject({ job_id: JOB_ID });
    expect(fetchMock).toHaveBeenCalledWith(
      `http://127.0.0.1:8765/api/v1/jobs/${JOB_ID}/result-view`,
      expect.objectContaining({
        credentials: "include",
        headers: { Accept: "application/json" },
      }),
    );
  });

  it("uses only media-plan and sends canonical query parameter names", async () => {
    const result = resultFixture();
    const value = planFixture("S05", { page: 2, pageSize: 1, channel: "Онлайн-видео", geo: "Москва" });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(value));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getScenarioMediaPlan(JOB_ID, {
      scenarioId: "S05",
      page: 2,
      pageSize: 1,
      channel: "Онлайн-видео",
      geo: "Москва",
    }, result, undefined, API_BASE_URL)).resolves.toMatchObject({ scenario: { scenario_id: "S05" } });
    expect(fetchMock).toHaveBeenCalledWith(
      `http://127.0.0.1:8765/api/v1/jobs/${JOB_ID}/media-plan?scenario_id=S05&page=2&page_size=1&channel=${encodeURIComponent("Онлайн-видео")}&geo=${encodeURIComponent("Москва")}`,
      expect.objectContaining({
        credentials: "include",
        headers: { Accept: "application/json" },
      }),
    );
  });

  it.each([
    [404, JobResultNotFoundError, "JOB_NOT_FOUND"],
    [409, JobResultInconsistentError, undefined],
    [503, JobResultUnavailableError, undefined],
    [500, JobResultRequestError, undefined],
  ])("maps result HTTP %i without exposing payload details", async (status, errorType, code) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(code
      ? productErrorResponse(code, status)
      : jsonResponse({ private: "SECRET" }, status)));
    const error = await getJobResultView(JOB_ID, undefined, API_BASE_URL).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(errorType);
    expect((error as Error).message).not.toContain("SECRET");
  });

  it.each([
    [404, JobResultNotFoundError, "JOB_NOT_FOUND"],
    [409, JobResultInconsistentError, undefined],
    [422, MediaPlanQueryUnsupportedError, undefined],
    [503, MediaPlanUnavailableError, undefined],
    [500, MediaPlanRequestError, undefined],
  ])("maps media-plan HTTP %i without exposing payload details", async (status, errorType, code) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(code
      ? productErrorResponse(code, status)
      : jsonResponse({ private: "SECRET" }, status)));
    const error = await getScenarioMediaPlan(JOB_ID, { scenarioId: "S06" }, resultFixture(), undefined, API_BASE_URL)
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(errorType);
    expect((error as Error).message).not.toContain("SECRET");
  });

  it("distinguishes RESOURCE_NOT_READY from JOB_NOT_FOUND for both endpoints", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(productErrorResponse("RESOURCE_NOT_READY", 404)));
    await expect(getJobResultView(JOB_ID, undefined, API_BASE_URL)).rejects.toBeInstanceOf(JobResultNotReadyError);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(productErrorResponse("RESOURCE_NOT_READY", 404)));
    await expect(getScenarioMediaPlan(JOB_ID, { scenarioId: "S06" }, resultFixture(), undefined, API_BASE_URL))
      .rejects.toBeInstanceOf(JobResultNotReadyError);
  });

  it("fails closed for malformed and unknown 404 envelopes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error: { code: "JOB_NOT_FOUND" } }, 404)));
    await expect(getJobResultView(JOB_ID, undefined, API_BASE_URL)).rejects.toBeInstanceOf(
      UnsupportedJobResultContractError,
    );

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(productErrorResponse("ROUTE_NOT_FOUND", 404)));
    await expect(getJobResultView(JOB_ID, undefined, API_BASE_URL)).rejects.toBeInstanceOf(JobResultRequestError);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error: null }, 404)));
    await expect(getScenarioMediaPlan(JOB_ID, { scenarioId: "S06" }, resultFixture(), undefined, API_BASE_URL))
      .rejects.toBeInstanceOf(UnsupportedScenarioMediaPlanContractError);
  });

  it("maps network and malformed JSON to controlled errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new Error("PRIVATE_NETWORK")));
    await expect(getJobResultView(JOB_ID, undefined, API_BASE_URL)).rejects.toBeInstanceOf(JobResultRequestError);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response("{bad", { status: 200 })));
    await expect(getJobResultView(JOB_ID, undefined, API_BASE_URL)).rejects.toBeInstanceOf(UnsupportedJobResultContractError);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response("{bad", { status: 200 })));
    await expect(getScenarioMediaPlan(JOB_ID, { scenarioId: "S06" }, resultFixture(), undefined, API_BASE_URL))
      .rejects.toBeInstanceOf(UnsupportedScenarioMediaPlanContractError);
  });
});

describe("artifact download URL resolver", () => {
  const canonicalPath = "/api/v1/artifacts/artifact_abcdef123456/download";

  it("resolves only a canonical relative artifact endpoint against the configured API base", () => {
    expect(resolveArtifactDownloadUrl(canonicalPath, API_BASE_URL)).toBe(
      "http://127.0.0.1:8765/api/v1/artifacts/artifact_abcdef123456/download",
    );
  });

  it("keeps a canonical relative path for the intentional same-origin empty base", () => {
    expect(resolveArtifactDownloadUrl(canonicalPath, "")).toBe(canonicalPath);
  });

  it.each([
    "https://evil.example/api/v1/artifacts/artifact_abcdef123456/download",
    "//evil.example/api/v1/artifacts/artifact_abcdef123456/download",
    "file:///Users/example/report.xlsx",
    "/Users/example/report.xlsx",
    "/api/v1/artifacts/artifact_abcdef123456/download?token=secret",
    "/api/v1/jobs/job_abcdef123456/result",
  ])("rejects unsafe or non-canonical path %s", (path) => {
    expect(() => resolveArtifactDownloadUrl(path, API_BASE_URL)).toThrow(UnsupportedJobResultContractError);
  });

  it("rejects unsafe base URL schemes and credentials", () => {
    expect(() => resolveArtifactDownloadUrl(canonicalPath, "file:///tmp"))
      .toThrow(UnsupportedJobResultContractError);
    expect(() => resolveArtifactDownloadUrl(canonicalPath, "https://user:password@example.com"))
      .toThrow(UnsupportedJobResultContractError);
  });
});
