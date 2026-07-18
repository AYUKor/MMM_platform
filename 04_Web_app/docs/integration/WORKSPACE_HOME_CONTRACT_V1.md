# Workspace Home Contract V1

## Назначение

`GET /api/v1/workspace/home` возвращает компактный снимок рабочего пространства
для Главной. Endpoint отвечает на пять вопросов: что сейчас считается, что
завершилось недавно, есть ли ошибки, какая модель активна и куда пользователь
может перейти дальше.

Это read-only projection. Он не запускает расчет, не меняет job status и не
пересчитывает метрики.

## Источники

- persisted `DecisionJob v1` records;
- campaign summaries из соответствующей `ValidationResult v1`;
- published `result.json` и `overview.json` для признаков результата и отчета;
- `job_progress_view_v1` для текущего этапа активного расчета;
- `model_overview_v1` для краткого описания активной модели.

Браузер не читает lifecycle storage, result artifacts или model registry
напрямую.

## Семантика счетчиков

- `running`: jobs в `running` и `cancel_requested`;
- `queued`: jobs в `queued`;
- `completed_30d`: `succeeded` с `finished_at_utc` за последние 30 дней;
- `failed_30d`: `failed` и `timed_out` за последние 30 дней.

Счетчики активных jobs обязаны сходиться с `active_calculations[]`.

## Active и recent

`active_calculations[]` содержит только `queued`, `running` и
`cancel_requested`. `current_stage` может быть `null`, если детальный progress
временно недоступен; общий lifecycle status при этом не выдумывается.

`recent_calculations[]` содержит не более пяти terminal jobs, отсортированных
по времени создания. `result_path` публикуется только если одновременно
существуют согласованные result и overview. `report_available` требует реальный
`marketer_report_xlsx` в опубликованном overview.

## Model summary

Model summary строится из `model_overview_v1`. При отсутствии подтвержденной
активной модели endpoint возвращает explicit `unavailable` с `null` в model
facts. Fake score или optimistic fallback запрещены.

## Quick actions

Контракт всегда публикует ровно четыре реальные команды:

1. `/calculations/new` — новый расчет;
2. `/calculations` — история;
3. `/model` — сведения о модели;
4. `/help` — справка.

## Warnings

Home warnings агрегируют только операционные факты: недавние ошибки/тайм-ауты,
отсутствующий отчет, недоступную модель или временно недоступный детальный этап.
Они не меняют recommendation и не интерпретируют MMM-эффект.

## Errors

- `409 PRODUCT_NAVIGATION_INCONSISTENT`: опубликованные состояния противоречат
  друг другу;
- `422 PRODUCT_NAVIGATION_QUERY_INVALID`: endpoint получил неподдерживаемые
  параметры;
- `503 PRODUCT_NAVIGATION_UNAVAILABLE`: обязательный источник временно нельзя
  прочитать.

Error response не содержит exception, workstation path, registry key или
внутренние названия компонентов.

## Historical map source

`workspace_home_v1` отвечает за операционный снимок jobs и не содержит
исторический медиабюджет обучающей панели. После frontend Phase E.1F карта на
Главной должна отдельно читать
`GET /api/v1/model/historical-geo-budget` (`historical_model_geo_budget_v1`).

`GET /api/v1/workspace/geo-budget` при этом не удаляется: он отражает только
кампании, обработанные приложением, и может использоваться для аналитики
истории расчетов. Эти два источника имеют разные бизнес-смыслы и не являются
fallback друг для друга.
