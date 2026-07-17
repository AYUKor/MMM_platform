import type {
  ApplicationError,
  CampaignPreview,
  CampaignUpload,
  DecisionJob,
  ProgressEvent,
  ValidationResult,
} from "../../entities/lifecycle/types";
import { appEnv } from "../config/env";
import { credentialedFetch } from "./credentialed-fetch";

interface ApiErrorPayload {
  error?: { code?: string; display_text?: string };
}

export interface JobListItem {
  job: DecisionJob;
  campaigns: CampaignPreview[];
}

interface JobListPayload {
  items: JobListItem[];
  total: number;
}

export class LifecycleApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code = "HTTP_ERROR") {
    super(message);
    this.name = "LifecycleApiError";
    this.status = status;
    this.code = code;
  }
}

function apiUrl(path: string): string {
  return `${appEnv.apiBaseUrl.replace(/\/+$/, "")}${path}`;
}

async function apiError(response: Response): Promise<LifecycleApiError> {
  let payload: ApiErrorPayload | null = null;
  try {
    payload = (await response.json()) as ApiErrorPayload;
  } catch {
    // HTTP status remains the fallback when the response body is unavailable.
  }
  return new LifecycleApiError(
    payload?.error?.display_text ?? `Backend вернул ошибку HTTP ${response.status}.`,
    response.status,
    payload?.error?.code,
  );
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await credentialedFetch(apiUrl(path), {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) throw await apiError(response);
  return (await response.json()) as T;
}

export function createIdempotencyKey(scope: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${scope}:${suffix}`;
}

export function uploadCampaign(
  file: File,
  idempotencyKey = createIdempotencyKey("upload"),
): Promise<CampaignUpload> {
  const form = new FormData();
  form.append("file", file, file.name);
  return requestJson<CampaignUpload>("/api/v1/uploads", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: form,
  });
}

export function getUpload(
  uploadId: string,
  signal?: AbortSignal,
): Promise<CampaignUpload> {
  return requestJson<CampaignUpload>(
    `/api/v1/uploads/${encodeURIComponent(uploadId)}`,
    { signal },
  );
}

export function requestValidation(
  uploadId: string,
  idempotencyKey = createIdempotencyKey("validation"),
): Promise<ValidationResult> {
  return requestJson<ValidationResult>(
    `/api/v1/uploads/${encodeURIComponent(uploadId)}/validations`,
    { method: "POST", headers: { "Idempotency-Key": idempotencyKey } },
  );
}

export function getValidation(
  validationId: string,
  signal?: AbortSignal,
): Promise<ValidationResult> {
  return requestJson<ValidationResult>(
    `/api/v1/validations/${encodeURIComponent(validationId)}`,
    { signal },
  );
}

export function createJob(
  validationId: string,
  idempotencyKey = createIdempotencyKey("job"),
  options: Record<string, unknown> = {},
): Promise<DecisionJob> {
  return requestJson<DecisionJob>(
    `/api/v1/validations/${encodeURIComponent(validationId)}/jobs`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(options),
    },
  );
}

export function getJob(jobId: string): Promise<DecisionJob> {
  return requestJson<DecisionJob>(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
}

export function listJobs(): Promise<JobListPayload> {
  return requestJson<JobListPayload>("/api/v1/jobs");
}

export function getJobProgress(jobId: string): Promise<ProgressEvent[]> {
  return requestJson<ProgressEvent[]>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/progress`,
  );
}

export function getJobErrors(jobId: string): Promise<ApplicationError[]> {
  return requestJson<ApplicationError[]>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/errors`,
  );
}

export function cancelJob(jobId: string): Promise<{ job_id: string; cancellation_requested: boolean }> {
  return requestJson(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

export async function pollUntil<T>(
  load: () => Promise<T>,
  isComplete: (value: T) => boolean,
  onUpdate: (value: T) => void,
  options: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<T> {
  const intervalMs = options.intervalMs ?? 500;
  const deadline = Date.now() + (options.timeoutMs ?? 120_000);
  while (true) {
    throwIfAborted(options.signal);
    const value = await load();
    throwIfAborted(options.signal);
    onUpdate(value);
    if (isComplete(value)) return value;
    if (Date.now() >= deadline) {
      throw new Error("Backend не завершил операцию в ожидаемое время.");
    }
    await waitForNextPoll(intervalMs, options.signal);
  }
}

function waitForNextPoll(intervalMs: number, signal?: AbortSignal): Promise<void> {
  if (!signal) {
    return new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      window.clearTimeout(timeoutId);
      reject(abortReason(signal));
    };
    const timeoutId = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, intervalMs);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortReason(signal);
}

function abortReason(signal: AbortSignal): unknown {
  return signal.reason ?? new DOMException("Операция отменена.", "AbortError");
}
