import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getCalculationHistory,
  getHelpCatalog,
  getModelOverview,
  getWorkspaceHome,
  isSafeInternalPath,
  normalizeCalculationHistoryQuery,
  parseCalculationHistory,
  parseHelpCatalog,
  parseModelOverview,
  parseWorkspaceHome,
  ProductNavigationInconsistentError,
  ProductNavigationQueryInvalidError,
  ProductNavigationRequestError,
  ProductNavigationUnavailableError,
  serializeCalculationHistoryQuery,
  UnsupportedProductNavigationContractError,
} from "./product-navigation-client";
import {
  createCalculationHistoryFixture,
  createHelpCatalogFixture,
  createModelOverviewFixture,
  createWorkspaceHomeFixture,
} from "../../test/productNavigationFixtures";

const API_BASE_URL = "http://127.0.0.1:8765/";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function navigationError(code: string, displayText: string, retryable: boolean): Record<string, unknown> {
  return {
    error: {
      code,
      display_text: displayText,
      retryable,
      user_action: "Выполните рекомендуемое действие.",
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Phase D runtime parsers", () => {
  it("accepts all coherent synthetic contracts without converting null or zero", () => {
    const home = parseWorkspaceHome(createWorkspaceHomeFixture());
    const history = parseCalculationHistory(createCalculationHistoryFixture());
    const model = parseModelOverview(createModelOverviewFixture());
    const help = parseHelpCatalog(createHelpCatalogFixture());

    expect(home.recent_calculations[0].warnings_count).toBe(0);
    expect(home.recent_calculations[1].warnings_count).toBeNull();
    expect(history.items[0].warnings_count).toBe(0);
    expect(history.items[2].total_budget_rub).toBeNull();
    expect(model.active_model.supported_scope?.allowed_use_counts.unavailable).toBe(1);
    expect(help.sections).toHaveLength(9);
  });

  it("accepts backend-nullable home timestamps and unavailable model publication dates", () => {
    const home = createWorkspaceHomeFixture();
    home.recent_calculations[0].completed_at_utc = null;
    home.recent_calculations[0].status = { code: "running", display_text: "Выполняется" };
    home.model = {
      ...home.model,
      status: { code: "unavailable", display_text: "Модель недоступна" },
      model_id: null,
      display_name: null,
      version: null,
      training_period: null,
      supported_scope: null,
    };
    expect(parseWorkspaceHome(home).recent_calculations[0].completed_at_utc).toBeNull();
    expect(parseWorkspaceHome(home).model.published_at_utc).toBe("2026-07-15T11:00:00Z");

    const model = createModelOverviewFixture();
    model.active_model = {
      ...model.active_model,
      status: { code: "unavailable", display_text: "Модель недоступна" },
      model_id: null,
      display_name: null,
      version: null,
      framework: null,
      training_period: null,
      supported_scope: null,
    };
    model.versions = [];
    expect(parseModelOverview(model).active_model.published_at_utc).toBe("2026-07-15T11:00:00Z");
  });

  it.each([
    ["home extra key", () => {
      const value = createWorkspaceHomeFixture() as unknown as Record<string, unknown>;
      value.internal_state = "private";
      return () => parseWorkspaceHome(value);
    }],
    ["history summary mismatch", () => {
      const value = createCalculationHistoryFixture();
      value.summary.all = 4;
      return () => parseCalculationHistory(value);
    }],
    ["model capability count mismatch", () => {
      const value = createModelOverviewFixture();
      if (value.active_model.supported_scope) value.active_model.supported_scope.capability_cells_n = 99;
      return () => parseModelOverview(value);
    }],
    ["help unsafe markup", () => {
      const value = createHelpCatalogFixture();
      value.sections[0].articles[0].body[0] = { block_type: "paragraph", text: "<script>alert(1)</script>" };
      return () => parseHelpCatalog(value);
    }],
  ])("rejects %s", (_name, createAssertion) => {
    expect(createAssertion()).toThrow(UnsupportedProductNavigationContractError);
  });

  it("rejects inconsistent active/recent, result/report and model version relations", () => {
    const home = createWorkspaceHomeFixture();
    home.active_calculations[0].can_cancel = false;
    expect(() => parseWorkspaceHome(home)).toThrow(UnsupportedProductNavigationContractError);

    const history = createCalculationHistoryFixture();
    history.items[2].result_available = true;
    history.items[2].result_path = "/calculations/job_000000000003/result";
    expect(() => parseCalculationHistory(history)).toThrow(UnsupportedProductNavigationContractError);

    const model = createModelOverviewFixture();
    model.versions[0].status = "registered";
    expect(() => parseModelOverview(model)).toThrow(UnsupportedProductNavigationContractError);
  });

  it("rejects duplicate or unknown help relations and unapproved routes", () => {
    const duplicate = createHelpCatalogFixture();
    duplicate.sections[1].articles[0].article_id = duplicate.sections[0].articles[0].article_id;
    expect(() => parseHelpCatalog(duplicate)).toThrow(UnsupportedProductNavigationContractError);

    const unknown = createHelpCatalogFixture();
    unknown.sections[0].articles[0].related_article_ids = ["unknown_article"];
    expect(() => parseHelpCatalog(unknown)).toThrow(UnsupportedProductNavigationContractError);

    const route = createHelpCatalogFixture() as unknown as {
      sections: Array<{ articles: Array<{ related_routes: string[] }> }>;
    };
    route.sections[0].articles[0].related_routes = ["/admin"];
    expect(() => parseHelpCatalog(route)).toThrow(UnsupportedProductNavigationContractError);
  });

  it("rejects local paths, traversal and unsupported model scores", () => {
    expect(isSafeInternalPath("/calculations/job_000000000001/progress")).toBe(true);
    expect(isSafeInternalPath("//example.com/private")).toBe(false);
    expect(isSafeInternalPath("/Users/example/private")).toBe(false);
    expect(isSafeInternalPath("/calculations/%2e%2e/private")).toBe(false);

    const home = createWorkspaceHomeFixture();
    home.active_calculations[0].progress_path = "/Users/example/private";
    expect(() => parseWorkspaceHome(home)).toThrow(UnsupportedProductNavigationContractError);

    const model = createModelOverviewFixture() as unknown as Record<string, unknown>;
    model.quality_score = 10;
    expect(() => parseModelOverview(model)).toThrow(UnsupportedProductNavigationContractError);
  });

  it("rejects every absolute path outside approved route fields", () => {
    const help = createHelpCatalogFixture();
    help.sections[0].articles[0].body[0] = {
      block_type: "paragraph",
      text: "/etc/passwd",
    };
    expect(() => parseHelpCatalog(help)).toThrow(UnsupportedProductNavigationContractError);

    const history = createCalculationHistoryFixture();
    history.items[0].segments = ["/opt/private-model"];
    expect(() => parseCalculationHistory(history)).toThrow(UnsupportedProductNavigationContractError);

    const model = createModelOverviewFixture();
    model.data_requirements[0].accepted_values = ["/srv/internal-package"];
    expect(() => parseModelOverview(model)).toThrow(UnsupportedProductNavigationContractError);

    expect(() => parseWorkspaceHome(createWorkspaceHomeFixture())).not.toThrow();
    expect(() => parseHelpCatalog(createHelpCatalogFixture())).not.toThrow();
  });

  it("rejects malformed model limitation copy and status", () => {
    const blankAction = createModelOverviewFixture();
    blankAction.limitations[0].recommended_action = " ";
    expect(() => parseModelOverview(blankAction)).toThrow(UnsupportedProductNavigationContractError);

    const invalidStatus = createModelOverviewFixture();
    (invalidStatus.limitations[0] as unknown as { status: string }).status = "warning";
    expect(() => parseModelOverview(invalidStatus)).toThrow(UnsupportedProductNavigationContractError);
  });
});

describe("history query contract", () => {
  it("normalizes defaults and serializes only supported backend parameters", () => {
    expect(normalizeCalculationHistoryQuery()).toEqual({
      page: 1,
      pageSize: 25,
      status: null,
      search: null,
      createdFrom: null,
      createdTo: null,
      sort: "created_desc",
    });
    expect(serializeCalculationHistoryQuery({
      page: 2,
      pageSize: 50,
      status: "active",
      search: "  Кампания A  ",
      createdFrom: "2026-07-01",
      createdTo: "2026-07-17",
      sort: "campaign_asc",
    })).toBe(
      "page=2&page_size=50&sort=campaign_asc&status=active&search=%D0%9A%D0%B0%D0%BC%D0%BF%D0%B0%D0%BD%D0%B8%D1%8F+A&created_from=2026-07-01&created_to=2026-07-17",
    );
  });

  it.each([
    { page: 0 },
    { pageSize: 101 },
    { search: "   " },
    { createdFrom: "2026-02-30" },
  ])("rejects invalid query %#", (query) => {
    expect(() => normalizeCalculationHistoryQuery(query)).toThrow(ProductNavigationQueryInvalidError);
  });

  it("passes a reversed date range through so the backend can return its browser-safe 422 copy", () => {
    expect(serializeCalculationHistoryQuery({
      createdFrom: "2026-07-20",
      createdTo: "2026-07-10",
    })).toContain("created_from=2026-07-20&created_to=2026-07-10");
  });

  it("requires the backend to echo the requested filters and pagination", () => {
    const value = createCalculationHistoryFixture();
    expect(() => parseCalculationHistory(value, {
      page: 2,
      pageSize: 25,
      status: null,
      search: null,
      createdFrom: null,
      createdTo: null,
      sort: "created_desc",
    })).toThrow(UnsupportedProductNavigationContractError);
  });
});

describe("Phase D HTTP clients", () => {
  it("calls only the four approved endpoints", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(createWorkspaceHomeFixture()))
      .mockResolvedValueOnce(jsonResponse(createCalculationHistoryFixture()))
      .mockResolvedValueOnce(jsonResponse(createModelOverviewFixture()))
      .mockResolvedValueOnce(jsonResponse(createHelpCatalogFixture()));
    vi.stubGlobal("fetch", fetchMock);

    await getWorkspaceHome(undefined, API_BASE_URL);
    await getCalculationHistory({}, undefined, API_BASE_URL);
    await getModelOverview(undefined, API_BASE_URL);
    await getHelpCatalog(undefined, API_BASE_URL);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8765/api/v1/workspace/home",
      "http://127.0.0.1:8765/api/v1/calculations/history?page=1&page_size=25&sort=created_desc",
      "http://127.0.0.1:8765/api/v1/model/overview",
      "http://127.0.0.1:8765/api/v1/help/catalog",
    ]);
    for (const [, options] of fetchMock.mock.calls) {
      expect(options).toMatchObject({ method: "GET", headers: { Accept: "application/json" } });
    }
  });

  it.each([
    [422, "PRODUCT_NAVIGATION_QUERY_INVALID", ProductNavigationQueryInvalidError],
    [409, "PRODUCT_NAVIGATION_INCONSISTENT", ProductNavigationInconsistentError],
    [503, "PRODUCT_NAVIGATION_UNAVAILABLE", ProductNavigationUnavailableError],
  ])("maps HTTP %i to a controlled product error", async (status, code, ErrorType) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse(navigationError(code, "Безопасное сообщение", status !== 409), status),
    ));
    const error = await getWorkspaceHome(undefined, API_BASE_URL).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ErrorType);
    expect((error as Error).message).toBe("Безопасное сообщение");
  });

  it("does not expose network details and preserves abort errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("PRIVATE_NETWORK_DETAIL")));
    const error = await getHelpCatalog(undefined, API_BASE_URL).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ProductNavigationRequestError);
    expect((error as Error).message).not.toContain("PRIVATE_NETWORK_DETAIL");

    const controller = new AbortController();
    controller.abort();
    const abortError = new DOMException("Aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortError));
    await expect(getModelOverview(controller.signal, API_BASE_URL)).rejects.toBe(abortError);
  });

  it("maps malformed successful JSON to unsupported contract", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{bad", { status: 200 })));
    await expect(getWorkspaceHome(undefined, API_BASE_URL)).rejects.toMatchObject({
      name: "UnsupportedProductNavigationContractError",
      contract: "workspace_home_v1",
      status: 200,
    });
  });
});
