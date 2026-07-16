# New Calculation Preview Contract V1

## Назначение

Этот контракт обслуживает backend-часть маршрута `/calculations/new` до запуска
долгого forecast/optimizer job. Он отвечает на четыре вопроса:

1. принят ли файл;
2. действительно ли в нем ровно одна кампания;
3. как backend понял бюджет, даты, каналы и географии;
4. можно ли создавать job.

Preview не является прогнозом. В нем нет ROAS, incremental effect, posterior
scoring, optimizer candidates или рекомендации сценария.

## Поддерживаемые файлы

- разрешены `.csv` и `.xlsx`;
- `.xls` и `.tsv` отклоняются на upload boundary;
- multipart-запрос должен содержать ровно одно поле `file`;
- один файл должен описывать ровно одну кампанию;
- `campaign_name` обязателен: пустое имя не превращается в служебную кампанию;
- XLSX с encrypted content, чрезмерным числом ZIP entries или опасным
  распакованным размером отклоняется до передачи workbook parser.

Upload parsing сохраняет `detected_campaigns_n`. Если значение равно `0` или
больше `1`, validation завершается со статусом `invalid`, кодом
`CAMPAIGN_COUNT_NOT_ONE` и `job_creation_allowed=false`. Backend не делит такой
файл на несколько расчетов. Пользователь должен загрузить каждую кампанию
отдельно.

## Последовательность API

1. `POST /api/v1/uploads` принимает один CSV/XLSX.
2. `GET /api/v1/uploads/{upload_id}` возвращает результат parsing.
3. `POST /api/v1/uploads/{upload_id}/validations` запускает validation.
4. `GET /api/v1/validations/{validation_id}` возвращает validation и optional
   `preview`.
5. `POST /api/v1/validations/{validation_id}/jobs` разрешен только для valid
   validation ровно одной кампании.

Низкоуровневый `POST /api/v1/jobs` применяет тот же guardrail: job должен
ссылаться на существующую valid validation с одной кампанией, тем же
`upload_id` и теми же hash-verified normalized/daily artifacts. Поэтому
технический endpoint нельзя использовать для обхода product validation.

Дополнительные read-only endpoints:

- `GET /api/v1/templates/campaign-plan.xlsx`;
- `GET /api/v1/calculation-profile`.

## ValidationResult.preview

Поле `preview` опционально, поэтому сохранена совместимость с V1-ответами и
fixtures без preview. Когда поле присутствует, его массивы также являются
опциональными.

### budget_by_channel

Одна строка на канал:

- `channel`;
- `total_budget_rub` - сумма normalized campaign budget;
- `max_daily_budget_rub` - максимум суммы по этому каналу за один день;
- optional `status` с machine code и русским `display_text`.

### budget_by_geo

Одна строка на географию:

- `geo`;
- `total_budget_rub`;
- `max_daily_budget_rub`;
- optional `status`.

### channel_flighting

Одна строка на `channel x date`:

- `channel`;
- `date`;
- `daily_budget_rub`;
- optional `status`.

Суммы `budget_by_channel` и `budget_by_geo` обязаны совпадать с
`totals.model_input_budget_rub`. Сумма `channel_flighting` обязана совпадать с
`totals.daily_budget_rub` в пределах lifecycle tolerance.

### checks

Каждая строка содержит:

- `code` - стабильный machine code;
- `status` - `passed`, `warning`, `failed` или `unavailable`;
- `display_text` - объяснение для пользователя.

Backend публикует только доказуемые факты: структуру файла, число кампаний,
reconciliation бюджета, корректность дат и результаты существующего
model-aware validation. `HISTORICAL_SPEND_SIMILARITY` помечается
`unavailable`, потому что этот guardrail проверяется позже при сценарном
расчете. Preview не подменяет support checks optimizer.

### geo_points

`geo_points` предусмотрен схемой как optional extension, но в текущем ответе
не публикуется. В web/backend-контуре нет утвержденного geo-coordinate
reference. Координаты не геокодируются внешним сервисом и не угадываются по
названиям.

## Synthetic response example

```json
{
  "status": {"code": "valid", "display_text": "План можно рассчитать"},
  "job_creation_allowed": true,
  "preview": {
    "budget_by_channel": [
      {
        "channel": "SYNTHETIC_CHANNEL_A",
        "total_budget_rub": 7000,
        "max_daily_budget_rub": 1000,
        "status": {"code": "passed", "display_text": "Проверено"}
      }
    ],
    "budget_by_geo": [
      {
        "geo": "SYNTHETIC_GEO_A",
        "total_budget_rub": 7000,
        "max_daily_budget_rub": 1000,
        "status": {"code": "passed", "display_text": "Проверено"}
      }
    ],
    "channel_flighting": [
      {
        "channel": "SYNTHETIC_CHANNEL_A",
        "date": "2026-02-01",
        "daily_budget_rub": 1000,
        "status": {"code": "passed", "display_text": "Проверено"}
      }
    ],
    "checks": [
      {
        "code": "CAMPAIGN_COUNT",
        "status": "passed",
        "display_text": "В файле найдена ровно одна кампания."
      }
    ]
  }
}
```

Пример сокращен: обязательные lifecycle-поля здесь не повторены.

## Campaign template

`GET /api/v1/templates/campaign-plan.xlsx` возвращает
`campaign-plan-template.xlsx` с листами:

- `00_Инструкция`;
- `01_Daily`;
- `02_Interval`.

В `01_Daily` используются колонки:

`campaign_name, date, segment, geo, channel, budget_rub`.

В `02_Interval` используются колонки:

`campaign_name, start_date, end_date, segment, geo, channel, budget_rub`.

Все примеры имеют префикс `SYNTHETIC_`. При загрузке backend игнорирует эти
примерные строки и выбирает единственный лист, в котором появились
пользовательские строки. Одновременное заполнение `01_Daily` и `02_Interval`
отклоняется как неоднозначный input.

## Calculation profile

`GET /api/v1/calculation-profile` возвращает:

- `scenario6_attempt_budget` из активной backend sampling configuration;
- `profile_label`;
- `model_version_label` из browser-safe model passport.

Endpoint не раскрывает seeds, posterior filenames, package paths или локальные
пути. Frontend должен использовать это значение для объяснения Scenario 6 и
не должен hardcode число попыток.

## Backward compatibility

- lifecycle schema остается `1.0.0`;
- `ValidationResult.preview` не входит в required fields;
- старые validation fixtures без preview проходят parser/schema validation и
  round-trip без добавления `preview: null`;
- существующие upload, validation и job URLs не изменены;
- OpenAPI document version поднята до `1.2.0` как additive API extension.

## Неизмененные границы

Эта версия не меняет campaign preparation mathematics, forecast engine,
posterior draws, optimizer scoring, recommendation policy или Excel result
report. Preview строится только из normalized campaign plan, daily flighting и
существующих validation statuses.
