# Frontend Phase E.1B: turnover-only business semantics

## Статус

Phase E.1B реализована в отдельной frontend-ветке. Typed migration, unit,
fixture regression, Chromium automation, live backend acceptance и
light/dark/mobile visual review выполнены. Safari manual smoke остается
единственным pending gate, пока macOS заблокирована; до его завершения PR
остается Draft.

Baseline:
`origin/main@f5944c5b25296a2cd58e27b4c8469c572fe93e20`
(merged PR #23).

Branch:
`codex/frontend-phase-e1b-business-semantics-v1`.

Backend, optimizer, JSON Schemas, OpenAPI, auth/admin и deployment в этой фазе
не меняются.

## API boundary

Frontend добавляет один общий typed client с fail-closed runtime validation и
переводит product views на следующие projections:

| Product view | Endpoint | Контракт |
|---|---|---|
| Результат и сценарии | `GET /api/v1/jobs/{job_id}/result-view-v2` | `job_result_view_v2@2.0.0` |
| Медиаплан сценария | `GET /api/v1/jobs/{job_id}/media-plan-v2` | `scenario_media_plan_v2@2.0.0` |
| Проверка загрузки | `GET /api/v1/validations/{validation_id}/view-v2` | `validation_result_v2@2.0.0` |
| Подробности модели | `GET /api/v1/models/active-v2` | `model_passport_v2@2.0.0` |
| Продуктовый обзор модели | `GET /api/v1/model/overview-v2` | `model_overview_v2@2.0.0` |
| Готовность географического справочника | `GET /api/v1/meta/geo-catalog` | `geo_catalog_v1@1.0.0` |
| Бюджет workspace по географиям | `GET /api/v1/workspace/geo-budget` | `workspace_geo_budget_v1@1.0.0` |

Каждый запрос выполняется с `credentials: "include"`. Session cookie остается
HttpOnly и не читается через JavaScript. Неизвестные version/shape/semantic
invariants дают controlled unsupported state:
`Данные результата имеют неподдерживаемый формат.`

Silent fallback на v1 result, validation, media-plan или model semantics
запрещен. Lifecycle endpoints загрузки и создания job остаются orchestration
boundary, но пользовательское содержание проверки берется только из
`validation_result_v2`.

## Runtime validation

До рендера клиент проверяет:

- точные `contract_name`, `schema_version` и ключи объектов;
- равенство route ID и ID ответа;
- порядок S01–S06 и ровно один публичный S5;
- разрешенные `scenario_variant`, decision/review/status combinations;
- `requested = allocated + unallocated` и опубликованную `allocation_share`;
- явный denominator обоих ROAS и согласованность primary denominator;
- равенство опубликованных ROAS P10/P50/P90 соответствующим quantiles
  дополнительного оборота, деленным на allocated/requested denominator,
  с fail-closed допуском `1e-8`;
- reconciliation risk budgets/shares с распределенным бюджетом;
- full/infeasible invariants S6 и reference/manual semantics S1;
- полный список географий и согласованное `geographies_n`;
- `channel_id` как machine identity и `channel_display_name` как label;
- связь media-plan с загруженным result по `result_id`, `campaign_id`,
  scenario status, `is_selected`, safe/raw ranks и requested/source/selected/
  unallocated budget totals;
- отсутствие локальных путей, усеченных geo-строк и diagnostic target copy.

Frontend не рассчитывает ROAS, quantiles, recommendation, allocation delta,
risk composition или optimizer policy. Он только форматирует опубликованные
значения.

## Result semantics

Основной результат теперь turnover-only. Product UI показывает:

- дополнительный оборот P10/P50/P90;
- ROAS с явным denominator;
- запрошенный, распределенный и нераспределенный бюджет;
- опубликованную долю распределения;
- uncertainty/reliability evidence;
- risk composition;
- уже рассчитанный медиаплан.

Из product UI исключаются дополнительные заказы, заказы на 100 000 рублей,
средний чек, механизм среднего чека и псевдодекомпозиция оборота. Legacy v1
поля не используются для заполнения отсутствующих v2 данных.

Decision и review status не объединяются в один зеленый badge. Рекомендация
относится только к распределению бюджета и не является решением запускать или
отменять кампанию.

### S1

S1 всегда показывается как `Исходный план` с badge `Точка отсчета`.
`keep_uploaded_plan + manual_review_required` означает сохранение исходного
плана для ручной проверки, а не автоматическую рекомендацию. S1 не получает
маркер `Рекомендован системой`.

### S5

Frontend показывает ровно один публичный S5. Пользовательское имя определяется
его variant; общей подписи `Осторожный сценарий` и внутренних имен S5.1/S5.2
в интерфейсе нет:

- `full_conservative` — `Полный осторожный план`; весь бюджет распределен,
  положительный recommendation state возможен только если он опубликован
  backend;
- `safe_partial` — `Безопасно распределяемая часть`; amber/manual-review
  state с точными requested, allocated и unallocated RUB.

Для `safe_partial` одновременно показываются:

- `ROAS распределенной части` из `roas.allocated_budget`;
- `Отдача относительно всего запрошенного бюджета` из
  `roas.requested_budget`.

Основной показатель сравнения partial S5 — опубликованный
requested-budget ROAS. Браузер не делит effect на budget самостоятельно.

### S6

Feasible S6 показывает только полный опубликованный план. Для
`status=infeasible` выводится controlled state
`Полный план максимального эффекта недоступен`, browser-safe ограничения и ни
одного fake KPI. Media-plan request для infeasible S6 не выполняется; пустая
таблица не маскируется под готовый план.

### Budget и risk

Budget block показывает четыре поля контракта: requested, allocated,
unallocated и allocation share. Контракт не публикует отдельную
`unallocated_share`; frontend намеренно не вычисляет `1 - allocation_share`.
До появления versioned поля доля нераспределенного бюджета остается contract
gap, а точный нераспределенный бюджет в рублях остается видимым.

Risk composition показывает три независимые опубликованные категории:
`Внутри надежного диапазона`, `Контролируемое расширение` и `Высокий риск` —
каждую с RUB и share. Покрытие модели не используется как доказательство
полного распределения.

## Media plan

Сценарий в media-plan tab управляет только просмотром готового результата и не
меняет recommendation. Query, exact channel/geo filters и pagination уходят в
`media-plan-v2`.

Product labels берутся из `channel_display_name`; raw `Digital_Performance` и
`OOH_Total` не выводятся. Machine filtering сохраняет `channel_id`. Все
structured geographies остаются в фильтрах и строках; frontend не восстанавливает
их из сокращенной подписи и не агрегирует paginated rows в новые decision
metrics.

## Validation redesign

Страница `/calculations/new` разделяет две разные сущности:

1. `Проверка файла` — структура, одна кампания, бюджет, даты, число строк и
   возможность создать job из `file_validation.checks`;
2. `Ограничения модели` — сгруппированные turnover limitations с channel
   display name, типом ограничения, числом и полным списком географий,
   severity/allowed use и признаком блокировки.

Проверки не хардкодятся. Для каждой limitation используются contract-поля
`what`, `why` и `recommended_action`. Географии раскрываются через keyboard-
accessible accordion, а не стену повторяющихся chips. Orders/average-basket
warnings в v2 projection не рендерятся.

## Model, Home и geo behavior

`/model` использует turnover-only `active-v2` и `overview-v2`:

- один serving target — дополнительный оборот;
- четыре активные serving-модели;
- 12 research fits в пакете;
- явное пояснение, что модели заказов и среднего чека сохранены только для
  исследований и не участвуют в рекомендациях.

Главная сохраняет `workspace_home_v1` для workspace summary и добавляет
`workspace_geo_budget_v1` как отдельную server-side budget projection. Браузер
не суммирует history/jobs для построения географических totals.

`geo_catalog_v1` и geo fields используются только для readiness state. Пока
canonical coordinates отсутствуют, result, validation и Home показывают:
`Карта будет доступна после подключения утвержденного справочника координат.`
Phase E.1B не рисует scatter plot, не геокодирует названия и не строит guessed
points.

## Report contract gap

`job_result_view_v2` не публикует report/artifact metadata или download path.
Поэтому вкладка `Отчет` остается controlled unavailable. Frontend не вызывает
v1 result-view ради старого artifact и не конструирует download URL. Возврат
скачивания требует additive v2 artifact projection или отдельного утвержденного
endpoint; это не разрешение менять backend в Phase E.1B.

## Control campaign live acceptance

No-interception acceptance на реальном backend пройдена:

| Проверка | Подтвержденное значение |
|---|---:|
| Строк | 45 |
| Географий | 15 |
| Каналов | 3 |
| Requested budget | 267 818 706 RUB |
| S5 variant | `safe_partial` |
| S5 allocated | 173 912 510.62947646 RUB |
| S5 unallocated | 93 906 195.37052354 RUB |
| S5 allocated-budget ROAS P50 | 1.9817393657528313 |
| S5 requested-budget ROAS P50 | 1.2868752659545044 |
| S5 high-risk budget/share | 0 RUB / 0% |
| S6 | `infeasible` |
| S5 media-plan | 45 строк / 15 географий / 3 канала |
| Model package | 1 target / 4 serving models / 12 research fits |

Live job: `job_a8d96e52fc792197be1f`. Live validation:
`validation_edcd6ec607d845ae34b2`. Console warnings/errors отсутствовали.
Synthetic fixtures не использовались для live acceptance. В unit/E2E/review
screenshots они по-прежнему допустимы только с badge
`Демонстрационные данные`.

## Verification status

| Gate | Статус |
|---|---|
| Generated contract drift | passed; generated files unchanged |
| TypeScript | passed |
| ESLint | passed |
| Unit tests | passed: 39 files, 412 tests |
| Production build | passed: 151 modules; non-blocking bundle-size warning |
| Fixture/full Playwright regression | passed: 149 tests; 2 opt-in live suites skipped |
| Chromium automated acceptance | passed |
| Live backend acceptance without interception | passed: 1 test |
| Safari manual smoke | pending: macOS locked |
| Light/dark/mobile visual review | passed: 24 PNG |
| Result contrast | light 5.981:1; dark 8.002:1 |
| Validation contrast | light 5.981:1; dark 8.002:1 |

Фактические browser evidence и screenshot inventory зафиксированы в
`04_Web_app/docs/ui-review/phase-e1b-business-semantics-v1/REVIEW_NOTES.md`.

## Known contract limitations

1. Отдельной `unallocated_share` нет; frontend не вычисляет complement.
2. V2 result не содержит artifact metadata/download path; Report unavailable.
3. Approved canonical coordinates отсутствуют; карта unavailable.
4. Daily media plan и channel/date matrix недоступны.
5. S6 infeasible не имеет KPI или медиаплана по определению.
6. Model package остается research/preprod; production claim не разрешен.
