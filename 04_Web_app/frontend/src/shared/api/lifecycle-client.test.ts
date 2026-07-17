import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createIdempotencyKey,
  createJob,
  listJobs,
  LifecycleApiError,
  pollUntil,
  uploadCampaign,
} from "./lifecycle-client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("lifecycle client", () => {
  it("uploads a campaign as multipart with an idempotency key", async () => {
    const response = {
      contract_name: "campaign_upload_v1",
      upload_id: "upload_123456789abc",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["campaign_name,budget_rub"], "campaign.csv");
    await expect(uploadCampaign(file, "upload:test-key-0001")).resolves.toEqual(response);
    const [, request] = fetchMock.mock.calls[0];
    expect(request.method).toBe("POST");
    expect(request.credentials).toBe("include");
    expect(request.headers["Idempotency-Key"]).toBe("upload:test-key-0001");
    expect(request.body).toBeInstanceOf(FormData);
  });

  it("creates a job from a valid validation", async () => {
    const response = {
      contract_name: "decision_job_v1",
      job_id: "job_123456789abc",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createJob("validation_123456789abc", "job:test-key-0000001");
    const [url, request] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/validations/validation_123456789abc/jobs");
    expect(request.body).toBe("{}");
  });

  it("lists server-side jobs", async () => {
    const response = { items: [], total: 0 };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(listJobs()).resolves.toEqual(response);
  });

  it("preserves backend error code and display text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: "JOB_CREATION_BLOCKED", display_text: "План не прошел проверку." },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(createJob("validation_123456789abc")).rejects.toMatchObject({
      name: "LifecycleApiError",
      code: "JOB_CREATION_BLOCKED",
      status: 409,
    } satisfies Partial<LifecycleApiError>);
  });

  it("creates backend-safe idempotency keys", () => {
    expect(createIdempotencyKey("upload")).toMatch(/^[A-Za-z0-9._:-]{16,128}$/);
  });

  it("cancels an active polling interval without another request", async () => {
    const controller = new AbortController();
    const load = vi.fn().mockResolvedValue({ complete: false });
    const polling = pollUntil(
      load,
      (value) => value.complete,
      vi.fn(),
      { intervalMs: 60_000, signal: controller.signal },
    );

    await Promise.resolve();
    controller.abort();

    await expect(polling).rejects.toMatchObject({ name: "AbortError" });
    expect(load).toHaveBeenCalledTimes(1);
  });
});
