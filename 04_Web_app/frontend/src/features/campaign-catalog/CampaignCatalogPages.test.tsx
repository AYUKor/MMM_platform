import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../../test/fixtures/campaign_catalog_v1_synthetic.json";
import { CampaignCardPage } from "../../pages/CampaignCardPage";
import { CampaignCatalogPage } from "../../pages/CampaignCatalogPage";

const authMock = vi.hoisted(() => ({ permissions: ["model.read", "report.download"] as string[] }));

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: (permission: string) => authMock.permissions.includes(permission) }),
}));

type Json = Record<string, unknown>;

function catalog(): Json {
  return structuredClone(fixture) as unknown as Json;
}

function card(number: number): Json | null {
  const source = catalog();
  const campaign = (source.campaigns as Json[]).find((item) => item.number === number);
  if (!campaign) return null;
  return {
    contract_name: "campaign_card_v1",
    schema_version: "1.1.0",
    record_origin: "verified_model_package_artifact",
    package_id: source.package_id,
    model_version: source.model_version,
    model_display_name: source.model_display_name,
    artifact_id: source.artifact_id,
    catalog_version: source.catalog_version,
    period_start: source.period_start,
    period_end: source.period_end,
    roas_level_label: source.roas_level_label,
    notes: source.notes,
    campaign,
    updated_at_utc: source.updated_at_utc,
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function stubServer(listPayload: Json = catalog()) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    if (url.pathname === "/api/v1/campaign-catalog") return jsonResponse(listPayload);
    const match = /^\/api\/v1\/campaign-catalog\/(\d+)$/.exec(url.pathname);
    const payload = match ? card(Number(match[1])) : null;
    if (payload) return jsonResponse(payload);
    return jsonResponse({ error: { code: "CAMPAIGN_NOT_FOUND", message: "test", retryable: false, user_action: "test" } }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderPages(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/campaigns" element={<CampaignCatalogPage />} />
          <Route path="/campaigns/:number" element={<CampaignCardPage />} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  authMock.permissions = ["model.read", "report.download"];
});

describe("past campaigns pages", () => {
  it("reads the filters from the link and writes changes back to it", async () => {
    stubServer();
    renderPages("/campaigns?tab=long&sort=roas");

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(screen.getByRole("tab", { name: /Длиннее 120 дней/ })).toHaveAttribute("aria-selected", "true");

    fireEvent.click(within(screen.getByRole("group", { name: "Надёжность" })).getByRole("button", { name: "1" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/campaigns?tab=long&reliable=1&sort=roas");
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(4);
  });

  it("opens a card and returns to the same filtered list", async () => {
    const fetchMock = stubServer();
    renderPages("/campaigns?tab=long");

    fireEvent.click(within(await screen.findByRole("table")).getByText("70,1"));
    expect(await screen.findByRole("heading", { level: 1, name: "Тестовая кампания 7" })).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/campaigns/7?tab=long");
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/v1/campaign-catalog/7"))).toBe(true);

    fireEvent.click(screen.getByRole("link", { name: "Все кампании" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/campaigns?tab=long");
  });

  it("hides the Excel button from a viewer", async () => {
    authMock.permissions = ["model.read"];
    stubServer();
    renderPages("/campaigns");

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Скачать Excel/ })).not.toBeInTheDocument();
  });

  it("shows the not-published state from the server", async () => {
    stubServer({
      contract_name: "campaign_catalog_v1",
      schema_version: "1.1.0",
      record_origin: "model_package_artifact_unavailable",
      status: "unavailable",
      title: "Прошлые кампании",
      display_text: "Каталог прошлых кампаний для активной модели пока не опубликован.",
      package_id: "pkg_abababababababab_2222222222222222",
      model_version: null,
      model_display_name: null,
      artifact_id: null,
      catalog_version: null,
      period_start: null,
      period_end: null,
      roas_level_label: null,
      summary: null,
      download: null,
      notes: [],
      campaigns: [],
      updated_at_utc: null,
    });
    renderPages("/campaigns");

    expect(await screen.findByText("Каталог пока не опубликован")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("does not show a catalog that fails the contract check", async () => {
    const broken = catalog();
    (broken.summary as Json).weighted_roas = 30;
    stubServer(broken);
    renderPages("/campaigns");

    expect(await screen.findByRole("alert")).toHaveTextContent("Формат каталога не поддерживается");
    expect(screen.queryByText(/ROAS всех кампаний/)).not.toBeInTheDocument();
  });

  it("answers a wrong campaign number without asking the server", async () => {
    const fetchMock = stubServer();
    renderPages("/campaigns/0012abc?q=7");

    expect(await screen.findByRole("alert")).toHaveTextContent("Кампания не найдена");
    expect(screen.getByRole("link", { name: "Все кампании" })).toHaveAttribute("href", "/campaigns?q=7");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports a number that is not in the catalog", async () => {
    stubServer();
    renderPages("/campaigns/383");

    expect(await screen.findByRole("alert")).toHaveTextContent("Кампания не найдена");
  });
});
