# Calculation History Contract V1

## Назначение

`GET /api/v1/calculations/history` возвращает server-side историю расчетов.
Одна строка соответствует одному immutable `job_id`. Frontend не собирает
историю из lifecycle-файлов и не определяет доступность результата по тексту
статуса.

## Query

Поддержаны:

- `page`, default `1`;
- `page_size`, default `25`, диапазон `1..100`;
- `status`: lifecycle code либо агрегат `active`;
- `search`: до 120 символов;
- `created_from` и `created_to`: inclusive ISO dates;
- `sort`: `created_desc`, `created_asc`, `completed_desc`, `campaign_asc`.

Неизвестные и повторяющиеся параметры отклоняются. Search применяется к
`job_id`, campaign name и известным segments. Фильтры и пагинация выполняются
до отправки ответа браузеру.

## Источники строки

- status и timestamps: persisted `DecisionJob v1`;
- campaign name, period, budget, segments, channel/geo counts:
  `ValidationResult v1.campaigns`;
- result availability: опубликованы и result, и overview для `succeeded` job;
- report availability: overview содержит `marketer_report_xlsx`;
- warnings count: published overview, а до результата — validation warnings.

Legacy multi-campaign job отображается одной строкой с объединением только
реально известных campaign facts. Если факт отсутствует, возвращается `null`,
а не ноль. Missing campaign metadata не восстанавливается из filename.

## Summary

`summary` считается по всей сохраненной истории до текущих фильтров:

- `all`;
- `active` = queued + running + cancel_requested;
- `succeeded`;
- `failed`;
- `cancelled`;
- `timed_out`.

Все категории взаимоисключающие и обязаны суммироваться в `all`.

## Stable ordering

Каждый sort имеет deterministic tie-breaker по `job_id`. Для
`completed_desc` незавершенные jobs идут после terminal. Пустая страница
возвращает `items=[]` и корректные totals.

## Path и publication rules

- `progress_path` всегда browser route;
- `result_path` равен `null`, пока product result не опубликован;
- report не может быть available без result;
- failed/active job не может публиковать result/report flags;
- local filesystem paths запрещены.

## Errors

- `409 PRODUCT_NAVIGATION_INCONSISTENT` для duplicated IDs, невозможных
  timestamps или противоречивого publication state;
- `422 PRODUCT_NAVIGATION_QUERY_INVALID` для pagination/filter/search/date/sort;
- `503 PRODUCT_NAVIGATION_UNAVAILABLE` для временной ошибки чтения projection.

Существующий технический `GET /api/v1/jobs?limit=&offset=&status=` сохранен для
совместимости. Новый endpoint является product projection для страницы
Истории.
