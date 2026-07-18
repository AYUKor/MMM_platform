import { appEnv } from "../config/env";
import { credentialedFetch } from "./credentialed-fetch";

const XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const JOB_ID_RE = /^job_[0-9a-f]{12,64}$/;
const RESULT_ID_RE = /^result_[0-9a-f]{12,64}$/;
const ARTIFACT_ID_RE = /^artifact_[0-9a-f]{12,64}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const DOWNLOAD_PATH_RE = /^\/api\/v1\/artifacts\/(artifact_[0-9a-f]{12,64})\/download$/;
const ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const LOCAL_PATH_RE = /(?:file:\/\/|(?:^|[\s("'=:]|\[)~?\/[^\s/]+|(?:^|[^A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/]|\.{1,2}[\\/]))/i;

const REPORT_KEYS = [
  "status",
  "display_text",
  "generated_at_utc",
  "artifact",
  "sheets",
  "working_media_plan",
] as const;
const SOURCE_ARTIFACT_KEYS = [
  "artifact_id",
  "display_name",
  "media_type",
  "size_bytes",
  "sha256",
  "download_path",
] as const;
const PROJECTED_ARTIFACT_KEYS = [
  "artifactId",
  "displayName",
  "sizeBytes",
  "downloadPath",
] as const;
const AVAILABILITY_KEYS = ["status", "display_text", "artifact"] as const;
const SHEET_KEYS = ["sheet_name", "title", "description"] as const;

type JsonRecord = Record<string, unknown>;

export interface ReportArtifact {
  artifactId: string;
  displayName: string;
  sizeBytes: number;
  downloadPath: string;
}

export interface ReportArtifactAvailability {
  status: "ready" | "unavailable";
  displayText: string;
  artifact: ReportArtifact | null;
}

export interface ReportSheet {
  sheetName: string;
  title: string;
  description: string | null;
}

export interface JobReportArtifacts {
  status: "ready" | "failed" | "unavailable";
  displayText: string;
  generatedAtUtc: string | null;
  artifact: ReportArtifact | null;
  sheets: ReportSheet[];
  workingMediaPlan: ReportArtifactAvailability;
}

export class UnsupportedReportArtifactsContractError extends Error {
  readonly status: number | null;

  constructor(status: number | null = null) {
    super("Сведения об отчете имеют неподдерживаемый формат.");
    this.name = "UnsupportedReportArtifactsContractError";
    this.status = status;
  }
}

export class ReportArtifactsRequestError extends Error {
  readonly status: number | null;
  readonly retryable: boolean;

  constructor(status: number | null = null) {
    super("Не удалось получить сведения об отчете.");
    this.name = "ReportArtifactsRequestError";
    this.status = status;
    this.retryable = status === null || status === 409 || status >= 500;
  }
}

function fail(status: number | null = null): never {
  throw new UnsupportedReportArtifactsContractError(status);
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: JsonRecord, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && expected.every((key) => actual.includes(key));
}

function hasControlCharacter(value: string): boolean {
  return [...value].some((character) => {
    const code = character.charCodeAt(0);
    return code <= 31 || code === 127;
  });
}

function isSafeText(value: unknown, maximum: number): value is string {
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= maximum &&
    value === value.trim() &&
    !hasControlCharacter(value) &&
    !LOCAL_PATH_RE.test(value);
}

function isSafeDisplayName(value: unknown): value is string {
  return isSafeText(value, 255) &&
    value !== "." &&
    value !== ".." &&
    !value.includes("/") &&
    !value.includes("\\");
}

function isIsoDateTime(value: unknown): value is string {
  return typeof value === "string" &&
    ISO_DATETIME_RE.test(value) &&
    Number.isFinite(Date.parse(value));
}

function parseArtifact(value: unknown): ReportArtifact {
  if (!isRecord(value) || !hasExactKeys(value, SOURCE_ARTIFACT_KEYS)) fail();
  const match = typeof value.download_path === "string"
    ? DOWNLOAD_PATH_RE.exec(value.download_path)
    : null;
  if (
    typeof value.artifact_id !== "string" ||
    !ARTIFACT_ID_RE.test(value.artifact_id) ||
    !isSafeDisplayName(value.display_name) ||
    value.media_type !== XLSX_MEDIA_TYPE ||
    !Number.isSafeInteger(value.size_bytes) ||
    (value.size_bytes as number) < 0 ||
    typeof value.sha256 !== "string" ||
    !SHA256_RE.test(value.sha256) ||
    match === null ||
    match[1] !== value.artifact_id
  ) fail();
  return {
    artifactId: value.artifact_id,
    displayName: value.display_name,
    sizeBytes: value.size_bytes as number,
    downloadPath: value.download_path as string,
  };
}

function parseAvailability(value: unknown): ReportArtifactAvailability {
  if (!isRecord(value) || !hasExactKeys(value, AVAILABILITY_KEYS) || !isSafeText(value.display_text, 1_000)) fail();
  if (value.status === "ready") {
    if (value.artifact === null) fail();
    return {
      status: "ready",
      displayText: value.display_text,
      artifact: parseArtifact(value.artifact),
    };
  }
  if (value.status !== "unavailable" || value.artifact !== null) fail();
  return {
    status: "unavailable",
    displayText: value.display_text,
    artifact: null,
  };
}

function parseSheet(value: unknown): ReportSheet {
  if (!isRecord(value) || !hasExactKeys(value, SHEET_KEYS) ||
    !isSafeText(value.sheet_name, 31) || !isSafeText(value.title, 250) ||
    (value.description !== null && !isSafeText(value.description, 1_000))) fail();
  return {
    sheetName: value.sheet_name,
    title: value.title,
    description: value.description as string | null,
  };
}

export function parseJobReportArtifacts(
  value: unknown,
  expectedJobId: string,
  expectedResultId: string,
): JobReportArtifacts {
  if (!JOB_ID_RE.test(expectedJobId) || !RESULT_ID_RE.test(expectedResultId) || !isRecord(value) ||
    value.contract_name !== "job_result_view_v1" || value.schema_version !== "1.0.0" ||
    value.job_id !== expectedJobId || value.result_id !== expectedResultId || !isRecord(value.report) ||
    !hasExactKeys(value.report, REPORT_KEYS)) fail();

  const report = value.report;
  if ((report.status !== "ready" && report.status !== "failed" && report.status !== "unavailable") ||
    !isSafeText(report.display_text, 1_000) ||
    (report.generated_at_utc !== null && !isIsoDateTime(report.generated_at_utc)) ||
    !Array.isArray(report.sheets) || report.sheets.length > 256) fail();

  const artifact = report.artifact === null ? null : parseArtifact(report.artifact);
  const sheets = report.sheets.map(parseSheet);
  const sheetNames = sheets.map((sheet) => sheet.sheetName);
  if (new Set(sheetNames).size !== sheetNames.length) fail();

  if (report.status === "ready") {
    if (artifact === null || sheets.length === 0) fail();
  } else if (artifact !== null || sheets.length !== 0 || report.generated_at_utc !== null) fail();

  return {
    status: report.status,
    displayText: report.display_text,
    generatedAtUtc: report.generated_at_utc as string | null,
    artifact,
    sheets,
    workingMediaPlan: parseAvailability(report.working_media_plan),
  };
}

function apiUrl(path: string, baseUrl: string): string {
  if (baseUrl === "") return path;
  if (baseUrl !== baseUrl.trim() || baseUrl.includes("?") || baseUrl.includes("#")) fail();
  let parsedBase: URL;
  try {
    parsedBase = new URL(baseUrl);
  } catch {
    fail();
  }
  if ((parsedBase.protocol !== "http:" && parsedBase.protocol !== "https:") ||
    parsedBase.username !== "" || parsedBase.password !== "" || parsedBase.search !== "" ||
    parsedBase.hash !== "" || (parsedBase.pathname !== "" && parsedBase.pathname !== "/")) fail();
  const resolved = new URL(path, parsedBase.origin);
  if (resolved.origin !== parsedBase.origin || resolved.pathname !== path || resolved.search !== "" || resolved.hash !== "") fail();
  return resolved.toString();
}

export function resolveReportArtifactDownloadUrl(
  artifact: ReportArtifact,
  baseUrl = appEnv.apiBaseUrl,
): string {
  if (!isRecord(artifact) || !hasExactKeys(artifact, PROJECTED_ARTIFACT_KEYS) ||
    typeof artifact.artifactId !== "string" || !ARTIFACT_ID_RE.test(artifact.artifactId) ||
    !isSafeDisplayName(artifact.displayName) || !Number.isSafeInteger(artifact.sizeBytes) || artifact.sizeBytes < 0 ||
    typeof artifact.downloadPath !== "string") fail();
  const match = DOWNLOAD_PATH_RE.exec(artifact.downloadPath);
  if (match === null || match[1] !== artifact.artifactId) fail();
  return apiUrl(artifact.downloadPath, baseUrl);
}

export async function getJobReportArtifacts(
  jobId: string,
  expectedResultId: string,
  signal?: AbortSignal,
  baseUrl = appEnv.apiBaseUrl,
): Promise<JobReportArtifacts> {
  if (!JOB_ID_RE.test(jobId) || !RESULT_ID_RE.test(expectedResultId)) fail();
  let endpoint: string;
  try {
    endpoint = apiUrl(`/api/v1/jobs/${jobId}/result-view`, baseUrl);
  } catch (error) {
    if (error instanceof UnsupportedReportArtifactsContractError) throw error;
    fail();
  }

  let response: Response;
  try {
    response = await credentialedFetch(endpoint, {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ReportArtifactsRequestError();
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (response.ok) throw new UnsupportedReportArtifactsContractError(response.status);
    throw new ReportArtifactsRequestError(response.status);
  }
  if (!response.ok) throw new ReportArtifactsRequestError(response.status);
  try {
    return parseJobReportArtifacts(payload, jobId, expectedResultId);
  } catch (error) {
    if (error instanceof UnsupportedReportArtifactsContractError) {
      throw new UnsupportedReportArtifactsContractError(response.status);
    }
    throw error;
  }
}
