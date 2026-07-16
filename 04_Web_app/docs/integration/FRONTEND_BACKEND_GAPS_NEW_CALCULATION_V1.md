# Frontend ↔ Backend gaps: новый расчет V1

**Экран:** `/calculations/new`

**Frontend milestone:** Phase A — New Calculation V2

**Baseline:** `origin/main@79f1f456ab3ec6abb2f745726622fa052dd5b4a5`

**Статус:** frontend integration note; не является предложением изменить schema

## 1. Граница документа

Страница использует только текущий Application Lifecycle v1 через существующие
HTTP-операции upload, validation и job creation. Этот документ фиксирует поля,
которые уже можно отображать напрямую, и данные, которых не хватает для
утвержденного UX.

Frontend не читает XLSX/CSV после передачи файла серверу, не рассчитывает
агрегаты, не придумывает координаты и не переносит MMM- или optimizer-логику в
браузер. До появления новых browser-safe полей отсутствующие блоки показывают
контролируемое состояние «Нет данных».

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

Frontend принимает только `.xlsx` и `.csv`, один файл за раз. Если
`detected_campaigns_n !== 1`, переход к validation блокируется, а пользователю
предлагается загрузить другой файл. Это frontend guardrail; текущий frontend
contract сам по себе не доказывает server-side запрет `.xls` / `.tsv` и
multi-campaign input. Повтор отправки одного выбранного `File` использует тот
же idempotency key до выбора или удаления другого файла.

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
| видимое описание issue | `ValidationIssue.display_text` |
| severity и affected cells | `severity`, `scope`, `affected_cells[]` |

Три верхнеуровневых состояния формируются только из contract facts:

- `Кампания готова к расчету`: validation завершена, создание job разрешено,
  warnings и blocking errors отсутствуют;
- `Кампанию можно рассчитать, но есть замечания`: создание job разрешено и
  `warnings.length > 0`;
- `Кампанию нужно исправить`: validation invalid, создание job запрещено,
  присутствуют blocking errors либо `campaigns.length !== 1`.

Повтор запуска validation для того же `upload_id` использует стабильный
upload-scoped idempotency key.

### Сценарии и запуск

Экран S1–S6 содержит только утвержденные продуктовые описания и не показывает
forecast values. Создание job выполняется только с этого экрана через
`POST /api/v1/validations/{validation_id}/jobs`, после чего используется
возвращенный `job_id` для перехода на существующий progress route. Для одного
`validation_id` frontend повторно использует тот же idempotency key: потерянный
HTTP-ответ не должен приводить к созданию второго дорогостоящего job.

## 3. Contract gaps

| Gap | Что нужно для UI | Что доступно сейчас | Поведение frontend до закрытия gap |
|---|---|---|---|
| Шаблон медиаплана | browser-safe artifact/action для скачивания XLSX-шаблона, включая имя и media type | template artifact/URL отсутствует | disabled action `Скачать шаблон медиаплана` и текст `Шаблон будет доступен после подключения файла-шаблона` |
| Бюджет по каналам | массив channel aggregate с названием канала и бюджетом кампании | только список названий каналов и общий бюджет | polished unavailable state; значения по каналам не рассчитываются в браузере |
| Бюджет по географиям | массив geo aggregate с названием гео и бюджетом кампании | только список географий и общий бюджет | polished unavailable state; значения по гео не рассчитываются в браузере |
| Daily flighting projection | browser-safe daily/channel series с датой и бюджетом; ArtifactIdentity недостаточно | `daily_flighting` содержит только identity артефакта, без данных для графика | календарь показывает unavailable state; frontend не читает локальный артефакт |
| Координаты географий | approved geo catalog или projection с latitude/longitude и стабильным geo ID | координат в lifecycle contract нет | карта показывает unavailable state; координаты не угадываются и не хардкодятся |
| Readable check outcomes | структурированный список проверок: stable check key, marketer-safe title, outcome, explanation и blocking flag | есть итоговый validation status и issues, но нет результатов каждой проверки | обязательный checklist не помечает проверку как успешно пройденную без прямого contract evidence; отсутствующие outcomes показаны как `Нет данных` |
| Warning explanation/action | отдельные marketer-safe `what`, `why`, `recommended_action` и issue-level blocking flag | `display_text`, `severity`, `recoverable`, `scope`, `affected_cells` | `display_text` используется только как `Что обнаружено`; `Почему это важно` и `Что можно сделать` показываются как недоступные, если безопасный текст не передан; raw code не выводится |
| Scenario 6 attempts до job creation | browser-safe scenario profile/preview с фактическим configured attempt count до запуска | `scenario6_attempt_budget` существует только в `DecisionJob.sampling`, то есть после создания job | число попыток на pre-job scenario screen не показывается; `150` не хардкодится |

## 4. Refresh-safe navigation

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

## 5. Не входит в frontend Phase A

- изменение JSON Schema, OpenAPI или generated TypeScript types;
- backend enforcement форматов и одной кампании;
- создание template endpoint/artifact;
- добавление preview aggregates, geo catalog или check/warning projections;
- изменение job profile или Scenario 6 configuration;
- любая MMM-, forecast-, optimizer- или report-математика.
