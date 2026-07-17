import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AUTH_FORBIDDEN_EVENT,
  AUTH_UNAUTHORIZED_EVENT,
  credentialedFetch,
} from "./credentialed-fetch";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("credentialedFetch", () => {
  it("always includes browser credentials while preserving request options", async () => {
    const response = new Response(null, { status: 204 });
    const fetchMock = vi.fn().mockResolvedValue(response);
    const controller = new AbortController();
    vi.stubGlobal("fetch", fetchMock);

    await expect(credentialedFetch("/api/v1/resource", {
      method: "POST",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })).resolves.toBe(response);

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/resource", {
      method: "POST",
      headers: { Accept: "application/json" },
      signal: controller.signal,
      credentials: "include",
    });
  });

  it("does not allow a caller to omit credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await credentialedFetch("/api/v1/resource", { credentials: "omit" });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/resource", {
      credentials: "include",
    });
  });

  it("signals an unauthorized application request without exposing response data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    const listener = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, listener);

    await credentialedFetch("/api/v1/protected");

    expect(listener).toHaveBeenCalledOnce();
    expect(listener.mock.calls[0]).toHaveLength(1);
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
  });

  it("allows login to suppress the unauthorized-session signal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    const listener = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, listener);

    await credentialedFetch(
      "/api/v1/auth/login",
      { method: "POST" },
      { signalUnauthorized: false, signalForbidden: false },
    );

    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, listener);
  });

  it("signals a protected 403 and allows Login to suppress that signal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 403 })));
    const listener = vi.fn();
    window.addEventListener(AUTH_FORBIDDEN_EVENT, listener);

    await credentialedFetch("/api/v1/admin/system/status");
    expect(listener).toHaveBeenCalledOnce();

    listener.mockClear();
    await credentialedFetch(
      "/api/v1/auth/login",
      { method: "POST" },
      { signalForbidden: false },
    );
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(AUTH_FORBIDDEN_EVENT, listener);
  });
});
