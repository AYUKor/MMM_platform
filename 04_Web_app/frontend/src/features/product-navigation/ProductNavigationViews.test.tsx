import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import {
  createCalculationHistoryFixture,
  createHelpCatalogFixture,
  createWorkspaceHomeFixture,
} from "../../test/productNavigationFixtures";
import type { GeoCatalogV1 } from "../../shared/api/generated/geo-catalog-v1";
import type { ModelOverviewV2 } from "../../shared/api/generated/model-overview-v2";
import type { ModelPassportV2 } from "../../shared/api/generated/model-passport-v2";
import type { WorkspaceGeoBudgetV1 } from "../../shared/api/generated/workspace-geo-budget-v1";
import { HelpCatalogView } from "./HelpCatalogView";
import { HistoryView } from "./HistoryView";
import { HomeView } from "./HomeView";
import { ModelOverviewView } from "./ModelOverviewView";
import { historyQueryFromSearch } from "./productNavigationModel";

function renderInRouter(node: React.ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

function createGeoCatalogFixture(): GeoCatalogV1 {
  return {
    contract_name: "geo_catalog_v1",
    schema_version: "1.0.0",
    catalog_version: "catalog-synthetic-v1",
    coordinates_source: "Synthetic test source",
    coordinates_source_version_or_date: "2026-07-18",
    coordinates_license: "CC BY 4.0",
    status: "unavailable",
    display_text: "Координаты пока не опубликованы.",
    geographies_n: 2,
    coverage: {
      status: "unavailable",
      located_geographies_n: 0,
      unlocated_geographies_n: 2,
      unlocated_geographies: [
        { geo_id: "geo_1111111111111111", geo_display_name: "Москва" },
        { geo_id: "geo_2222222222222222", geo_display_name: "Казань" },
      ],
    },
    entries: [
      { geo_id: "geo_1111111111111111", geo_display_name: "Москва", latitude: null, longitude: null, coordinates_status: "unavailable", region_id: null, region_display_name: null },
      { geo_id: "geo_2222222222222222", geo_display_name: "Казань", latitude: null, longitude: null, coordinates_status: "unavailable", region_id: null, region_display_name: null },
    ],
  };
}

function createGeoBudgetFixture(): WorkspaceGeoBudgetV1 {
  return {
    contract_name: "workspace_geo_budget_v1",
    schema_version: "1.0.0",
    catalog_version: "catalog-synthetic-v1",
    status: "unavailable",
    display_text: "Сводка готова без координат.",
    total_budget_rub: 12_000_000,
    campaigns_n: 2,
    geographies_n: 2,
    coverage: {
      status: "unavailable",
      located_geographies_n: 0,
      unlocated_geographies_n: 2,
      unlocated_geographies: [
        { geo_id: "geo_1111111111111111", geo_display_name: "Москва" },
        { geo_id: "geo_2222222222222222", geo_display_name: "Казань" },
      ],
      located_budget_rub: 0,
      unlocated_budget_rub: 12_000_000,
      unlocated_budget_share: 1,
    },
    rows: [
      { geo_id: "geo_1111111111111111", geo_display_name: "Москва", latitude: null, longitude: null, coordinates_status: "unavailable", region_id: null, region_display_name: null, total_budget_rub: 7_000_000, campaigns_n: 2, budget_share: 7 / 12 },
      { geo_id: "geo_2222222222222222", geo_display_name: "Казань", latitude: null, longitude: null, coordinates_status: "unavailable", region_id: null, region_display_name: null, total_budget_rub: 5_000_000, campaigns_n: 1, budget_share: 5 / 12 },
    ],
  };
}

function createModelPassportV2Fixture(): ModelPassportV2 {
  return {
    contract_name: "model_passport_v2",
    schema_version: "2.0.0",
    record_origin: "synthetic_fixture",
    serving: {
      serving_policy_version: "turnover_serving_v1",
      target_id: "turnover",
      core_target: "turnover_per_user",
      serving_targets_n: 1,
      active_serving_models_n: 4,
      research_models_in_package_n: 12,
      calculation_allowed: true,
      production_claim_allowed: false,
    },
    package: {
      registry_channel: "preprod",
      registry_event_id: "registry_event_synthetic",
      package_id: "pkg_1111111111111111_2222222222222222",
      package_fingerprint: "a".repeat(64),
      model_run_id: "run_synthetic",
      package_stage: "posterior_ready",
      activation_status: "preprod_restricted",
      package_schema_version: "1.0.0",
      gate_policy_version: "gate-v1",
    },
    data: {
      grain: "daily",
      training_period: { start_date: "2023-01-01", end_date: "2025-12-31" },
      development_shadow_period: {
        start_date: "2026-01-01",
        end_date: "2026-03-31",
        purpose: "development_shadow_not_sealed_oot",
      },
    },
    coverage: {
      segments: ["ТС5/Онлайн"],
      channels: [{ channel_id: "Digital_Performance", channel_display_name: "Цифровая реклама" }],
      targets: [{ target_id: "turnover", core_target: "turnover_per_user" }],
      geographies_n: 15,
      capability_cells_n: 1,
    },
    validation: {
      historical_replay: { status: "passed", generated_at_utc: "2026-07-17T10:00:00Z", reason_code: null, display_text: "Historical replay пройден." },
      sealed_oot: { status: "unavailable", generated_at_utc: null, reason_code: "not_available", display_text: "Sealed OOT пока недоступен." },
      production_blockers: [{ code: "research_preprod", display_text: "Модель не утверждена для production-использования." }],
    },
    channel_policies: [{
      segment: "ТС5/Онлайн",
      channel_id: "Digital_Performance",
      channel_display_name: "Цифровая реклама",
      target: "turnover",
      allowed_use: "primary",
      forecast_action: "forecast",
      optimizer_action: "optimize",
      display_text: "Канал доступен в подтвержденной зоне.",
    }],
    caveats: [{ code: "allocation_only", display_text: "Рекомендация относится только к распределению бюджета." }],
  };
}

function createModelOverviewV2Fixture(passport = createModelPassportV2Fixture()): ModelOverviewV2 {
  return {
    contract_name: "model_overview_v2",
    schema_version: "2.0.0",
    serving: { ...passport.serving },
    summary: {
      training_period: { ...passport.data.training_period },
      package_status: "posterior_ready",
      activation_status: "preprod_restricted",
      calculation_allowed: passport.serving.calculation_allowed,
      historical_replay: { ...passport.validation.historical_replay },
      sealed_oot: { ...passport.validation.sealed_oot },
    },
    channel_policies: passport.channel_policies.map((item) => ({ ...item })),
    limitations: [{
      code: "allocation_only",
      status: "active",
      title: "Рекомендация только по распределению",
      display_text: "Система не принимает решение о запуске кампании.",
      recommended_action: "Сопоставьте результат с бизнес-целями.",
    }],
  };
}

describe("Phase D product-navigation views", () => {
  it("renders backend zero as zero and missing recent facts as Нет данных on Home", () => {
    const home = createWorkspaceHomeFixture();
    home.summary.queued = 0;
    home.recent_calculations[1].total_budget_rub = null;
    home.recent_calculations[1].warnings_count = null;
    renderInRouter(
      <HomeView
        home={home}
        geoBudget={createGeoBudgetFixture()}
        geoCatalog={createGeoCatalogFixture()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText("Демонстрационные данные")).toBeInTheDocument();
    expect(within(screen.getByText("В очереди").parentElement as HTMLElement).getByText("0"))
      .toBeInTheDocument();
    expect(screen.getAllByText("Нет данных").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Открыть ход расчета" })).toHaveAttribute(
      "href",
      home.active_calculations[0].progress_path,
    );
    const succeededRow = screen.getByText(home.recent_calculations[0].campaign_name).closest("li");
    const failedRow = screen.getByText(home.recent_calculations[1].campaign_name).closest("li");
    expect(succeededRow).not.toBeNull();
    expect(failedRow).not.toBeNull();
    expect(within(succeededRow as HTMLElement).getByText("Результат")).toBeInTheDocument();
    expect(within(succeededRow as HTMLElement).getByText("Доступен")).toBeInTheDocument();
    expect(within(succeededRow as HTMLElement).getByText("Готов")).toBeInTheDocument();
    expect(within(failedRow as HTMLElement).getByText("Результат")).toBeInTheDocument();
    expect(within(failedRow as HTMLElement).getAllByText("Не готов")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "Бюджет проверенных кампаний по географиям" })).toBeInTheDocument();
    expect(screen.getByText("Карта будет доступна после подключения утвержденного справочника координат."))
      .toBeInTheDocument();
    expect(screen.getByText("Бюджет в проверенных кампаниях").parentElement as HTMLElement)
      .toHaveTextContent("12 млн ₽");
    expect(screen.getAllByText("Дополнительный оборот").length).toBeGreaterThan(0);
  });

  it("renders history rows from the projection and sends filters back to the page", () => {
    const history = createCalculationHistoryFixture();
    const onQueryChange = vi.fn();
    const query = historyQueryFromSearch(new URLSearchParams());
    renderInRouter(
      <HistoryView
        history={history}
        query={query}
        onQueryChange={onQueryChange}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "История расчетов" })).toBeInTheDocument();
    expect(screen.getAllByText(history.items[0].campaign_name).length).toBeGreaterThan(0);
    const search = screen.getByRole("searchbox", { name: "Поиск" });
    expect(search).toHaveAttribute("placeholder", "Поиск по названию кампании");
    expect(screen.queryByPlaceholderText("Кампания, сегмент или номер расчета"))
      .not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "  кампания  " } });
    fireEvent.submit(screen.getByLabelText("Поиск").closest("form") as HTMLFormElement);
    expect(onQueryChange).toHaveBeenCalledWith(expect.objectContaining({
      search: "кампания",
      page: 1,
    }));
  });

  it("renders one turnover target, serving inventory and research/preprod boundaries", () => {
    const passport = createModelPassportV2Fixture();
    const overview = createModelOverviewV2Fixture(passport);
    const { container } = renderInRouter(
      <ModelOverviewView passport={passport} overview={overview} onRefresh={vi.fn()} />,
    );

    expect(screen.getByRole("heading", { name: "Дополнительный оборот" })).toBeInTheDocument();
    expect(screen.getByText("Serving-показателей").parentElement as HTMLElement).toHaveTextContent("1");
    expect(screen.getByText("Активных serving-моделей").parentElement as HTMLElement).toHaveTextContent("4");
    expect(screen.getByText("Исследовательских моделей в пакете").parentElement as HTMLElement).toHaveTextContent("12");
    expect(screen.getByText(/Модели заказов и среднего чека сохранены для исследований/)).toBeInTheDocument();
    expect(screen.getAllByText("Цифровая реклама").length).toBeGreaterThan(0);
    expect(screen.getByText("Historical replay пройден.")).toBeInTheDocument();
    expect(screen.getByText("Sealed OOT пока недоступен.")).toBeInTheDocument();
    expect(container).not.toHaveTextContent("turnover_per_user");
    expect(container).not.toHaveTextContent("Digital_Performance");
    expect(container).not.toHaveTextContent(passport.package.package_id);
    expect(container).not.toHaveTextContent(passport.package.model_run_id);
    expect(container).not.toHaveTextContent("posterior_ready");
    expect(container).not.toHaveTextContent("preprod_restricted");
  });

  it("shows calculation unavailable as a controlled non-production state", () => {
    const passport = createModelPassportV2Fixture();
    passport.serving.calculation_allowed = false;
    const overview = createModelOverviewV2Fixture(passport);
    renderInRouter(
      <ModelOverviewView passport={passport} overview={overview} onRefresh={vi.fn()} />,
    );

    expect(screen.getByText("Расчеты недоступны")).toBeInTheDocument();
    expect(screen.getAllByText("Research / preprod").length).toBeGreaterThan(0);
  });

  it("navigates help articles and performs local title/summary/keyword search", () => {
    const catalog = createHelpCatalogFixture();
    const firstSection = catalog.sections[0];
    const firstArticle = firstSection.articles[0];
    const onSelectionChange = vi.fn();
    renderInRouter(
      <HelpCatalogView
        catalog={catalog}
        selection={{ sectionId: firstSection.section_id, articleId: firstArticle.article_id }}
        onSelectionChange={onSelectionChange}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: firstArticle.title })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Поиск по справке"), {
      target: { value: firstArticle.keywords[0] },
    });
    expect(screen.getByRole("heading", { name: "Найденные статьи" })).toBeInTheDocument();
    const searchResult = screen.getAllByRole("button", { name: new RegExp(firstArticle.title) })[0];
    fireEvent.click(searchResult);
    expect(onSelectionChange).toHaveBeenCalledWith({
      sectionId: firstSection.section_id,
      articleId: firstArticle.article_id,
    });
  });

  it("filters legacy multi-target claims from help presentation and search", () => {
    const catalog = createHelpCatalogFixture();
    const firstSection = catalog.sections[0];
    const firstArticle = firstSection.articles[0];
    firstArticle.title = "Три целевых показателя";
    firstArticle.summary = "Количество заказов, оборот и средний чек.";
    firstArticle.body = [{
      block_type: "paragraph",
      text: "Дополнительные заказы показываются рядом с оборотом.",
    }];
    firstArticle.keywords = ["orders_per_user", "avg_basket"];

    renderInRouter(
      <HelpCatalogView
        catalog={catalog}
        selection={{ sectionId: firstSection.section_id, articleId: firstArticle.article_id }}
        onSelectionChange={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Материал обновляется" })).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    for (const forbidden of [
      "Три целевых показателя",
      "Количество заказов",
      "средний чек",
      "Дополнительные заказы",
      "orders_per_user",
      "avg_basket",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });
});
