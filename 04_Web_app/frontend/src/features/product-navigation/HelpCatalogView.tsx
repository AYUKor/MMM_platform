import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { HelpCatalogV1 } from "../../shared/api/generated/help-catalog-v1";
import { RefreshNotice } from "./ProductNavigationPageState";
import {
  searchHelpArticles,
  type HelpSelection,
} from "./productNavigationModel";
import styles from "./product-navigation.module.css";

interface HelpCatalogViewProps {
  catalog: HelpCatalogV1;
  selection: HelpSelection;
  refreshMessage?: string | null;
  onSelectionChange: (selection: HelpSelection) => void;
  onRefresh: () => void;
}

const ROUTE_LABELS: Record<string, string> = {
  "/": "Главная",
  "/calculations": "История расчетов",
  "/calculations/new": "Новый расчет",
  "/model": "Модель",
  "/help": "Справка",
};

export function HelpCatalogView({
  catalog,
  selection,
  refreshMessage = null,
  onSelectionChange,
  onRefresh,
}: HelpCatalogViewProps) {
  const [search, setSearch] = useState("");
  const section = catalog.sections.find((item) => item.section_id === selection.sectionId)
    ?? catalog.sections[0];
  const article = section.articles.find((item) => item.article_id === selection.articleId)
    ?? section.articles[0];
  const searchResults = useMemo(
    () => searchHelpArticles(catalog, search),
    [catalog, search],
  );
  const articleIndex = new Map(
    catalog.sections.flatMap((catalogSection) =>
      catalogSection.articles.map((catalogArticle) => [
        catalogArticle.article_id,
        { section: catalogSection, article: catalogArticle },
      ] as const)),
  );

  return (
    <div className={styles.page}>
      <header className={styles.helpHeader}>
        <div>
          <div className={styles.headerLabels}>
            <span className={styles.eyebrow}>Справочные материалы</span>
            {catalog.record_origin === "synthetic_fixture" ? (
              <span className={styles.demoBadge}>Демонстрационные данные</span>
            ) : null}
          </div>
          <h1>Справка</h1>
          <p>Короткие ответы о подготовке данных, сценариях, надежности, медиаплане и отчете.</p>
        </div>
        <label className={styles.helpSearch}>
          <span>Поиск по справке</span>
          <input
            type="search"
            value={search}
            placeholder="Например, S5 или P10"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </header>

      {refreshMessage ? <RefreshNotice message={refreshMessage} onRetry={onRefresh} /> : null}

      {search.trim() ? (
        <section className={styles.helpResults} aria-labelledby="help-search-results-title">
          <div className={styles.sectionHeading}>
            <div>
              <span className={styles.eyebrow}>Поиск</span>
              <h2 id="help-search-results-title">Найденные статьи</h2>
            </div>
            <span>{searchResults.length}</span>
          </div>
          {searchResults.length === 0 ? (
            <div className={styles.inlineEmpty} role="status">
              <strong>Ничего не найдено</strong>
              <span>Попробуйте другое слово или откройте нужный раздел слева.</span>
            </div>
          ) : (
            <ul className={styles.helpResultList}>
              {searchResults.map((result) => (
                <li key={result.article.article_id}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelectionChange({
                        sectionId: result.sectionId,
                        articleId: result.article.article_id,
                      });
                      setSearch("");
                    }}
                  >
                    <span>{result.sectionTitle}</span>
                    <strong>{result.article.title}</strong>
                    <small>{result.article.summary}</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      <div className={styles.helpLayout}>
        <aside className={styles.helpNavigation} aria-label="Разделы справки">
          <span className={styles.eyebrow}>Разделы</span>
          <nav>
            {catalog.sections.map((item) => {
              const active = item.section_id === section.section_id;
              return (
                <button
                  type="button"
                  key={item.section_id}
                  className={active ? styles.helpSectionActive : styles.helpSection}
                  aria-current={active ? "page" : undefined}
                  onClick={() => onSelectionChange({
                    sectionId: item.section_id,
                    articleId: item.articles[0].article_id,
                  })}
                >
                  <span>{String(item.order).padStart(2, "0")}</span>
                  {item.title}
                </button>
              );
            })}
          </nav>
          <Link className={styles.secondaryLink} to="/calculations/new">Начать новый расчет</Link>
        </aside>

        <section className={styles.helpArticle} aria-label="Статья справки">
          <nav className={styles.articleNavigation} aria-label="Статьи раздела">
            {section.articles.map((item) => {
              const active = item.article_id === article.article_id;
              return (
                <button
                  type="button"
                  key={item.article_id}
                  className={active ? styles.articleTabActive : styles.articleTab}
                  aria-current={active ? "page" : undefined}
                  onClick={() => onSelectionChange({
                    sectionId: section.section_id,
                    articleId: item.article_id,
                  })}
                >
                  {item.title}
                </button>
              );
            })}
          </nav>

          <article className={styles.articleBody}>
            <span className={styles.eyebrow}>{section.title}</span>
            <h2>{article.title}</h2>
            <p className={styles.articleSummary}>{article.summary}</p>
            <div className={styles.bodyBlocks}>
              {article.body.map((block, index) => {
                if (block.block_type === "paragraph") {
                  return <p key={`${block.block_type}-${index}`}>{block.text}</p>;
                }
                if (block.block_type === "steps") {
                  return (
                    <ol key={`${block.block_type}-${index}`}>
                      {block.items.map((item, itemIndex) => (
                        <li key={`${itemIndex}-${item}`}><span>{itemIndex + 1}</span><p>{item}</p></li>
                      ))}
                    </ol>
                  );
                }
                return (
                  <aside
                    key={`${block.block_type}-${index}`}
                    className={block.tone === "warning" ? styles.helpNoteWarning : styles.helpNote}
                  >
                    <strong>{block.title}</strong>
                    <p>{block.text}</p>
                  </aside>
                );
              })}
            </div>
          </article>

          {(article.related_article_ids.length > 0 || article.related_routes.length > 0) ? (
            <aside className={styles.relatedContent} aria-labelledby="related-content-title">
              <h3 id="related-content-title">По теме</h3>
              {article.related_article_ids.length > 0 ? (
                <ul>
                  {article.related_article_ids.map((articleId) => {
                    const related = articleIndex.get(articleId);
                    if (!related) return null;
                    return (
                      <li key={articleId}>
                        <button
                          type="button"
                          onClick={() => onSelectionChange({
                            sectionId: related.section.section_id,
                            articleId: related.article.article_id,
                          })}
                        >
                          {related.article.title}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : null}
              {article.related_routes.length > 0 ? (
                <div className={styles.relatedRoutes}>
                  {article.related_routes.map((route) => (
                    <Link key={route} to={route}>{ROUTE_LABELS[route] ?? "Открыть раздел"}</Link>
                  ))}
                </div>
              ) : null}
            </aside>
          ) : null}
        </section>
      </div>
    </div>
  );
}
