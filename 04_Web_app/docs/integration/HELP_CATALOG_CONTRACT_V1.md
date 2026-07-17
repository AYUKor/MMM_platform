# Help Catalog Contract V1

## Назначение

`GET /api/v1/help/catalog` возвращает versioned structured content для страницы
Справки. Frontend не читает Markdown, filesystem или произвольный HTML.

## Source

Единственный source v1:

`04_Web_app/content/help_catalog_v1.json`

Файл проходит Python semantic validation и Draft 2020-12 JSON Schema до
публикации. Он является reviewed product content, а не автоматически
сгенерированной документацией.

## Разделы

Порядок фиксирован:

1. Как начать;
2. Подготовка данных;
3. Сценарии S1-S6;
4. Как читать результат;
5. Надежность;
6. Медиаплан;
7. Отчет;
8. Частые ошибки;
9. Ограничения.

Каждый раздел содержит минимум одну статью. `section_id`, `article_id` и order
стабильны; related article IDs обязаны существовать.

## Safe body blocks

Разрешены только три типа:

- `paragraph`;
- `steps`;
- `note` с tone `info` или `warning`.

HTML, script/event handlers, `javascript:` links, data-HTML, workstation paths
и внутренние технические термины отклоняются. Related routes ограничены
утвержденным набором `/`, `/calculations`, `/calculations/new`, `/model`,
`/help`.

## Product claims

Catalog описывает только реализованные semantics:

- incremental effect против варианта без кампании;
- P10/P50/P90;
- S1-S6 и allocation-only recommendation;
- support/reliability caveats;
- diagnostic-only orders;
- marketer report;
- explicit unavailable daily plan, map, reliability score и working XLSX.

Статьи, версии модели и пользовательская активность не генерируются из
предположений.

## Errors

- `409 PRODUCT_NAVIGATION_INCONSISTENT`: content нарушает структуру, links или
  relations;
- `422 PRODUCT_NAVIGATION_QUERY_INVALID`: endpoint получил query parameters;
- `503 PRODUCT_NAVIGATION_UNAVAILABLE`: catalog file временно нельзя прочитать.

Frontend обязан fail closed для неизвестной schema version и не должен
рендерить raw markup.
