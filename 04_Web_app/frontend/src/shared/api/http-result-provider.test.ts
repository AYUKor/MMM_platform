import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../../../../tests/fixtures/result_overview_v1_real_sanitized.json";
import type { ResultOverviewV1 } from "../../entities/result-overview/types";
import {
  createHttpResultProvider,
  ResultOverviewHttpError,
} from "./http-result-provider";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HTTP result overview provider", () => {
  it("loads ResultOverview by job id from the browser-safe endpoint", async () => {
    const payload = fixture as unknown as ResultOverviewV1;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const provider = createHttpResultProvider("http://127.0.0.1:8765/");
    await expect(provider.getOverview("job_123456789abc")).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/v1/jobs/job_123456789abc/overview",
      { headers: { Accept: "application/json" } },
    );
  });

  it("does not expose a backend error code or display text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "RESOURCE_NOT_READY",
              display_text: "RAW_BACKEND_MESSAGE",
            },
          }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const provider = createHttpResultProvider("http://127.0.0.1:8765");
    const error = await provider.getOverview("job_123456789abc").catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ResultOverviewHttpError);
    expect((error as Error).message).not.toContain("RESOURCE_NOT_READY");
    expect((error as Error).message).not.toContain("RAW_BACKEND_MESSAGE");
  });

  it("rejects an empty or unknown response shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok", campaigns: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const provider = createHttpResultProvider("http://127.0.0.1:8765");
    await expect(provider.getOverview("job_123456789abc")).rejects.toThrow(
      "неполный или неизвестный",
    );
  });

  it("rejects a scenario set with a missing or duplicate scenario id", async () => {
    const payload = structuredClone(fixture) as unknown as ResultOverviewV1;
    payload.campaigns[0].scenarios[1] = payload.campaigns[0].scenarios[0];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      createHttpResultProvider("http://127.0.0.1:8765").getOverview("job_123456789abc"),
    ).rejects.toThrow("неполный или неизвестный");
  });
});
