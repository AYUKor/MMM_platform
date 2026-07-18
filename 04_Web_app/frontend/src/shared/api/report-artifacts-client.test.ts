import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getJobReportArtifacts,
  parseJobReportArtifacts,
  ReportArtifactsRequestError,
  resolveReportArtifactDownloadUrl,
  UnsupportedReportArtifactsContractError,
} from "./report-artifacts-client";

const API_BASE_URL = "http://127.0.0.1:8765";
const JOB_ID = "job_1234567890abcdef";
const RESULT_ID = "result_1234567890abcdef";
const REPORT_ARTIFACT_ID = "artifact_1234567890abcdef";
const WORKING_ARTIFACT_ID = "artifact_fedcba0987654321";
const XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
type MutableRecord = Record<string, unknown>;

function artifact(id = REPORT_ARTIFACT_ID, displayName = "mmm_report.xlsx") {
  return {
    artifact_id: id,
    display_name: displayName,
    media_type: XLSX_MEDIA_TYPE,
    size_bytes: 12_887,
    sha256: "a".repeat(64),
    download_path: `/api/v1/artifacts/${id}/download`,
  };
}

function payload(status: "ready" | "failed" | "unavailable" = "ready"): MutableRecord {
  const ready = status === "ready";
  return {
    contract_name: "job_result_view_v1",
    schema_version: "1.0.0",
    record_origin: "sanitized_fixture",
    job_id: JOB_ID,
    result_id: RESULT_ID,
    campaign: { total_budget_rub: 999_999_999 },
    recommendation: { scenario_id: "S06" },
    scenarios: [{ metrics: { roas: { p50: 999 } } }],
    report: {
      status,
      display_text: ready ? "Excel-отчет готов." : status === "failed" ? "Отчет не сформирован." : "Отчет недоступен.",
      generated_at_utc: ready ? "2026-07-18T10:00:00+00:00" : null,
      artifact: ready ? artifact() : null,
      sheets: ready ? [
        { sheet_name: "Summary", title: "Сводка", description: "Основные результаты." },
        { sheet_name: "Media plan", title: "Медиаплан", description: null },
      ] : [],
      working_media_plan: {
        status: "unavailable",
        display_text: "Рабочий медиаплан недоступен.",
        artifact: null,
      },
    },
  };
}

function report(value: MutableRecord): MutableRecord {
  return value.report as MutableRecord;
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("report artifact parser", () => {
  it("projects only report metadata and drops every legacy semantic field", () => {
    const parsed = parseJobReportArtifacts(payload(), JOB_ID, RESULT_ID);

    expect(parsed).toEqual({
      status: "ready",
      displayText: "Excel-отчет готов.",
      generatedAtUtc: "2026-07-18T10:00:00+00:00",
      artifact: {
        artifactId: REPORT_ARTIFACT_ID,
        displayName: "mmm_report.xlsx",
        sizeBytes: 12_887,
        downloadPath: `/api/v1/artifacts/${REPORT_ARTIFACT_ID}/download`,
      },
      sheets: [
        { sheetName: "Summary", title: "Сводка", description: "Основные результаты." },
        { sheetName: "Media plan", title: "Медиаплан", description: null },
      ],
      workingMediaPlan: {
        status: "unavailable",
        displayText: "Рабочий медиаплан недоступен.",
        artifact: null,
      },
    });
    expect(JSON.stringify(parsed)).not.toMatch(/campaign|recommendation|scenario|roas|999999999/);
    expect(parsed.artifact).not.toHaveProperty("sha256");
    expect(parsed.artifact).not.toHaveProperty("mediaType");
  });

  it.each(["failed", "unavailable"] as const)("accepts an honest %s report state", (status) => {
    const parsed = parseJobReportArtifacts(payload(status), JOB_ID, RESULT_ID);
    expect(parsed).toMatchObject({ status, artifact: null, sheets: [], generatedAtUtc: null });
  });

  it("projects a separately published working media-plan artifact", () => {
    const value = payload();
    report(value).working_media_plan = {
      status: "ready",
      display_text: "Рабочий медиаплан готов.",
      artifact: artifact(WORKING_ARTIFACT_ID, "working_media_plan.xlsx"),
    };

    expect(parseJobReportArtifacts(value, JOB_ID, RESULT_ID).workingMediaPlan).toEqual({
      status: "ready",
      displayText: "Рабочий медиаплан готов.",
      artifact: {
        artifactId: WORKING_ARTIFACT_ID,
        displayName: "working_media_plan.xlsx",
        sizeBytes: 12_887,
        downloadPath: `/api/v1/artifacts/${WORKING_ARTIFACT_ID}/download`,
      },
    });
  });

  it("accepts a safe extensionless display label while keeping XLSX transport strict", () => {
    const value = payload();
    (report(value).artifact as MutableRecord).display_name = "Отчет для маркетолога";

    expect(parseJobReportArtifacts(value, JOB_ID, RESULT_ID).artifact?.displayName)
      .toBe("Отчет для маркетолога");
  });

  it.each([
    ["mismatched route artifact", `/api/v1/artifacts/${WORKING_ARTIFACT_ID}/download`],
    ["external URL", `https://evil.example/api/v1/artifacts/${REPORT_ARTIFACT_ID}/download`],
    ["protocol-relative URL", `//evil.example/api/v1/artifacts/${REPORT_ARTIFACT_ID}/download`],
    ["local file URL", "file:///Users/example/report.xlsx"],
    ["POSIX workstation path", "/Users/example/report.xlsx"],
    ["Windows path", "C:\\private\\report.xlsx"],
    ["query string", `/api/v1/artifacts/${REPORT_ARTIFACT_ID}/download?token=secret`],
    ["fragment", `/api/v1/artifacts/${REPORT_ARTIFACT_ID}/download#fragment`],
    ["traversal", `/api/v1/artifacts/../${REPORT_ARTIFACT_ID}/download`],
    ["encoded slash", `/api/v1/artifacts/${REPORT_ARTIFACT_ID}%2fother/download`],
  ])("rejects an unsafe download path: %s", (_name, downloadPath) => {
    const value = payload();
    (report(value).artifact as MutableRecord).download_path = downloadPath;
    expect(() => parseJobReportArtifacts(value, JOB_ID, RESULT_ID))
      .toThrow(UnsupportedReportArtifactsContractError);
  });

  it.each([
    ["absolute display name", (value: MutableRecord) => { (report(value).artifact as MutableRecord).display_name = "/Users/example/report.xlsx"; }],
    ["Windows display name", (value: MutableRecord) => { (report(value).artifact as MutableRecord).display_name = "C:\\private\\report.xlsx"; }],
    ["path separator in display name", (value: MutableRecord) => { (report(value).artifact as MutableRecord).display_name = "reports/report.xlsx"; }],
    ["wrong media type", (value: MutableRecord) => { (report(value).artifact as MutableRecord).media_type = "text/csv"; }],
    ["invalid hash", (value: MutableRecord) => { (report(value).artifact as MutableRecord).sha256 = "abc"; }],
    ["negative size", (value: MutableRecord) => { (report(value).artifact as MutableRecord).size_bytes = -1; }],
    ["ready without artifact", (value: MutableRecord) => { report(value).artifact = null; }],
    ["ready without sheets", (value: MutableRecord) => { report(value).sheets = []; }],
    ["duplicate sheet", (value: MutableRecord) => { const sheets = report(value).sheets as MutableRecord[]; sheets.push(structuredClone(sheets[0])); }],
    ["local path in sheet text", (value: MutableRecord) => { ((report(value).sheets as MutableRecord[])[0]).description = "Файл:/private/tmp/report.xlsx"; }],
    ["root path in report text", (value: MutableRecord) => { report(value).display_text = "Файл /root/report.xlsx"; }],
    ["data path in sheet title", (value: MutableRecord) => { ((report(value).sheets as MutableRecord[])[0]).title = "/data/report.xlsx"; }],
    ["app path in availability text", (value: MutableRecord) => { (report(value).working_media_plan as MutableRecord).display_text = "Файл /app/report.xlsx"; }],
    ["home-relative path", (value: MutableRecord) => { ((report(value).sheets as MutableRecord[])[0]).description = "Файл ~/report.xlsx"; }],
    ["relative workstation path", (value: MutableRecord) => { ((report(value).sheets as MutableRecord[])[0]).description = "Файл ../report.xlsx"; }],
    ["unexpected report key", (value: MutableRecord) => { report(value).total_budget_rub = 100; }],
    ["unexpected artifact key", (value: MutableRecord) => { (report(value).artifact as MutableRecord).storage_key = "private/report.xlsx"; }],
  ])("fails closed on %s", (_name, mutate) => {
    const value = payload();
    mutate(value);
    expect(() => parseJobReportArtifacts(value, JOB_ID, RESULT_ID))
      .toThrow(UnsupportedReportArtifactsContractError);
  });

  it("requires the v1 header to match the validated v2 job and result identities", () => {
    expect(() => parseJobReportArtifacts(payload(), "job_ffffffffffffffff", RESULT_ID))
      .toThrow(UnsupportedReportArtifactsContractError);
    expect(() => parseJobReportArtifacts(payload(), JOB_ID, "result_ffffffffffffffff"))
      .toThrow(UnsupportedReportArtifactsContractError);
    const value = payload();
    value.contract_name = "job_result_view_v2";
    expect(() => parseJobReportArtifacts(value, JOB_ID, RESULT_ID))
      .toThrow(UnsupportedReportArtifactsContractError);
  });
});

describe("report artifact download URL", () => {
  const parsedArtifact = parseJobReportArtifacts(payload(), JOB_ID, RESULT_ID).artifact!;

  it("resolves only the canonical path against the configured API origin", () => {
    expect(resolveReportArtifactDownloadUrl(parsedArtifact, API_BASE_URL)).toBe(
      `${API_BASE_URL}/api/v1/artifacts/${REPORT_ARTIFACT_ID}/download`,
    );
    expect(resolveReportArtifactDownloadUrl(parsedArtifact, "")).toBe(parsedArtifact.downloadPath);
  });

  it.each([
    "file:///tmp",
    "https://user:password@example.com",
    "https://example.com/base",
    "https://example.com?token=secret",
    "https://example.com?",
    "https://example.com#",
    " https://example.com",
  ])("rejects unsafe API base %s", (baseUrl) => {
    expect(() => resolveReportArtifactDownloadUrl(parsedArtifact, baseUrl))
      .toThrow(UnsupportedReportArtifactsContractError);
  });

  it("revalidates the projected artifact instead of trusting TypeScript", () => {
    expect(() => resolveReportArtifactDownloadUrl(
      { ...parsedArtifact, artifactId: WORKING_ARTIFACT_ID },
      API_BASE_URL,
    )).toThrow(UnsupportedReportArtifactsContractError);
  });
});

describe("report artifact getter", () => {
  it("uses the narrow v1 view path with a credentialed request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload()));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getJobReportArtifacts(JOB_ID, RESULT_ID, undefined, API_BASE_URL))
      .resolves.toMatchObject({ status: "ready" });
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE_URL}/api/v1/jobs/${JOB_ID}/result-view`,
      {
        credentials: "include",
        headers: { Accept: "application/json" },
        signal: undefined,
      },
    );
  });

  it("maps a malformed successful payload to an unsupported contract", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ report: {} })));
    const error = await getJobReportArtifacts(JOB_ID, RESULT_ID, undefined, API_BASE_URL)
      .catch((value: unknown) => value);
    expect(error).toBeInstanceOf(UnsupportedReportArtifactsContractError);
    expect(error).toMatchObject({ status: 200 });
  });

  it("maps HTTP and network failures to safe request errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ private: "RAW_BACKEND_TEXT" }, 503)));
    const httpError = await getJobReportArtifacts(JOB_ID, RESULT_ID, undefined, API_BASE_URL)
      .catch((value: unknown) => value);
    expect(httpError).toBeInstanceOf(ReportArtifactsRequestError);
    expect(httpError).toMatchObject({ status: 503, retryable: true });
    expect((httpError as Error).message).not.toContain("RAW_BACKEND_TEXT");

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("RAW_NETWORK_TEXT")));
    const networkError = await getJobReportArtifacts(JOB_ID, RESULT_ID, undefined, API_BASE_URL)
      .catch((value: unknown) => value);
    expect(networkError).toBeInstanceOf(ReportArtifactsRequestError);
    expect(networkError).toMatchObject({ status: null, retryable: true });
    expect((networkError as Error).message).not.toContain("RAW_NETWORK_TEXT");
  });

  it("fails before a request when route identities are not opaque", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(getJobReportArtifacts("../job", RESULT_ID, undefined, API_BASE_URL))
      .rejects.toBeInstanceOf(UnsupportedReportArtifactsContractError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
