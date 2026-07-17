import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import {
  createCalculationHistoryFixture,
  createHelpCatalogFixture,
  createModelOverviewFixture,
  createWorkspaceHomeFixture,
} from "../../test/productNavigationFixtures";
import { HelpCatalogView } from "./HelpCatalogView";
import { HistoryView } from "./HistoryView";
import { HomeView } from "./HomeView";
import { ModelOverviewView } from "./ModelOverviewView";
import { historyQueryFromSearch } from "./productNavigationModel";

function renderInRouter(node: React.ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

describe("Phase D product-navigation views", () => {
  it("renders backend zero as zero and missing recent facts as Нет данных on Home", () => {
    const home = createWorkspaceHomeFixture();
    home.summary.queued = 0;
    home.recent_calculations[1].total_budget_rub = null;
    home.recent_calculations[1].warnings_count = null;
    renderInRouter(<HomeView home={home} onRefresh={vi.fn()} />);

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

  it("shows an honest unavailable model and never replaces missing version history", () => {
    const overview = createModelOverviewFixture();
    overview.active_model = {
      ...overview.active_model,
      status: { code: "unavailable", display_text: "Модель недоступна" },
      model_id: null,
      display_name: null,
      version: null,
      published_at_utc: null,
      framework: null,
      training_period: null,
      supported_scope: null,
    };
    overview.versions = [];
    renderInRouter(<ModelOverviewView overview={overview} onRefresh={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Сведения об активной модели пока недоступны" }))
      .toBeInTheDocument();
    expect(screen.getByText("История версий пока недоступна")).toBeInTheDocument();
    expect(screen.queryByText(overview.active_model.model_id ?? "never-visible-model-id"))
      .not.toBeInTheDocument();
  });

  it("renders published model versions and complete limitation copy without internal fields", () => {
    const overview = createModelOverviewFixture();
    overview.versions[0].model_run_id = "internal_model_run_should_not_render";
    const { container } = renderInRouter(
      <ModelOverviewView overview={overview} onRefresh={vi.fn()} />,
    );

    expect(screen.getAllByText("Публикация модели")).toHaveLength(2);
    expect(screen.getByText("Активная")).toBeInTheDocument();
    expect(screen.getByText("Зарегистрирована")).toBeInTheDocument();
    for (const limitation of overview.limitations) {
      expect(screen.getByText(limitation.title)).toBeInTheDocument();
      expect(screen.getByText(limitation.display_text)).toBeInTheDocument();
      expect(screen.getByText(`Что учитывать: ${limitation.recommended_action}`)).toBeInTheDocument();
    }
    expect(container).not.toHaveTextContent(overview.versions[0].model_id);
    expect(container).not.toHaveTextContent("internal_model_run_should_not_render");
    expect(container).not.toHaveTextContent(overview.versions[0].package_stage);
    expect(container).not.toHaveTextContent(overview.versions[0].activation_status);
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
});
