# Scenario Media Plan Contract V1

## Endpoint

```text
GET /api/v1/jobs/{job_id}/media-plan
    ?scenario_id=S06
    &page=1
    &page_size=100
    &channel=...
    &geo=...
```

`scenario_id` обязателен и принимает S01-S06. `page` начинается с 1,
`page_size` принимает 1-500. `channel` и `geo` являются exact-match filters.
Repeated, empty или unknown query parameters дают controlled 422.

Параметр `date` зарезервирован, но сейчас дает 422: canonical scenario plans
не имеют daily grain.

## Source and integrity

Источник строк - опубликованный и hash-checked
`recommended_allocations_csv`. Ответ содержит `source_artifact.artifact_id` и
`source_artifact.sha256`; local path и raw candidate name не публикуются.

Scenario-to-candidate mapping читается из:

- S01-S05: `scenario_results_csv`;
- S06: canonical S06 row из `decision_pool_csv`; для совместимости с более
  ранним output, где выбранный S06 отсутствует в pool, разрешен только exact
  canonical S06 row из `recommendations_csv`.

Safe/raw candidates и canonical recommendation остаются разными понятиями.
Endpoint не выбирает candidate заново.

## Grain and row semantics

Текущий grain фиксирован:

```text
campaign × scenario × segment × geo × channel, total campaign period
```

Поэтому `date=null`, а `grain="geo_channel_total"`. Одна строка содержит:

- source S01 budget;
- выбранный scenario budget;
- delta RUB;
- delta percent, либо `null`, если source budget равен zero;
- source и selected shares;
- browser-safe quality status и explanation.

Missing cell не заполняется нулем. Selected scenario обязан иметь тот же набор
разрешенных cells, что и S01; появление новой или исчезновение source cell
закрывает projection с 409.

## Pagination and filters

Порядок строк стабилен: `segment`, `geo`, `channel`. Pagination применяется
после channel/geo filters. Ответ отдельно содержит:

- global scenario `totals`;
- `filtered_totals` для текущих filters;
- `total_rows` и `total_pages` после filters;
- одну page строк.

`totals.requested_budget_rub` раскладывается на
`selected_budget_rub + unallocated_budget_rub`. Это особенно важно для
partial-safe S5/S6: безопасно нераспределенный остаток не исчезает и не
маскируется под нулевой эффект.

Пустой результат корректного exact filter - это 200 с `rows=[]` и нулевыми
`filtered_totals`; global totals не меняются.

## Backend aggregates

В каждом ответе публикуются source-of-truth aggregates по полному scenario:

- `by_channel`;
- `by_geo`;
- `by_geo_channel`;
- heatmap-ready `geo_channel_matrix`.

Все три суммы должны сходиться с global source и selected totals в пределах
1 RUB. Frontend использует готовые aggregates и не создает новый decision
metric путем самостоятельного суммирования.

## Unavailable structures

- `by_date`: unavailable;
- `channel_date_matrix`: unavailable;
- map and coordinates: unavailable;
- working media-plan XLSX: unavailable.

Исходное daily flighting не превращается в scenario-specific daily plan через
неутвержденное пропорциональное масштабирование. Координаты не запрашиваются у
внешнего geocoder и не угадываются по названиям.

## Partial model coverage

Plan totals относятся к рассчитанной model-supported части сценария и сходятся
с `scenario.budget.allocated_budget_rub`. Полный uploaded budget и
`model_coverage_share` остаются в `job_result_view_v1.campaign`. Непокрытый
бюджет не показывается как zero-effect allocation.

## Ranks and quality

`safe_rank` и `raw_rank` читаются из allocation artifact. Row quality строится
только из опубликованных `allowed_use`, `optimizer_policy` и non-OK gate
evidence:

- `safe`: разрешена автоматическая аллокация;
- `caution`: допустима только осторожная интерпретация или budget fixed;
- `blocked`: есть реальный gate/policy запрет;
- `unavailable`: source values не дают однозначного status.

`allowed_use=caution` / `optimizer_policy=no_increase` и
`allowed_use=diagnostic` / `fixed_at_plan` остаются `caution`, даже если имеют
объясняющие non-OK reason codes. Наличие такого reason само по себе не
превращает разрешенную фиксированную связку в blocked. Raw codes не выводятся
пользователю.

## HTTP errors

| HTTP | Code | Значение |
|---:|---|---|
| 404 | `JOB_NOT_FOUND` | Job не существует. |
| 404 | `RESOURCE_NOT_READY` | Result еще не опубликован. |
| 409 | `RESULT_VIEW_INCONSISTENT` | Artifact или budget evidence не согласованы. |
| 422 | `MEDIA_PLAN_QUERY_UNSUPPORTED` | Scenario/filter/pagination недоступны. |
| 503 | `MEDIA_PLAN_VIEW_UNAVAILABLE` | Projection временно недоступна. |
