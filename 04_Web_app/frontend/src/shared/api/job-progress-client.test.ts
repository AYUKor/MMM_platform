import { afterEach, describe, expect, it, vi } from "vitest";
import type { JobProgressViewV1 } from "./generated/job-progress-view-v1";
import {
  getJobProgressView,
  getMmmFacts,
  JobProgressInconsistentError,
  JobProgressNotFoundError,
  JobProgressRequestError,
  JobProgressUnavailableError,
  MmmFactsUnavailableError,
  parseJobProgressView,
  parseMmmFactCatalog,
  UnsupportedJobProgressContractError,
  UnsupportedMmmFactsContractError,
} from "./job-progress-client";

const JOB_ID = "job_000000000001";
const API_BASE_URL = "http://127.0.0.1:8765/";
const stageCatalog = [
  ["P01", "Расчет ожидает запуска"],
  ["P02", "Подготавливаем медиаплан"],
  ["P03", "Рассчитываем исходный медиаплан"],
  ["P04", "Рассчитываем контрольные сценарии"],
  ["P05", "Ищем устойчивый вариант"],
  ["P06", "Перебираем варианты распределения"],
  ["P07", "Проверяем результаты"],
  ["P08", "Формируем отчет"],
  ["P09", "Расчет завершен"],
] as const;

function runningView(): JobProgressViewV1 {
  return {
    contract_name: "job_progress_view_v1",
    schema_version: "1.0.0",
    record_origin: "synthetic_fixture",
    job_id: JOB_ID,
    job_status: { code: "running", display_text: "Расчет выполняется" },
    queue: { position: null, queued_jobs_total: 0, display_text: "Расчет уже запущен." },
    campaign: {
      campaign_id: "campaign_000000000002",
      campaign_name: "Синтетическая кампания",
      segment: ["Синтетический сегмент"],
      start_date: "2026-08-01",
      end_date: "2026-08-31",
      total_budget_rub: 12_000_000,
      channels_n: 3,
      geographies_n: 5,
    },
    current_stage_id: "P02",
    stages: stageCatalog.map(([stage_id, title], index) => ({
      stage_id,
      order: index + 1,
      title,
      status: index === 0 ? "completed" as const : index === 1 ? "active" as const : "pending" as const,
      started_at_utc: index <= 1 ? `2026-07-16T10:0${index}:00Z` : null,
      finished_at_utc: index === 0 ? "2026-07-16T10:00:30Z" : null,
      display_text: index === 1 ? "Проверяем входные данные." : `${title}.`,
      progress: index === 1 ? { current: 2, total: null, unit: "шага" } : null,
    })) as JobProgressViewV1["stages"],
    scenario6: {
      status: "pending",
      attempt_budget: null,
      attempts_checked: null,
      safe_candidates: null,
      blocked_candidates: null,
      finalists_scored: null,
      finalists_total: null,
    },
    report: {
      status: "pending",
      display_text: "Отчет будет сформирован после проверки результатов.",
      retryable: false,
    },
    errors: [],
    can_cancel: true,
    result_available: false,
    updated_at_utc: "2026-07-16T10:05:00Z",
  };
}

function succeededView(): JobProgressViewV1 {
  const value = runningView();
  value.job_status = { code: "succeeded", display_text: "Расчет завершен" };
  value.current_stage_id = "P09";
  value.stages = value.stages.map((stage, index) => ({
    ...stage,
    status: "completed" as const,
    started_at_utc: `2026-07-16T10:${String(index * 2).padStart(2, "0")}:00Z`,
    finished_at_utc: `2026-07-16T10:${String(index * 2 + 1).padStart(2, "0")}:00Z`,
    progress: null,
  })) as JobProgressViewV1["stages"];
  value.scenario6 = {
    status: "completed",
    attempt_budget: 2_048,
    attempts_checked: 1_706,
    safe_candidates: null,
    blocked_candidates: null,
    finalists_scored: 11,
    finalists_total: 600,
  };
  value.report = { status: "completed", display_text: "Excel-отчет готов.", retryable: false };
  value.can_cancel = false;
  value.result_available = true;
  value.updated_at_utc = "2026-07-16T10:20:00Z";
  return value;
}

function factCatalog(): Record<string, unknown> {
  return {
    contract_name: "mmm_fact_catalog_v1",
    schema_version: "1.0.0",
    facts: Array.from({ length: 20 }, (_, index) => ({
      fact_id: `fact_synthetic_${String(index).padStart(2, "0")}`,
      category: "forecast",
      text: `Синтетический факт ${index + 1}.`,
      source_label: "Синтетический источник",
    })),
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("job progress runtime parser", () => {
  it("accepts a coherent running snapshot and a coherent terminal snapshot", () => {
    expect(parseJobProgressView(runningView(), JOB_ID)).toEqual(runningView());
    expect(parseJobProgressView(succeededView(), JOB_ID)).toEqual(succeededView());
  });

  it.each([
    ["unknown contract", (value: Record<string, unknown>) => { value.contract_name = "future_contract"; }],
    ["unsupported version", (value: Record<string, unknown>) => { value.schema_version = "2.0.0"; }],
    ["extra field", (value: Record<string, unknown>) => { value.internal_phase = "private"; }],
    ["route mismatch", (value: Record<string, unknown>) => { value.job_id = "job_ffffffffffff"; }],
    ["absolute path", (value: Record<string, unknown>) => {
      (value.campaign as Record<string, unknown>).campaign_name = "/Users/example/private";
    }],
    ["invalid stage order", (value: Record<string, unknown>) => {
      ((value.stages as Record<string, unknown>[])[1]).order = 7;
    }],
    ["invalid stage title", (value: Record<string, unknown>) => {
      ((value.stages as Record<string, unknown>[])[1]).title = "Техническая стадия";
    }],
    ["counter over total", (value: Record<string, unknown>) => {
      ((value.stages as Record<string, unknown>[])[1].progress as Record<string, unknown>).total = 1;
    }],
    ["finished stage without a start", (value: Record<string, unknown>) => {
      const stage = (value.stages as Record<string, unknown>[])[2];
      stage.status = "warning";
      stage.started_at_utc = null;
      stage.finished_at_utc = "2026-07-16T10:02:30Z";
    }],
  ])("rejects %s", (_name, mutate) => {
    const payload = structuredClone(runningView()) as unknown as Record<string, unknown>;
    mutate(payload);
    expect(() => parseJobProgressView(payload, JOB_ID)).toThrow(
      UnsupportedJobProgressContractError,
    );
  });

  it("rejects incoherent queue, Scenario 6 and terminal combinations", () => {
    const queued = runningView();
    queued.job_status.code = "queued";
    queued.queue.position = 0;
    expect(() => parseJobProgressView(queued, JOB_ID)).toThrow(UnsupportedJobProgressContractError);

    const counters = runningView();
    counters.scenario6.attempt_budget = 10;
    counters.scenario6.attempts_checked = 11;
    expect(() => parseJobProgressView(counters, JOB_ID)).toThrow(UnsupportedJobProgressContractError);

    const terminal = succeededView();
    terminal.stages[8].status = "active";
    terminal.stages[8].finished_at_utc = null;
    expect(() => parseJobProgressView(terminal, JOB_ID)).toThrow(UnsupportedJobProgressContractError);

    const unknownQueueTotal = runningView();
    unknownQueueTotal.job_status.code = "queued";
    unknownQueueTotal.queue.position = 1;
    unknownQueueTotal.queue.queued_jobs_total = null;
    expect(() => parseJobProgressView(unknownQueueTotal, JOB_ID)).toThrow(
      UnsupportedJobProgressContractError,
    );

    const invalidCancelFlag = runningView();
    invalidCancelFlag.can_cancel = false;
    expect(() => parseJobProgressView(invalidCancelFlag, JOB_ID)).toThrow(
      UnsupportedJobProgressContractError,
    );
  });
});

describe("job progress HTTP client", () => {
  it("loads only the product progress-view endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(runningView()));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getJobProgressView(JOB_ID, undefined, API_BASE_URL)).resolves.toEqual(runningView());
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      `http://127.0.0.1:8765/api/v1/jobs/${JOB_ID}/progress-view`,
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it.each([
    [404, JobProgressNotFoundError],
    [409, JobProgressInconsistentError],
    [503, JobProgressUnavailableError],
    [500, JobProgressRequestError],
  ])("maps HTTP %i to a controlled error", async (status, errorType) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ raw: "PRIVATE" }, status)));
    const error = await getJobProgressView(JOB_ID, undefined, API_BASE_URL).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(errorType);
    expect((error as Error).message).not.toContain("PRIVATE");
  });

  it("maps network failure without exposing transport details", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("PRIVATE_NETWORK_DETAIL")));
    const error = await getJobProgressView(JOB_ID, undefined, API_BASE_URL).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(JobProgressRequestError);
    expect((error as Error).message).not.toContain("PRIVATE_NETWORK_DETAIL");
  });

  it("maps malformed successful JSON to unsupported contract", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{bad", { status: 200 })));
    await expect(getJobProgressView(JOB_ID, undefined, API_BASE_URL)).rejects.toBeInstanceOf(
      UnsupportedJobProgressContractError,
    );
  });
});

describe("MMM fact catalog", () => {
  it("accepts the reviewed catalog shape", () => {
    expect(parseMmmFactCatalog(factCatalog()).facts).toHaveLength(20);
  });

  it.each([
    ["too few facts", (value: Record<string, unknown>) => { value.facts = (value.facts as unknown[]).slice(0, 19); }],
    ["duplicate fact", (value: Record<string, unknown>) => {
      const facts = value.facts as Record<string, unknown>[];
      facts[1].fact_id = facts[0].fact_id;
    }],
    ["unknown category", (value: Record<string, unknown>) => {
      ((value.facts as Record<string, unknown>[])[0]).category = "private";
    }],
    ["extra field", (value: Record<string, unknown>) => {
      ((value.facts as Record<string, unknown>[])[0]).internal_source = "private";
    }],
  ])("rejects %s", (_name, mutate) => {
    const payload = structuredClone(factCatalog());
    mutate(payload);
    expect(() => parseMmmFactCatalog(payload)).toThrow(UnsupportedMmmFactsContractError);
  });

  it("loads facts from the metadata endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(factCatalog()));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getMmmFacts(undefined, API_BASE_URL)).resolves.toMatchObject({
      contract_name: "mmm_fact_catalog_v1",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/v1/meta/mmm-facts",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("keeps facts optional when the endpoint fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 500)));
    await expect(getMmmFacts(undefined, API_BASE_URL)).rejects.toBeInstanceOf(
      MmmFactsUnavailableError,
    );
  });
});
