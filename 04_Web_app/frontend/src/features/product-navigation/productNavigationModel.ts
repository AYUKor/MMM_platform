import type { CalculationHistoryV1 } from "../../shared/api/generated/calculation-history-v1";
import type { HelpCatalogV1 } from "../../shared/api/generated/help-catalog-v1";
import type {
  HistoryQuery,
  HistorySort,
  HistoryStatus,
} from "../../shared/api/product-navigation-client";

export const HISTORY_STATUS_OPTIONS = [
  { value: null, label: "Все" },
  { value: "active", label: "В работе" },
  { value: "queued", label: "В очереди" },
  { value: "running", label: "Выполняются" },
  { value: "cancel_requested", label: "Отмена запрошена" },
  { value: "succeeded", label: "Завершены" },
  { value: "failed", label: "С ошибкой" },
  { value: "cancelled", label: "Отменены" },
  { value: "timed_out", label: "Превышено время" },
] as const;

export const HISTORY_SORT_OPTIONS = [
  { value: "created_desc", label: "Сначала новые" },
  { value: "created_asc", label: "Сначала старые" },
  { value: "completed_desc", label: "Недавно завершенные" },
  { value: "campaign_asc", label: "По названию кампании" },
] as const;

export interface NormalizedHistoryQuery {
  status: HistoryQuery["status"];
  search: string | null;
  createdFrom: string | null;
  createdTo: string | null;
  sort: NonNullable<HistoryQuery["sort"]>;
  page: number;
  pageSize: number;
}

export interface HelpSelection {
  sectionId: HelpCatalogV1["sections"][number]["section_id"];
  articleId: string;
}

interface NavigationErrorLike {
  message?: unknown;
  name?: unknown;
  status?: unknown;
}

export interface NavigationErrorCopy {
  title: string;
  description: string;
  retryable: boolean;
}

const HISTORY_STATUSES: ReadonlySet<HistoryStatus> = new Set(
  HISTORY_STATUS_OPTIONS.flatMap((item) => item.value === null ? [] : [item.value]),
);
const HISTORY_SORTS: ReadonlySet<HistorySort> = new Set(
  HISTORY_SORT_OPTIONS.map((item) => item.value),
);
const DEFAULT_SORT: NormalizedHistoryQuery["sort"] = "created_desc";
const DEFAULT_PAGE_SIZE = 25;

function positiveInteger(value: string | null, fallback: number): number {
  if (value === null || !/^\d+$/.test(value)) return fallback;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function nullableTrimmed(value: string | null): string | null {
  if (value === null) return null;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

function isHistoryStatus(value: string | null): value is HistoryStatus {
  return value !== null && HISTORY_STATUSES.has(value as HistoryStatus);
}

function isHistorySort(value: string | null): value is HistorySort {
  return value !== null && HISTORY_SORTS.has(value as HistorySort);
}

function errorLike(error: unknown): NavigationErrorLike {
  return error !== null && typeof error === "object"
    ? error as NavigationErrorLike
    : {};
}

export function navigationErrorStatus(error: unknown): number | null {
  const status = errorLike(error).status;
  return typeof status === "number" && Number.isInteger(status) ? status : null;
}

export function navigationErrorMessage(error: unknown): string | null {
  const message = errorLike(error).message;
  return typeof message === "string" && message.trim().length > 0
    ? message
    : null;
}

export function navigationErrorCopy(error: unknown): NavigationErrorCopy {
  const value = errorLike(error);
  const status = navigationErrorStatus(error);
  if (value.name === "UnsupportedProductNavigationContractError" || value.name === "UnsupportedBusinessSemanticsContractError") {
    return {
      title: "Формат сведений не поддерживается",
      description: "Ответ не прошел защитную проверку и поэтому не показан.",
      retryable: true,
    };
  }
  if (value.name === "BusinessSemanticsNotReadyError") {
    return {
      title: "Сведения еще готовятся",
      description: "Расчет или публикация данных еще не завершены. Повторите запрос позже.",
      retryable: true,
    };
  }
  if (status === 404) {
    return {
      title: "Раздел не найден",
      description: "Проверьте адрес или вернитесь в рабочее пространство.",
      retryable: false,
    };
  }
  if (status === 409) {
    return {
      title: "Опубликованные сведения временно не согласованы",
      description: "Данные обновляются. Повторите запрос через несколько секунд.",
      retryable: true,
    };
  }
  if (status === 422) {
    return {
      title: "Параметры запроса не приняты",
      description: navigationErrorMessage(error) ?? "Проверьте выбранные фильтры.",
      retryable: true,
    };
  }
  if (status === 503) {
    return {
      title: "Сведения временно недоступны",
      description: "Повторите запрос после восстановления доступа.",
      retryable: true,
    };
  }
  return {
    title: "Не удалось загрузить сведения",
    description: "Проверьте соединение и повторите попытку.",
    retryable: true,
  };
}

export function historyQueryFromSearch(
  searchParams: URLSearchParams,
): NormalizedHistoryQuery {
  const status = searchParams.get("status");
  const sort = searchParams.get("sort");
  const pageSize = positiveInteger(searchParams.get("page_size"), DEFAULT_PAGE_SIZE);
  return {
    status: isHistoryStatus(status) ? status : null,
    search: nullableTrimmed(searchParams.get("search")),
    createdFrom: nullableTrimmed(searchParams.get("created_from")),
    createdTo: nullableTrimmed(searchParams.get("created_to")),
    sort: isHistorySort(sort) ? sort : DEFAULT_SORT,
    page: positiveInteger(searchParams.get("page"), 1),
    pageSize: pageSize <= 100 ? pageSize : DEFAULT_PAGE_SIZE,
  };
}

export function historySearchParams(
  query: NormalizedHistoryQuery,
): URLSearchParams {
  const params = new URLSearchParams();
  if (query.status) params.set("status", query.status);
  if (query.search) params.set("search", query.search);
  if (query.createdFrom) params.set("created_from", query.createdFrom);
  if (query.createdTo) params.set("created_to", query.createdTo);
  if (query.sort !== DEFAULT_SORT) params.set("sort", query.sort);
  if (query.page !== 1) params.set("page", String(query.page));
  if (query.pageSize !== DEFAULT_PAGE_SIZE) params.set("page_size", String(query.pageSize));
  return params;
}

export function hasHistoryFilters(query: NormalizedHistoryQuery): boolean {
  return Boolean(
    query.status || query.search || query.createdFrom || query.createdTo,
  );
}

export function historyEmptyCopy(
  history: CalculationHistoryV1,
  query: NormalizedHistoryQuery,
): { title: string; description: string } {
  if (history.summary.all === 0) {
    return {
      title: "Расчетов пока нет",
      description: "Создайте первый расчет — он появится в истории после запуска.",
    };
  }
  if (query.search) {
    return {
      title: "Поиск ничего не нашел",
      description: "Измените запрос или очистите фильтры.",
    };
  }
  if (hasHistoryFilters(query)) {
    return {
      title: "Нет результатов по выбранным фильтрам",
      description: "Измените период или статус и повторите поиск.",
    };
  }
  return {
    title: "На этой странице нет расчетов",
    description: "Вернитесь на предыдущую страницу истории.",
  };
}

export function helpSelectionFromSearch(
  catalog: HelpCatalogV1,
  searchParams: URLSearchParams,
): HelpSelection {
  const requestedSection = searchParams.get("section");
  const section = catalog.sections.find((item) => item.section_id === requestedSection)
    ?? catalog.sections[0];
  const requestedArticle = searchParams.get("article");
  const article = section.articles.find((item) => item.article_id === requestedArticle)
    ?? section.articles[0];
  return { sectionId: section.section_id, articleId: article.article_id };
}

export function helpSearchParams(selection: HelpSelection): URLSearchParams {
  return new URLSearchParams({
    section: selection.sectionId,
    article: selection.articleId,
  });
}

export function searchHelpArticles(
  catalog: HelpCatalogV1,
  query: string,
): Array<{
  sectionId: HelpSelection["sectionId"];
  sectionTitle: string;
  article: HelpCatalogV1["sections"][number]["articles"][number];
}> {
  const normalized = query.trim().toLocaleLowerCase("ru-RU");
  if (!normalized) return [];
  return catalog.sections.flatMap((section) =>
    section.articles
      .filter((article) => [
        article.title,
        article.summary,
        ...article.keywords,
      ].some((value) => value.toLocaleLowerCase("ru-RU").includes(normalized)))
      .map((article) => ({
        sectionId: section.section_id,
        sectionTitle: section.title,
        article,
      })),
  );
}
