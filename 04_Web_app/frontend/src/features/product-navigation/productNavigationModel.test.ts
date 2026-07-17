import { describe, expect, it } from "vitest";
import {
  createCalculationHistoryFixture,
  createHelpCatalogFixture,
} from "../../test/productNavigationFixtures";
import {
  helpSearchParams,
  helpSelectionFromSearch,
  historyEmptyCopy,
  historyQueryFromSearch,
  historySearchParams,
  searchHelpArticles,
} from "./productNavigationModel";

describe("product navigation URL and search model", () => {
  it("round-trips all supported history state through browser query parameters", () => {
    const query = historyQueryFromSearch(new URLSearchParams(
      "status=cancel_requested&search=Кампания&created_from=2026-01-01&created_to=2026-02-01&sort=campaign_asc&page=3&page_size=50",
    ));
    expect(query).toEqual({
      status: "cancel_requested",
      search: "Кампания",
      createdFrom: "2026-01-01",
      createdTo: "2026-02-01",
      sort: "campaign_asc",
      page: 3,
      pageSize: 50,
    });
    expect(historyQueryFromSearch(historySearchParams(query))).toEqual(query);
  });

  it("uses safe defaults for unsupported status, sort and pagination values", () => {
    expect(historyQueryFromSearch(new URLSearchParams(
      "status=private&sort=raw&page=-1&page_size=1000",
    ))).toEqual({
      status: null,
      search: null,
      createdFrom: null,
      createdTo: null,
      sort: "created_desc",
      page: 1,
      pageSize: 25,
    });
  });

  it("distinguishes an empty workspace, filtered result and empty search", () => {
    const history = createCalculationHistoryFixture();
    history.items = [];
    history.summary.all = 3;
    expect(historyEmptyCopy(history, {
      ...historyQueryFromSearch(new URLSearchParams()),
      search: "нет такой кампании",
    }).title).toBe("Поиск ничего не нашел");
    expect(historyEmptyCopy(history, {
      ...historyQueryFromSearch(new URLSearchParams()),
      status: "failed",
    }).title).toBe("Нет результатов по выбранным фильтрам");
    history.summary = { all: 0, active: 0, succeeded: 0, failed: 0, cancelled: 0, timed_out: 0 };
    expect(historyEmptyCopy(history, historyQueryFromSearch(new URLSearchParams())).title)
      .toBe("Расчетов пока нет");
  });

  it("restores help deep links and searches only reviewed metadata", () => {
    const catalog = createHelpCatalogFixture();
    const requestedSection = catalog.sections[2];
    const requestedArticle = requestedSection.articles[0];
    const selection = helpSelectionFromSearch(catalog, new URLSearchParams({
      section: requestedSection.section_id,
      article: requestedArticle.article_id,
    }));
    expect(selection).toEqual({
      sectionId: requestedSection.section_id,
      articleId: requestedArticle.article_id,
    });
    expect(helpSearchParams(selection).toString()).toContain(`article=${requestedArticle.article_id}`);
    expect(searchHelpArticles(catalog, requestedArticle.keywords[0])).toEqual(
      expect.arrayContaining([expect.objectContaining({ article: requestedArticle })]),
    );

    const bodyOnlyNeedle = "только-в-теле-статьи";
    requestedArticle.body.push({ block_type: "paragraph", text: bodyOnlyNeedle });
    expect(searchHelpArticles(catalog, bodyOnlyNeedle)).toEqual([]);
  });
});
