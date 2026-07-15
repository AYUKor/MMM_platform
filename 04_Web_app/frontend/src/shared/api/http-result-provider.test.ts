import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpResultProvider } from "./http-result-provider";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HTTP result provider", () => {
  it("loads DecisionResult by job_id", async () => {
    const payload = {
      contract_name: "decision_result_v1",
      schema_version: "1.0.0",
      result_id: "result_123456789abc",
      job: { job_id: "job_123456789abc" },
      campaign_results: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const provider = createHttpResultProvider("http://127.0.0.1:8765/");
    await expect(provider.getResult(payload.job.job_id)).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/v1/jobs/job_123456789abc/result",
      { headers: { Accept: "application/json" } },
    );
  });

  it("shows backend display text for unavailable result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "RESOURCE_NOT_READY",
              display_text: "Ресурс не найден или еще не готов.",
            },
          }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const provider = createHttpResultProvider("http://127.0.0.1:8765");
    await expect(provider.getResult("job_123456789abc")).rejects.toThrow(
      "Ресурс не найден или еще не готов.",
    );
  });

  it("rejects an unknown response shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const provider = createHttpResultProvider("http://127.0.0.1:8765");
    await expect(provider.getResult("job_123456789abc")).rejects.toThrow(
      "неизвестного формата",
    );
  });
});
