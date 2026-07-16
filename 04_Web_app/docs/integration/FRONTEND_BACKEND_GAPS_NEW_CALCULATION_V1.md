# Frontend ↔ Backend gaps: новый расчет V1

**Экран:** `/calculations/new`

**Frontend milestone:** Phase A — New Calculation V2

**Backend Phase A baseline:** `origin/main@f9aade027d5bac0c2213b6cdc6e58fdf2111f74f`

**Статус:** frontend integration note; не является предложением изменить schema

## 1. Граница документа

Страница использует только текущие browser-safe contracts через HTTP-операции
upload, validation, job creation, скачивание шаблона и чтение calculation
profile. Этот документ фиксирует поля, которые frontend отображает напрямую,
и единственный оставшийся data gap для утвержденного UX.

Frontend не читает XLSX/CSV после передачи файла серверу, не рассчитывает
budget aggregates или Scenario 6 profile, не придумывает координаты и не
переносит MMM- или optimizer-логику в браузер. Отсутствующие optional projections
показываются как контролируемое состояние «Нет данных» и не заменяются нулями.

## 2. Что уже подключается к live contract

### Загрузка и разбор файла

| UI-состояние или поле | Contract field / operation |
|---|---|
| загрузка одного файла | `POST /api/v1/uploads` |
| восстановление результата разбора по URL | `GET /api/v1/uploads/{upload_id}` |
| имя и размер исходного файла | `original_file.display_name`, `original_file.size_bytes` |
| статус разбора | `status.code`, `status.display_text` |
| количество исходных строк | `source_rows_n` |
| найденное количество кампаний | `detected_campaigns_n` |
| маркировка синтетического ответа в review/test | `record_origin = synthetic_fixture` |

Frontend принимает только `.xlsx` и `.csv`, один файл за раз. Backend Phase A
также проверяет формат на upload boundary и требует ровно одну кампанию. Если
`detected_campaigns_n !== 1`, frontend не запускает validation и предлагает
загрузить другой файл. Повтор отправки одного выбранного `File` использует тот
же idempotency key до выбора или удаления другого файла.

Кнопка `Скачать шаблон медиаплана` ведет на
`GET /api/v1/templates/campaign-plan.xlsx`. Файл и его имя возвращает backend;
frontend не хранит копию шаблона и не строит workbook в браузере.

### Проверка кампании

| UI-состояние или поле | Contract field / operation |
|---|---|
| запуск и восстановление проверки | `POST /api/v1/uploads/{upload_id}/validations`, `GET /api/v1/validations/{validation_id}` |
| running / valid / invalid | `status.code`, `status.display_text` |
| разрешение создать job | `job_creation_allowed` |
| одна кампания после validation | `campaigns.length === 1` |
| название, сегменты, даты | `campaigns[].campaign_name`, `segments`, `start_date`, `end_date` |
| каналы и географии | `campaigns[].channels`, `geographies` |
| активные дни и число строк | `campaigns[].active_days`, `source_rows_n` |
| общий бюджет кампании | `campaigns[].uploaded_budget_rub` |
| общие budget reconciliation values | `totals.*_budget_rub`, `totals.*_abs_diff_rub` |
| blocking issues и warnings | `blocking_errors[]`, `warnings[]` |
| видимое описание issue | `ValidationIssue.what` или совместимый fallback `display_text` |
| причина и действие | optional atomic set `why`, `recommended_action` |
| severity и affected cells | `severity`, `scope`, `affected_cells[]` |
| бюджет по каналам | `preview.budget_by_channel[]` |
| бюджет по географиям | `preview.budget_by_geo[]` |
| активность каналов по датам | `preview.channel_flighting[]` |
| результаты проверок | `preview.checks[]` |
| точки для будущей карты | optional `preview.geo_points[]`; текущий frontend намеренно не визуализирует координаты без фиксированной проекции |

Три верхнеуровневых состояния формируются только из contract facts:

- `Кампания готова к расчету`: validation завершена, создание job разрешено,
  warnings и blocking errors отсутствуют;
- `Кампанию можно рассчитать, но есть замечания`: создание job разрешено и
  `warnings.length > 0`;
- `Кампанию нужно исправить`: validation invalid, создание job запрещено,
  присутствуют blocking errors либо `campaigns.length !== 1`.

Повтор запуска validation для того же `upload_id` использует стабильный
upload-scoped idempotency key.

Графики бюджета и временная диаграмма строятся только из строк backend preview.
Frontend масштабирует длину полос и интенсивность ячеек для визуального
сравнения, но не агрегирует campaign rows и не выводит отсутствующую точку как
нулевой бюджет. Дневной `status` не агрегируется в статус всего канала: точные
row-level значения и формулировки доступны в раскрываемой таблице под
диаграммой. Блок проверок полностью формируется из `preview.checks`:
`display_text` показывается пользователю, а `code` остается техническим ключом.

Если старый совместимый ответ не содержит `preview` или отдельный optional
массив, соответствующий блок показывает «Нет данных». Если issue не содержит
полного guidance-набора, frontend показывает безопасный `display_text` и не
добавляет временные объяснения или рекомендации от себя.

### Сценарии и запуск

Экран S1–S6 содержит только утвержденные продуктовые описания и не показывает
forecast values. При входе на экран frontend запрашивает
`GET /api/v1/calculation-profile` и показывает для S6 фактическое
`scenario6_attempt_budget`, а также browser-safe `profile_label` и
`model_version_label`. Ответ проходит fail-closed runtime validation; при 503,
ошибке или неподдерживаемой форме контракта число вариантов не угадывается и
показывается контролируемое состояние недоступности.

Создание job выполняется только с этого экрана через
`POST /api/v1/validations/{validation_id}/jobs`, после чего используется
возвращенный `job_id` для перехода на существующий progress route. Для одного
`validation_id` frontend повторно использует тот же idempotency key: потерянный
HTTP-ответ не должен приводить к созданию второго дорогостоящего job.

## 3. Backend Phase A: закрытые gaps

| Возможность | Текущий contract source | Frontend behavior |
|---|---|---|
| XLSX-шаблон | `GET /api/v1/templates/campaign-plan.xlsx` | рабочая ссылка на backend artifact; локальной копии и fake URL нет |
| Бюджет по каналам | `ValidationResult.preview.budget_by_channel[]` | горизонтальная диаграмма с backend totals и max daily values |
| Бюджет по географиям | `ValidationResult.preview.budget_by_geo[]` | горизонтальная диаграмма с backend totals и max daily values |
| Активность каналов | `ValidationResult.preview.channel_flighting[]` | временная матрица `channel × date` из backend rows |
| Результаты проверок | `ValidationResult.preview.checks[]` | список строится только из `display_text` и `status` ответа; ручного перечня нет |
| Actionable issues | optional `what`, `why`, `recommended_action` | guidance отображается дословно; при legacy issue отсутствующие секции скрываются |
| Scenario 6 profile | `GET /api/v1/calculation-profile` | число вариантов и labels читаются из проверенного ответа, без hardcode |

Сгенерированные frontend-типы для additive lifecycle fields и
`CalculationProfile` берутся из актуальных JSON Schemas. Отдельный runtime
parser calculation profile дополнительно отклоняет лишние поля, неверные
contract identifiers, пустые labels и нецелое или неположительное число
вариантов.

## 4. Оставшийся data gap

| Gap | Что предусмотрено schema | Что публикует текущий backend | Поведение frontend |
|---|---|---|---|
| Координаты географий | optional `ValidationResult.preview.geo_points[]` с `latitude`, `longitude` и budget | массив в текущем application runtime отсутствует; фиксированная проекция и контур России не утверждены | карта показывает «данные пока недоступны» даже при наличии `geo_points`; frontend не растягивает точки по min/max кампании, не геокодирует названия и не хардкодит координаты |

Это не мешает показать backend aggregate по географиям. Карта и budget-by-geo
являются разными projections: наличие второго не считается доказательством
координат для первого. Сам массив координат также недостаточен для честной
карты без зафиксированной проекции, географических границ и контура России.

## 5. Refresh-safe navigation

Frontend сохраняет серверные идентификаторы и текущий шаг в URL:

- `/calculations/new`;
- `/calculations/new?uploadId=...&step=upload-result`;
- `/calculations/new?validationId=...&step=review`;
- `/calculations/new?validationId=...&step=scenarios`.

Результат upload восстанавливается через `uploadId`; review и scenarios — через
`validationId`. Сам объект `File` не сохраняется в browser storage и после
refresh до загрузки должен быть выбран заново. Record отображается и может быть
использован в action только если его ID совпадает с ID текущего URL; polling
отменяется при переходе на другой шаг или ресурс.

## 6. Не входит в frontend Phase A

- изменение Python backend, JSON Schemas, OpenAPI или MMM/model packages;
- агрегация budget/channel/geo/flighting rows в браузере;
- создание или изменение Scenario 6 configuration во frontend;
- external geocoding или локальный geo catalog;
- любая MMM-, forecast-, optimizer- или report-математика.

## 7. Live contract evidence

Проверено 2026-07-16 без route interception на локальном
`application_runtime` из этого worktree:

- `GET /health` → `ok`, `GET /ready` → `ready`;
- XLSX template → HTTP 200, media type
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, filename
  `campaign-plan-template.xlsx`, ZIP/XLSX integrity check passed;
- временный синтетический CSV существовал только вне repo и создал
  `upload_6e9e4bcda3b51b6cb7b1` с `detected_campaigns_n = 1`;
- validation `validation_9c58b89b5724a4512af7` завершилась как `valid` с
  `record_origin = application_runtime` и непустыми
  `budget_by_channel`, `budget_by_geo`, `channel_flighting`, `checks`;
- warning содержал непустые `what`, `why`, `recommended_action`;
- `geo_points` отсутствовал, и frontend показал controlled unavailable state;
- `GET /api/v1/calculation-profile` вернул `scenario6_attempt_budget = 2048`,
  frontend показал `2 048 вариантов` без локальной константы;
- real-browser smoke на `1440 × 900` и `375 × 812` подтвердил отсутствие
  document overflow, raw contract names и fixture badge.

Live-smoke не создавал calculation job и не запускал MMM: для Phase A он
проверяет границу template → upload → validation → preview → calculation
profile. Полный worker/result flow остается покрыт отдельным acceptance
контуром проекта.
