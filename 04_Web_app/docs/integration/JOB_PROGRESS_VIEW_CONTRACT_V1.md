# Job Progress View Contract V1

## Назначение

`job_progress_view_v1` - browser-safe снимок состояния одного расчета для
маршрута `/calculations/{job_id}/progress`. Он собирается из уже сохраненных
`DecisionJobV1`, `ValidationResultV1`, `ProgressEventV1`,
`ApplicationErrorV1` и, после завершения, `DecisionResultV1`.

Контракт не запускает расчет и не меняет его математику. Его задача - перевести
технический журнал выполнения в понятную пользователю картину:

- где находится задача в очереди;
- какой продуктовый этап выполняется;
- какие этапы закончены;
- сколько реальных вариантов проверено в Scenario 6;
- сформирован ли отчет;
- произошла ли ошибка и что можно сделать;
- опубликован ли проверенный результат.

Frontend должен получать этот снимок одним запросом и не собирать этапы из raw
`ProgressEventV1` самостоятельно.

## Endpoints

Основной endpoint:

```text
GET /api/v1/jobs/{job_id}/progress-view
```

Возможные ответы:

- `200` - согласованный `job_progress_view_v1`;
- `404 JOB_NOT_FOUND` - расчет не найден;
- `409 PROGRESS_STATE_INCONSISTENT` - сохраненные ресурсы противоречат друг
  другу, поэтому backend отказался показывать догадку;
- `503 PROGRESS_VIEW_UNAVAILABLE` - снимок временно невозможно получить.

Существующий endpoint
`GET /api/v1/jobs/{job_id}/progress` остается без изменений и возвращает raw
`ProgressEventV1[]` для совместимости и аудита. Новый экран не должен
показывать его `stage`, `phase`, проценты или тексты напрямую.

Опциональный справочный endpoint:

```text
GET /api/v1/meta/mmm-facts
```

Он возвращает 20 заранее проверенных коротких фактов. Каталог статический, не
зависит от job и не вызывает LLM во время расчета.

## Верхний уровень

Снимок содержит:

- стабильные `contract_name=job_progress_view_v1` и
  `schema_version=1.0.0`;
- opaque `job_id` без локального пути;
- `job_status` с machine code и русским `display_text`;
- `queue`;
- краткое описание ровно одной кампании из связанного ValidationResult;
- `current_stage_id`;
- фиксированный массив `stages` из девяти элементов;
- отдельный объект `scenario6`;
- отдельный объект `report`;
- browser-safe `errors`;
- `can_cancel`, `result_available` и `updated_at_utc`.

Контракт не содержит прогнозных метрик, временного победителя Scenario 6,
рекомендации, ETA, локальных путей, seed, имен posterior-файлов или stack trace.

## Девять этапов

Этапы присутствуют всегда и только в этом порядке:

| ID | Заголовок | Смысл |
|---|---|---|
| P01 | Расчет ожидает запуска | Job создан и находится в очереди. |
| P02 | Подготавливаем медиаплан | Проверяются входы, конфигурация и модель. |
| P03 | Рассчитываем исходный медиаплан | Scenario 1. |
| P04 | Рассчитываем контрольные сценарии | Scenarios 2-4. |
| P05 | Ищем устойчивый вариант | Scenario 5. |
| P06 | Перебираем варианты распределения | Scenario 6 и реальные счетчики поиска. |
| P07 | Проверяем результаты | Финальный scoring, ограничения и выбор рекомендации. |
| P08 | Формируем отчет | Проверка и публикация Excel и result resources. |
| P09 | Расчет завершен | Проверенный результат опубликован. |

Допустимые статусы этапа:

- `pending` - еще не начат;
- `active` - текущий этап;
- `completed` - завершен;
- `warning` - завершен с неблокирующим ограничением;
- `failed` - на этапе произошла terminal error;
- `skipped` - этап неприменим или не выполнялся после terminal outcome.

Terminal job (`succeeded`, `failed`, `cancelled`, `timed_out`) не может иметь
активный этап. `succeeded` возможен только при завершенном P09, готовом отчете и
опубликованном result resource.

## Mapping событий

Централизованный mapping находится в
`services/job_progress_view.py`. HTTP handler и frontend его не дублируют.

| Internal stage | Product checkpoint |
|---|---|
| queued job без progress events | P01 |
| `prepare` | P02 |
| `benchmarks`, первый `forecast` | P03-P05 grouped calculation window |
| `scenario6` | P06 |
| `final_scoring` | P07 |
| `report` | P08, затем publication boundary P09 |

Текущий optimizer оценивает несколько сценариев пакетно одним posterior call,
а не отдельными последовательно наблюдаемыми процессами S1, S2, S3, S4, S5 и
S6. Поэтому P03-P05 являются продуктовыми контрольными точками внутри общего
calculation window. Backend не выдумывает промежуточные метрики или время
окончания каждого сценария. Текущий worker-тест отдельно гарантирует, что
новое событие P08 начинается после `final_scoring`.

Старые сохраненные progress streams могли не иметь отдельного
`final_scoring` checkpoint. Projection продолжает читать их, если итоговый
result и отчет согласованы. Это часть backward compatibility.

## Queue

`queue.position` - однобазовая позиция среди job со статусом `queued`.
`queued_jobs_total` - число таких job в текущем file-backed runtime.

Если polling совпал с переходом job из очереди в выполнение, позиция может
временно быть `null`. Это честное неизвестное состояние, а не ошибка. Повторный
GET восстановит актуальный снимок и не меняет сохраненные данные.

## Campaign summary

`campaign` строится только из связанного ValidationResult:

- `campaign_id` и `campaign_name`;
- список сегментов;
- дата начала и окончания;
- загруженный бюджет;
- число каналов и географий.

Valid Phase A validation уже требует ровно одну кампанию. Projection повторно
проверяет это ограничение и fail-closed отклоняет противоречивое состояние.
Frontend не читает normalized CSV для заголовка progress page.

## Scenario 6 counters

`scenario6` содержит:

- `status`;
- `attempt_budget` из immutable `DecisionJob.sampling`;
- `attempts_checked` из structured worker event или финального result;
- `safe_candidates`;
- `blocked_candidates`;
- `finalists_scored`;
- `finalists_total`.

`attempts_checked` не может превышать `attempt_budget`. Значение из event не
принимается, если его total расходится с immutable job configuration.

Текущий worker надежно публикует attempt budget, checked attempts и число
пересчитанных finalists. Он не публикует агрегаты safe/blocked candidates,
поэтому эти два поля сейчас равны `null`. Frontend обязан показать неизвестное
значение как unavailable, а не как ноль.

В progress contract нет `best_raw`, `best_safe`, ROAS, incremental turnover или
временной рекомендации. Они публикуются только после завершения через result
contracts.

## Report publication boundary

`report.status` отделен от расчета сценариев:

- `pending` - финальная проверка еще не закончена;
- `running` - result adapter проверяет и публикует отчет;
- `completed` - marketer Excel присутствует в result artifacts;
- `failed` - сформировать обязательный отчет не удалось;
- `not_required` - расчет завершился раньше report stage.

Текущий canonical workflow считает отчет обязательным. Worker сначала пишет
result и artifact references, затем terminal job status. Projection отклоняет
`succeeded`, если result или marketer report отсутствует. Отдельного
report-only retry endpoint пока нет; повторно запускать forecast/optimizer ради
одного отчета backend автоматически не будет.

## Errors

Каждая ошибка progress-view содержит:

- opaque `error_id`;
- продуктовый `stage_id`;
- `severity`, `blocking`, `retryable`;
- пользовательский `display_text`;
- `recommended_action`.

Raw stdout/stderr, component, internal phase, support reference, stack trace и
workstation paths не публикуются. Неизвестный internal stage безопасно
привязывается к текущему продуктовому этапу.

## Percent policy

Общего `percent_complete` и ETA в V1 нет. Причина: текущий расчет не дает
достаточно равномерной и доказуемой шкалы времени. Даже для P04 backend не
публикует искусственное `3/3`, пока worker не отдает три реальных checkpoint.
P06 показывает реальные attempt counters. Если total неизвестен, он остается
`null`.

Frontend должен использовать indeterminate animation для этапа без реального
total. Он не должен увеличивать процент по таймеру.

## Recovery and polling

Projection не записывает состояние и детерминирован для одинакового набора
ресурсов. Повторный GET не создает events и не меняет job.

При наличии нескольких attempts используются progress events только текущего
`job.attempt_number`. Старые events остаются в аудите, но не сбивают текущую
последовательность. Event из будущей попытки, неправильный job ID,
немонотонные sequence/timestamps или несовпадающий attempt budget приводят к
fail-closed `409`.

## Synthetic example

```json
{
  "contract_name": "job_progress_view_v1",
  "schema_version": "1.0.0",
  "record_origin": "synthetic_fixture",
  "job_id": "job_777777777777",
  "job_status": {"code": "running", "display_text": "Расчет выполняется"},
  "queue": {
    "position": null,
    "queued_jobs_total": 0,
    "display_text": "Расчет уже запущен."
  },
  "campaign": {
    "campaign_id": "campaign_666666666666",
    "campaign_name": "Synthetic campaign",
    "segment": ["SYNTHETIC_SEGMENT"],
    "start_date": "2026-08-01",
    "end_date": "2026-08-31",
    "total_budget_rub": 50000000,
    "channels_n": 4,
    "geographies_n": 12
  },
  "current_stage_id": "P06",
  "stages": ["nine fixed stage objects"],
  "scenario6": {
    "status": "running",
    "attempt_budget": 2048,
    "attempts_checked": 620,
    "safe_candidates": null,
    "blocked_candidates": null,
    "finalists_scored": null,
    "finalists_total": null
  },
  "report": {
    "status": "pending",
    "display_text": "Отчет будет сформирован после проверки результатов.",
    "retryable": false
  },
  "errors": [],
  "can_cancel": true,
  "result_available": false,
  "updated_at_utc": "2026-07-16T09:00:00Z"
}
```

Массив `stages` сокращен только в документации. Реальный ответ всегда содержит
девять типизированных объектов.

## Backward compatibility

- `ProgressEventV1` и `/progress` не изменены;
- новый endpoint additive;
- OpenAPI поднят до `1.3.0`;
- JSON Schemas доступны через contract discovery;
- TypeScript types генерируются из schemas и проверяются на drift в CI;
- frontend Phase B в этой реализации не добавлен.

## Known gaps

- safe/blocked candidate counts пока `null`;
- пакетная оценка сценариев не дает отдельного live counter для S1-S5;
- нет общего процента и ETA;
- нет report-only retry endpoint;
- 20 MMM facts являются стартовым проверенным каталогом, а не будущим полным
  набором из 150 материалов;
- file-backed queue position относится только к одному local/research runtime,
  а не к будущей distributed queue.

## Неизмененные границы

Изменение не затрагивает MMM, forecast, posterior scoring, optimizer candidate
generation, Scenario 6 ranking, recommendation policy или содержимое Excel.
