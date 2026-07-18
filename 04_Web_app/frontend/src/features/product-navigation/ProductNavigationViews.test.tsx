import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import {
  createCalculationHistoryFixture,
  createHelpCatalogFixture,
  createWorkspaceHomeFixture,
} from "../../test/productNavigationFixtures";
import type { HistoricalModelGeoBudgetV1 } from "../../shared/api/generated/historical-model-geo-budget-v1";
import type { ModelOverviewV2 } from "../../shared/api/generated/model-overview-v2";
import type { ModelPassportV2 } from "../../shared/api/generated/model-passport-v2";
import { HelpCatalogView } from "./HelpCatalogView";
import { HistoryView } from "./HistoryView";
import { HomeView } from "./HomeView";
import { ModelOverviewView } from "./ModelOverviewView";
import { historyQueryFromSearch } from "./productNavigationModel";

function renderInRouter(node: React.ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

function createHistoricalGeoBudgetFixture(): HistoricalModelGeoBudgetV1 {
  const totalBudgetRub = 8_687_024_294.654741;
  return {
    contract_name: "historical_model_geo_budget_v1",
    schema_version: "1.0.0",
    record_origin: "verified_model_package_artifact",
    status: "available",
    title: "Исторический рекламный бюджет в данных модели",
    display_text: "Исторические расходы доступны для всех географий.",
    period_display_text: "Период данных: 01.01.2025 — 31.05.2026",
    package_id: "pkg_synthetic_history_2026",
    model_version: "model-synthetic-v1",
    artifact_id: "artifact_111111111111111111111111",
    artifact_version: "historical_geo_budget_v1",
    catalog_version: "catalog-synthetic-v1",
    period_start: "2025-01-01",
    period_end: "2026-05-31",
    spend_columns_version: "spend-columns-synthetic-v1",
    total_budget_rub: totalBudgetRub,
    geographies_n: 2,
    coverage: {
      status: "available",
      located_geographies_n: 2,
      unlocated_geographies_n: 0,
      unlocated_geographies: [],
      located_budget_rub: totalBudgetRub,
      unlocated_budget_rub: 0,
      unlocated_budget_share: 0,
    },
    rows: [
      { geo_id: "geo_1111111111111111", geo_display_name: "Москва", latitude: 55.7558, longitude: 37.6173, coordinates_status: "canonical", historical_total_budget_rub: 5_000_000_000, budget_share: 5_000_000_000 / totalBudgetRub, active_days_n: 300, active_rows_n: 800 },
      { geo_id: "geo_2222222222222222", geo_display_name: "Казань", latitude: 55.7963, longitude: 49.1088, coordinates_status: "canonical", historical_total_budget_rub: totalBudgetRub - 5_000_000_000, budget_share: (totalBudgetRub - 5_000_000_000) / totalBudgetRub, active_days_n: 240, active_rows_n: 620 },
    ],
    limitations: [{ code: "historical_spend_only", display_text: "Показаны фактические рекламные расходы из данных активной модели." }],
    updated_at_utc: "2026-07-19T09:00:00Z",
  };
}

function createUnavailableHistoricalGeoBudgetFixture(): HistoricalModelGeoBudgetV1 {
  return {
    ...createHistoricalGeoBudgetFixture(),
    record_origin: "model_package_artifact_unavailable",
    status: "unavailable",
    display_text: "Исторические расходы активной модели временно недоступны.",
    period_display_text: "Период данных временно недоступен.",
    model_version: null,
    artifact_id: null,
    artifact_version: null,
    period_start: null,
    period_end: null,
    spend_columns_version: null,
    total_budget_rub: null,
    geographies_n: 0,
    coverage: {
      status: "unavailable",
      located_geographies_n: 0,
      unlocated_geographies_n: 0,
      unlocated_geographies: [],
      located_budget_rub: 0,
      unlocated_budget_rub: 0,
      unlocated_budget_share: null,
    },
    rows: [],
    limitations: [{ code: "historical_artifact_unavailable", display_text: "Подтвержденный исторический агрегат для выбранной модели пока не опубликован." }],
    updated_at_utc: null,
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
        historicalGeoBudget={createHistoricalGeoBudgetFixture()}
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
    const historicalSection = screen.getByRole("heading", {
      name: "Исторический рекламный бюджет в данных модели",
    }).closest("section");
    expect(historicalSection).not.toBeNull();
    expect(within(historicalSection as HTMLElement).getByText("Общий рекламный бюджет").parentElement as HTMLElement)
      .toHaveTextContent("8,7 млрд ₽");
    expect(within(historicalSection as HTMLElement).getByText("Географий").parentElement as HTMLElement).toHaveTextContent("2");
    expect(within(historicalSection as HTMLElement).getByText("Период данных", { exact: true }).parentElement as HTMLElement)
      .toHaveTextContent("01.01.2025 — 31.05.2026");
    expect(within(historicalSection as HTMLElement).getByText("Покрытие карты").parentElement as HTMLElement).toHaveTextContent("2 из 2");
    expect(within(historicalSection as HTMLElement).queryByText("Кампании", { exact: true })).not.toBeInTheDocument();
    expect(screen.getAllByText("Дополнительный оборот").length).toBeGreaterThan(0);
  });

  it("keeps an unavailable historical artifact controlled without fabricated zero facts", () => {
    renderInRouter(
      <HomeView
        home={createWorkspaceHomeFixture()}
        historicalGeoBudget={createUnavailableHistoricalGeoBudgetFixture()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText("Карта пока недоступна", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Исторические расходы активной модели временно недоступны."))
      .toBeInTheDocument();
    const historicalSection = screen.getByRole("heading", {
      name: "Исторический рекламный бюджет в данных модели",
    }).closest("section");
    expect(historicalSection).not.toBeNull();
    for (const label of ["Общий рекламный бюджет", "Географий", "Период данных", "Покрытие карты"]) {
      expect(within(historicalSection as HTMLElement).getByText(label, { exact: true }).parentElement as HTMLElement)
        .toHaveTextContent("Нет данных");
    }
    expect(within(historicalSection as HTMLElement).queryByText("0 ₽", { exact: true })).not.toBeInTheDocument();
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
