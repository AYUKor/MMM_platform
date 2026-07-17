import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthSessionV1 } from "../../shared/api/generated/auth-session-v1";
import {
  getAuthSession,
  loginWithCredentials,
  logoutSession,
} from "../../shared/api/auth-admin-client";
import {
  AUTH_FORBIDDEN_EVENT,
  AUTH_UNAUTHORIZED_EVENT,
} from "../../shared/api/credentialed-fetch";
import {
  createAnonymousSessionFixture,
  createAuthenticatedSessionFixture,
} from "../../test/authAdminFixtures";
import { AuthProvider, useAuth } from "./AuthProvider";

vi.mock("../../shared/api/auth-admin-client", () => ({
  getAuthSession: vi.fn(),
  loginWithCredentials: vi.fn(),
  logoutSession: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

function AuthProbe() {
  const auth = useAuth();
  return (
    <div>
      <output data-testid="auth-status">{auth.status}</output>
      <output data-testid="auth-user">{auth.session?.user?.display_name ?? "Нет сессии"}</output>
      <output data-testid="auth-role">{auth.session?.user?.role.title ?? "Нет роли"}</output>
      <output data-testid="auth-permissions">
        {auth.session?.user?.permissions.join(",") ?? "Нет разрешений"}
      </output>
      <output data-testid="auth-notice">{auth.notice ?? ""}</output>
      <output data-testid="bootstrap-error">
        {auth.bootstrapError instanceof Error ? auth.bootstrapError.message : ""}
      </output>
      <button type="button" onClick={() => { void auth.refreshSession(); }}>Повторить bootstrap</button>
      <button
        type="button"
        onClick={() => { void auth.login("analyst@example.org", "Pilot-password-2026"); }}
      >
        Войти через provider
      </button>
      <button type="button" onClick={() => { void auth.logout(); }}>Выйти через provider</button>
    </div>
  );
}

function renderProvider() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider><AuthProbe /></AuthProvider>
    </QueryClientProvider>,
  );
  return queryClient;
}

async function expectStatus(status: string) {
  await waitFor(() => expect(screen.getByTestId("auth-status")).toHaveTextContent(status));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("AuthProvider session lifecycle", () => {
  it("starts in loading and applies an authenticated bootstrap response", async () => {
    const pending = deferred<AuthSessionV1>();
    vi.mocked(getAuthSession).mockReturnValueOnce(pending.promise);
    const authenticated = createAuthenticatedSessionFixture("analyst");

    renderProvider();

    expect(screen.getByTestId("auth-status")).toHaveTextContent("loading");
    await act(async () => { pending.resolve(authenticated); });

    await expectStatus("authenticated");
    expect(screen.getByTestId("auth-user")).toHaveTextContent(
      authenticated.user?.display_name ?? "missing user",
    );
    expect(getAuthSession).toHaveBeenCalledOnce();
  });

  it("starts in loading and applies an anonymous bootstrap response", async () => {
    const pending = deferred<AuthSessionV1>();
    vi.mocked(getAuthSession).mockReturnValueOnce(pending.promise);

    renderProvider();

    expect(screen.getByTestId("auth-status")).toHaveTextContent("loading");
    await act(async () => { pending.resolve(createAnonymousSessionFixture()); });

    await expectStatus("anonymous");
    expect(screen.getByTestId("auth-user")).toHaveTextContent("Нет сессии");
    expect(getAuthSession).toHaveBeenCalledOnce();
  });

  it("exposes an initial bootstrap error and recovers through an explicit retry", async () => {
    const initial = deferred<AuthSessionV1>();
    const retry = deferred<AuthSessionV1>();
    vi.mocked(getAuthSession)
      .mockReturnValueOnce(initial.promise)
      .mockReturnValueOnce(retry.promise);

    renderProvider();
    act(() => { initial.reject(new Error("session service unavailable")); });

    await expectStatus("error");
    expect(screen.getByTestId("bootstrap-error")).toHaveTextContent("session service unavailable");

    fireEvent.click(screen.getByRole("button", { name: "Повторить bootstrap" }));
    expect(screen.getByTestId("auth-status")).toHaveTextContent("loading");
    await act(async () => { retry.resolve(createAuthenticatedSessionFixture("viewer")); });

    await expectStatus("authenticated");
    expect(screen.getByTestId("bootstrap-error")).toBeEmptyDOMElement();
    expect(getAuthSession).toHaveBeenCalledTimes(2);
  });

  it("coalesces simultaneous unauthorized events into exactly one session recheck", async () => {
    const recheck = deferred<AuthSessionV1>();
    vi.mocked(getAuthSession)
      .mockResolvedValueOnce(createAuthenticatedSessionFixture("admin"))
      .mockReturnValueOnce(recheck.promise);
    const queryClient = renderProvider();
    queryClient.setQueryData(["protected"], { value: "cached" });
    await expectStatus("authenticated");
    const clear = vi.spyOn(queryClient, "clear");

    act(() => {
      window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
      window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
      window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
    });

    expect(getAuthSession).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("auth-notice")).toHaveTextContent(
      "Сессия завершена. Войдите повторно.",
    );
    await act(async () => { recheck.resolve(createAnonymousSessionFixture()); });

    await expectStatus("anonymous");
    expect(clear).toHaveBeenCalledOnce();
    expect(queryClient.getQueryData(["protected"])).toBeUndefined();
  });

  it("keeps the session and cache when an unauthorized recheck remains authenticated", async () => {
    const initial = createAuthenticatedSessionFixture("analyst");
    const rechecked = createAuthenticatedSessionFixture("analyst");
    const recheck = deferred<AuthSessionV1>();
    vi.mocked(getAuthSession)
      .mockResolvedValueOnce(initial)
      .mockReturnValueOnce(recheck.promise);
    const queryClient = renderProvider();
    queryClient.setQueryData(["protected"], { value: "cached" });
    await expectStatus("authenticated");
    const clear = vi.spyOn(queryClient, "clear");

    act(() => { window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT)); });
    expect(screen.getByTestId("auth-user")).toHaveTextContent(initial.user?.display_name ?? "");
    await act(async () => { recheck.resolve(rechecked); });

    await waitFor(() => expect(screen.getByTestId("auth-notice")).toBeEmptyDOMElement());
    expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("auth-user")).toHaveTextContent(rechecked.user?.display_name ?? "");
    expect(queryClient.getQueryData(["protected"])).toEqual({ value: "cached" });
    expect(clear).not.toHaveBeenCalled();
    expect(getAuthSession).toHaveBeenCalledTimes(2);
  });

  it("coalesces simultaneous forbidden events and keeps unchanged access and cache", async () => {
    const initial = createAuthenticatedSessionFixture("analyst");
    const recheck = deferred<AuthSessionV1>();
    vi.mocked(getAuthSession)
      .mockResolvedValueOnce(initial)
      .mockReturnValueOnce(recheck.promise);
    const queryClient = renderProvider();
    queryClient.setQueryData(["permission-scoped"], { value: "cached" });
    await expectStatus("authenticated");
    const clear = vi.spyOn(queryClient, "clear");

    act(() => {
      window.dispatchEvent(new CustomEvent(AUTH_FORBIDDEN_EVENT));
      window.dispatchEvent(new CustomEvent(AUTH_FORBIDDEN_EVENT));
      window.dispatchEvent(new CustomEvent(AUTH_FORBIDDEN_EVENT));
    });

    expect(getAuthSession).toHaveBeenCalledTimes(2);
    await act(async () => { recheck.resolve(structuredClone(initial)); });

    expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("auth-role")).toHaveTextContent(initial.user?.role.title ?? "");
    expect(queryClient.getQueryData(["permission-scoped"])).toEqual({ value: "cached" });
    expect(clear).not.toHaveBeenCalled();
  });

  it("applies changed role and permissions after a forbidden recheck and clears cache", async () => {
    const initial = createAuthenticatedSessionFixture("analyst");
    const changed = structuredClone(initial);
    if (!changed.user) throw new Error("Authenticated test fixture has no user");
    changed.user.role = { role_id: "admin", title: "Администратор" };
    changed.user.permissions = [
      ...changed.user.permissions,
      "admin.users.read",
      "admin.system.read",
    ];
    const recheck = deferred<AuthSessionV1>();
    vi.mocked(getAuthSession)
      .mockResolvedValueOnce(initial)
      .mockReturnValueOnce(recheck.promise);
    const queryClient = renderProvider();
    queryClient.setQueryData(["permission-scoped"], { value: "stale" });
    await expectStatus("authenticated");
    const clear = vi.spyOn(queryClient, "clear");

    act(() => { window.dispatchEvent(new CustomEvent(AUTH_FORBIDDEN_EVENT)); });
    await act(async () => { recheck.resolve(changed); });

    await waitFor(() => expect(screen.getByTestId("auth-role")).toHaveTextContent("Администратор"));
    expect(screen.getByTestId("auth-permissions")).toHaveTextContent("admin.users.read");
    expect(screen.getByTestId("auth-permissions")).toHaveTextContent("admin.system.read");
    expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
    expect(clear).toHaveBeenCalledOnce();
    expect(queryClient.getQueryData(["permission-scoped"])).toBeUndefined();
    expect(getAuthSession).toHaveBeenCalledTimes(2);
  });

  it("keeps the authenticated session and cache when a forbidden recheck fails", async () => {
    const initial = createAuthenticatedSessionFixture("admin");
    const recheck = deferred<AuthSessionV1>();
    vi.mocked(getAuthSession)
      .mockResolvedValueOnce(initial)
      .mockReturnValueOnce(recheck.promise);
    const queryClient = renderProvider();
    queryClient.setQueryData(["permission-scoped"], { value: "cached" });
    await expectStatus("authenticated");
    const clear = vi.spyOn(queryClient, "clear");

    act(() => { window.dispatchEvent(new CustomEvent(AUTH_FORBIDDEN_EVENT)); });
    await act(async () => {
      recheck.reject(new TypeError("permission recheck unavailable"));
      await Promise.resolve();
    });

    expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("auth-user")).toHaveTextContent(initial.user?.display_name ?? "");
    expect(screen.getByTestId("auth-role")).toHaveTextContent(initial.user?.role.title ?? "");
    expect(queryClient.getQueryData(["permission-scoped"])).toEqual({ value: "cached" });
    expect(clear).not.toHaveBeenCalled();
    expect(getAuthSession).toHaveBeenCalledTimes(2);
  });

  it("clears runtime session and query cache when logout fails on the network", async () => {
    vi.mocked(getAuthSession).mockResolvedValueOnce(createAuthenticatedSessionFixture("admin"));
    vi.mocked(logoutSession).mockRejectedValueOnce(new TypeError("network unavailable"));
    const queryClient = renderProvider();
    queryClient.setQueryData(["protected"], { value: "cached" });
    await expectStatus("authenticated");
    const clear = vi.spyOn(queryClient, "clear");

    fireEvent.click(screen.getByRole("button", { name: "Выйти через provider" }));

    await expectStatus("anonymous");
    expect(screen.getByTestId("auth-user")).toHaveTextContent("Нет сессии");
    expect(logoutSession).toHaveBeenCalledOnce();
    expect(clear).toHaveBeenCalledOnce();
    expect(queryClient.getQueryData(["protected"])).toBeUndefined();
  });

  it("rebootstraps after login and never writes auth session or token storage keys", async () => {
    const anonymous = createAnonymousSessionFixture();
    const loginResponse = createAuthenticatedSessionFixture("viewer");
    const bootstrapResponse = createAuthenticatedSessionFixture("admin");
    vi.mocked(getAuthSession)
      .mockResolvedValueOnce(anonymous)
      .mockResolvedValueOnce(bootstrapResponse);
    vi.mocked(loginWithCredentials).mockResolvedValueOnce(loginResponse);
    window.localStorage.setItem("mmm-frontend-theme", "dark");
    window.sessionStorage.setItem("ui-state", "preserved");
    const queryClient = renderProvider();
    queryClient.setQueryData(["anonymous-cache"], { value: "stale" });
    await expectStatus("anonymous");
    const clear = vi.spyOn(queryClient, "clear");

    fireEvent.click(screen.getByRole("button", { name: "Войти через provider" }));

    await expectStatus("authenticated");
    expect(loginWithCredentials).toHaveBeenCalledWith(
      "analyst@example.org",
      "Pilot-password-2026",
    );
    expect(getAuthSession).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("auth-user")).toHaveTextContent(
      bootstrapResponse.user?.display_name ?? "missing user",
    );
    expect(screen.getByTestId("auth-user")).not.toHaveTextContent(
      loginResponse.user?.display_name ?? "unexpected login response",
    );
    expect(clear).toHaveBeenCalledOnce();
    expect(queryClient.getQueryData(["anonymous-cache"])).toBeUndefined();

    const storageKeys = [
      ...Object.keys(window.localStorage),
      ...Object.keys(window.sessionStorage),
    ];
    expect(storageKeys.filter((key) => /auth|session|token/i.test(key))).toEqual([]);
    expect(window.localStorage.getItem("mmm-frontend-theme")).toBe("dark");
    expect(window.sessionStorage.getItem("ui-state")).toBe("preserved");
  });
});
