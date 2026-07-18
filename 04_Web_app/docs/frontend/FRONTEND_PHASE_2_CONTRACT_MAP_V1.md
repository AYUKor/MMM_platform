# Frontend Phase 2: contract map

Статус: обязательное contract-first ограничение для Phase 2 Product Pages.

Базовая версия репозитория: `52d8d03168b1f6d85606ab9740d6ca08e825e349`
(`52d8d03`).

Post-merge update, 2026-07-15: этот документ был написан до Product API v1.1.
В актуальном после PR #9 `main` (`15518cb`) backend публикует versioned
`GET /api/v1/models/active` с `ModelPassport v1`. Поэтому прежний gap
Standalone Model Passport закрыт на backend-стороне. Текущий frontend
milestone подключает route `/model` через typed client и fail-closed runtime
validation, не читая registry, `CURRENT_TRUTH.md` или локальные model files.

Post-merge E.1A update, 2026-07-17: backend publishes additive turnover-only
contracts. Frontend Phase E.1B migrates product presentation to these
projections from baseline
`f5944c5b25296a2cd58e27b4c8469c572fe93e20`. The existing v1 sections below
remain historical documentation only and must not be used to reconstruct
current result semantics.

Post-merge E.1D update, 2026-07-18: Backend Phase E.1C closed the canonical
point-coordinate and workspace-aggregation gaps. Frontend Phase E.1D consumes
only `validation_result_v2.geo_points` and `workspace_geo_budget_v1`, using one
fixed local projection and versioned outline asset. The browser still does not
geocode, match aliases, aggregate jobs, recompute shares or infer model
coverage. Asset and renderer decisions are recorded in ADR 0024.

Post-merge E.1F update, 2026-07-19: Backend Phase E.1E publishes the
package-bound `historical_model_geo_budget_v1`. Home now uses only
`GET /api/v1/model/historical-geo-budget`; it does not call or fall back to the
workspace geo-budget projection. The campaign map, fixed projection, local
outline, scaling and label layout remain unchanged.

New frontend work must prefer:

| Product view | Endpoint | Contract |
|---|---|---|
| Result and scenarios | `GET /api/v1/jobs/{job_id}/result-view-v2` | `job_result_view_v2` |
| Scenario media plan | `GET /api/v1/jobs/{job_id}/media-plan-v2` | `scenario_media_plan_v2` |
| Validation review | `GET /api/v1/validations/{validation_id}/view-v2` | `validation_result_v2` |
| Model Passport | `GET /api/v1/models/active-v2` | `model_passport_v2` |
| Model summary | `GET /api/v1/model/overview-v2` | `model_overview_v2` |
| Geo identity/coordinate availability | `GET /api/v1/meta/geo-catalog` | `geo_catalog_v1` |
| Workspace geo budget | `GET /api/v1/workspace/geo-budget` | `workspace_geo_budget_v1` |
| Historical model geo budget for Home | `GET /api/v1/model/historical-geo-budget` | `historical_model_geo_budget_v1` |

Phase E.1B frontend rules:

- primary result target is turnover only; do not render orders or average
  basket from legacy v1 fields;
- render both allocated-budget and requested-budget ROAS with the denominator
  label supplied by backend;
- render requested, allocated and unallocated budget explicitly;
- show within-support, controlled-extrapolation and high-risk budget shares as
  separate backend values; do not derive them from coverage;
- S1 is the uploaded reference and manual review, not a recommendation badge;
- S5 uses backend `scenario_variant`: `full_conservative` or `safe_partial`;
- S6 is either a complete full-budget plan or `infeasible`; do not invent a
  partial display plan;
- use `channel_display_name` for labels and `channel_id` for query/machine
  identity;
- keep all structured geographies; never parse `... еще N` presentation text;
- use backend `map_coverage` and canonical coordinates; for `partial`, keep
  every unlocated geography and its budget visible.

Phase E.1D map rules:

- Home points, totals, campaign counts and shares come only from
  `workspace_geo_budget_v1`; only canonical rows are plotted and the top ten
  labels are selected by published `total_budget_rub`;
- campaign points, channels and limitations come only from
  `validation_result_v2.geo_points`; every located geography is labeled and
  the complete non-map list remains visible;
- one fixed Albers Equal Area projection and local Natural Earth outline are
  shared by both modes; no response-relative fitting or runtime map provider;
- partial/unavailable coverage preserves every unlocated geography and the
  published budget/share instead of silently dropping it.

Phase E.1F Home source rules:

- Home points, total, period, active-day evidence, shares and coverage come
  only from `historical_model_geo_budget_v1`;
- top labels use published `historical_total_budget_rub`; frontend does not
  reconstruct historical spend from workspace calculations;
- Home does not show campaign count and does not use
  `workspace_geo_budget_v1` as fallback;
- missing package-bound evidence is a controlled unavailable state;
- `workspace_geo_budget_v1` remains a supported client contract for future
  product-history views, but no longer drives Home.

The v1 `/media-plan` endpoint remains compatible for the merged historical
frontend. Phase E.1B uses `/media-plan-v2`, which supplies versioned channel
and geography identities; frontend constants and loose CSV joins remain
prohibited. Malformed or unavailable v2 responses never fall back silently to
v1 result, validation, model or media-plan payloads.

Current E.1B contract gaps are explicit:

1. `job_result_view_v2` contains no report artifact metadata or download path,
   so Report remains controlled unavailable instead of reading a v1 artifact;
2. budget publishes `allocation_share`, but no `unallocated_share`; frontend
   shows exact unallocated RUB and does not compute the complement;
3. map rendering/base geometry is closed by Phase E.1D with a versioned local
   Natural Earth outline, fixed projection and no runtime map provider;
4. daily media-plan rows and channel/date matrix remain unavailable.

`workspace_geo_budget_v1` augments the existing workspace Home projection; it
does not replace `workspace_home_v1`. The browser consumes server totals and
does not aggregate jobs/history into a new geo decision metric.

Implementation and QA evidence are tracked in
`integration/FRONTEND_PHASE_E1B_BUSINESS_SEMANTICS_V1.md` and
`ui-review/phase-e1b-business-semantics-v1/REVIEW_NOTES.md`. Until those checks
are executed, their verification status remains `pending`.

The numbered sections below describe the historical v1 boundary.

## 1. Источники истины и граница frontend

Для экранов результата основным browser contract является
`result_overview_v1` из:

```text
GET /api/v1/jobs/{job_id}/overview
```

`decision_result_v1` из:

```text
GET /api/v1/jobs/{job_id}/result
```

остаётся полным audit contract. Он не должен использоваться как повод
повторно рассчитывать или переопределять browser-проекцию в React.

Frontend:

- форматирует уже рассчитанные backend значения для отображения;
- выбирает кампанию только по явному `campaign_id`, если в job больше одной
  кампании;
- использует известные status/warning/action codes только для browser-safe
  presentation map; raw codes и технический `display_text` не выводятся;
- для неизвестного кода закрывается в общее состояние ручной проверки, не
  повторяя backend text;
- не рассчитывает ROAS, p10/p50/p90, reliability, allocation delta,
  optimizer recommendation, paired comparison или recommendation;
- не объединяет optimizer CSV и другие loose artifacts в новый результат;
- не трактует allocation recommendation как решение запускать или отменять
  кампанию;
- не использует sanitized fixture как реальный результат. При
  `result_origin="sanitized_fixture"` обязателен badge
  `Демонстрационные данные`.

## 2. Экран → поля → endpoint → contract gap

| Экран / блок | Необходимые contract-поля | Существующий endpoint | Покрытие и contract gap |
|---|---|---|---|
| Result shell и выбор кампании | `overview_id`, `source_result_id`, `result_origin`, `created_at_utc`, `campaigns[].campaign_id`, `campaigns[].passport.campaign_name` | `GET /api/v1/jobs/{job_id}/overview` | Поддержано. При одной кампании она может открываться сразу; при нескольких нужен явный выбор. `campaigns=[]` является invalid payload, а не «пустым успешным результатом». |
| Паспорт кампании в результате | `passport.campaign_name`, `segments`, `source_start_date`, `source_end_date`, `model_start_date`, `model_end_date`, `source_active_days`, `model_active_days`, `source_channels`, `modeled_channels`, `unmodeled_channels`, `geographies`, `creatives`; `budget.*` | `GET /api/v1/jobs/{job_id}/overview` | Поддержано. Пустые допустимые списки показываются как `Нет данных`. Нельзя восстанавливать отсутствующие атрибуты из имени файла или artifact metadata. |
| Подробное сравнение сценариев 1–6 | `scenarios[].scenario_id`, `available`, `budget.*`, `metrics.incremental_turnover`, `metrics.turnover_roas`, `metrics.incremental_orders`, `metrics.incremental_orders_usage`, `metrics.avg_basket_turnover_bridge`, `calculation_status`, `cell_support_status`, `optimizer_status`, `support`, `quality`, `paired_comparison` | `GET /api/v1/jobs/{job_id}/overview` | Абсолютные p10/p50/p90, budget и quality/support поддержаны. Для `available=false` метрики не подменяются нулями; показываются причина и `Нет данных`. S5 получает presentation-label `Ориентир по устойчивости`. Orders явно маркируются `Диагностический показатель`; basket bridge нельзя называть изменением среднего чека. `paired_comparison` пока не выводится: contract не называет reference scenario, поэтому подпись сравнения нельзя утверждать. |
| Рекомендация и сравнение с загруженным планом | `recommendation.scenario_id`, `recommendation_type.code`, `plan_status.code`, `optimizer_available`, `metrics`, `versus_uploaded_plan.*`; campaign-level `statuses.business_decision_status.code` | `GET /api/v1/jobs/{job_id}/overview` | Поддержано. Используются готовые backend deltas и moved budget; пользовательские формулировки берутся из presentation map. Raw `reason` остается audit evidence и не печатается, если содержит техническую терминологию. Экран обязан отдельно сказать, что рекомендация относится к распределению бюджета и не является решением о запуске кампании. |
| Надёжность и warnings | `statuses.*.code`, `quality.status.code`, `quality.coverage_share`, `quality.uncertainty_width_share`, `scenarios[].support`, `scenarios[].quality`, `warnings[].code`, `severity`, `affected_cells`; root `warnings[]` | `GET /api/v1/jobs/{job_id}/overview` | Поддержано без синтетического reliability score. `coverage_share` — покрытие, а не reliability. Известные codes переводятся через browser-safe presentation map; unknown code дает общее fail-closed предупреждение без raw текста. `affected_cells` сейчас часто пуст и не содержит display-name, поэтому отдельный cell breakdown не заявляется. |
| Scenario 6 audit | `scenario6.audit.run_status.code`, `attempts_evaluated`, `candidates_scored`, `candidates_rejected`, `finalists`; `best_raw`, `best_safe`, `raw_differs_from_safe` | `GET /api/v1/jobs/{job_id}/overview` | Частично поддержано. Показаны четыре готовых счётчика, статус через presentation map, разрешённые metrics и eligibility без opaque ID. `candidate_id`, `method`, rejection codes, raw explanation и внутренние policy names скрываются. |
| Медиаплан «было → рекомендуется» по `geo × channel` | `allocation_comparison[].segment`, `geo`, `channel`, `uploaded_budget_rub`, `recommended_budget_rub`, `delta_budget_rub`, `uploaded_budget_share`, `recommended_budget_share`, `action`, `gate_reason_codes`; `recommendation.plan_status`, `budget.model_coverage_share` | `GET /api/v1/jobs/{job_id}/overview` | Поддержано на уровне contract-строк `segment × geo × channel`. Frontend не пересчитывает delta и shares. `action` переводится в `Увеличить` / `Уменьшить` / `Без изменения`. Отдельные агрегированные totals/charts только по channel или только по geo потребуют новой backend projection; frontend не суммирует строки для получения нового decision metric. Для `gate_reason_codes` нет display text на уровне строки: допустим общий признак `Нужна ручная проверка`, но raw codes скрываются. |
| Partial coverage | `budget.model_coverage_share`, `unmodeled_budget_rub`, `unallocated_budget_rub`, `passport.unmodeled_channels`, `recommendation.plan_status.code`, warnings | `GET /api/v1/jobs/{job_id}/overview` | Поддержано. При покрытии меньше 100% экран явно отделяет рассчитанную часть от непокрытой; непокрытый бюджет не считается нулевым эффектом. |
| Отчёт | `artifacts[].artifact_id`, `kind`, `display_name`, `media_type`, `size_bytes`, `download_path`; root `warnings[]` | `GET /api/v1/jobs/{job_id}/overview`; загрузка через contract `download_path` (`GET /api/v1/artifacts/{artifact_id}/download`) | Поддержаны список разрешённых artifacts и Excel download. Для marketer report выбирается `kind="marketer_report_xlsx"`; URL берётся из `download_path`, а не строится из `storage_key`. Browser preview содержимого Excel contract не предоставляет — не реализуется. Отсутствие Excel показывает `Отчёт недоступен`, а не неактивную кнопку без объяснения. |
| Loading / queued / running | `DecisionJob.status.code`, progress events | `GET /api/v1/jobs/{job_id}`; `GET /api/v1/jobs/{job_id}/progress` | Поддержано. Пока job не terminal, отсутствие overview означает `Результат ещё готовится`, а не invalid result. |
| Failed / timed out | `DecisionJob.status`; `ApplicationError.retryable` | `GET /api/v1/jobs/{job_id}`; `GET /api/v1/jobs/{job_id}/errors` | Поддержано. Страница выбирает простое сообщение по terminal status и `retryable`; raw `display_text`, code, exception, trace и внутренние пути не выводятся. |
| Empty / not found | Job existence и readiness | `GET /api/v1/jobs/{job_id}`; затем overview | Частично поддержано. `JOB_NOT_FOUND` — отдельный not-found state. `RESOURCE_NOT_READY` нужно интерпретировать только вместе со статусом job: queued/running → ожидание; succeeded без overview → server inconsistency/unavailable. Нельзя считать любой HTTP 404 «пустым результатом». |
| Invalid contract | `contract_name="result_overview_v1"`, `schema_version="1.0.0"`, обязательные collections и вложенные поля | `GET /api/v1/jobs/{job_id}/overview` | Поддерживается fail-closed client validation. Неизвестная версия, отсутствующая обязательная коллекция, duplicate/missing scenarios или нарушение shape дают controlled state `Результат имеет неподдерживаемый формат`; значения не достраиваются. |
| Model Passport: модель конкретного job | `job.*`, `model.registry_channel`, `registry_event_id`, `package_id`, `package_fingerprint`, `package_manifest_sha256`, `activation_status`, `production_blockers`; `policies.*` | `GET /api/v1/jobs/{job_id}/result` | Audit contract поддерживает job-scoped паспорт. Он может быть показан только в контексте выбранного `job_id` и не доказывает, что пакет сейчас активен. Идентификаторы и SHA допустимы в раскрываемом audit-блоке, но не как основной пользовательский текст. |
| Standalone Model Passport `/model` | `contract_name`, `schema_version`, `record_origin`; `serving.*`; безопасные поля `package.*`; `data.training_period`, `development_shadow_period`; `coverage.*`; `validation.historical_replay`, `sealed_oot`, `production_blockers`; `caveats` | `GET /api/v1/models/active` | **Поддержано.** Typed client принимает только `ModelPassport v1`, проверяет shape и semantic invariants, разделяет loading/ready/unavailable/error/unsupported-contract. Policy остаётся на уровне `segment × channel × target`; raw `package_stage`, `activation_status`, action/role/reason codes скрыты. `synthetic_fixture` всегда помечается `Демонстрационные данные`. Research/preprod и allocation-only границы показаны явно. |

## 3. Политика человекочитаемых названий

UI не выводит raw backend names как пользовательские подписи.

| Backend-представление | UI-представление |
|---|---|
| `status.code`, warning `code` | Использовать для branching и browser-safe presentation map; raw code и технический `display_text` не показывать. Unknown code → общее fail-closed сообщение. |
| `scenario_id` | Использовать для порядка и логики; пользовательский заголовок брать из согласованной presentation map. Для S5 использовать label `Ориентир по устойчивости`. |
| `incremental_turnover` | `Инкрементальный оборот`. |
| `turnover_roas` | `ROAS`. |
| `incremental_orders` | `Инкрементальные заказы · диагностический показатель`. |
| `avg_basket_turnover_bridge` | `Оборотный bridge на основе среднего чека`; не `delta среднего чека`. |
| `coverage_share` | `Покрытие моделью`; не `Надёжность`. |
| `uncertainty_width_share` | `Ширина интервала неопределённости`; не reliability score. |
| `elevated_warnings` | `Повышенная неопределённость`. |
| `strong_warnings` | `Сильные предупреждения`. |
| `hard_warnings` | `Блокирующие ограничения`. |
| `policy_violations` | `Нарушения правил автоматического распределения`. |
| `action=increase/decrease/keep` | `Увеличить` / `Уменьшить` / `Без изменения`. |
| `candidate_id`, `overview_id`, `source_result_id` | Скрывать в основных экранах; допустимы только в явно обозначенном audit/developer context. |
| `storage_key`, SHA-256, adapter/method/policy IDs | Не показывать в product UI. SHA и lineage допустимы только в раскрываемом audit-блоке Model Passport конкретного job. |
| `gate_reason_codes`, rejection codes | Не выводить raw. Известные row-level reasons переводятся через ограниченную presentation map; неизвестные → controlled `Нужна ручная проверка`. Rejection codes S6 скрываются. |

Значения `geo`, `channel` и `segment` берутся из backend contract без
переименования. Если production API возвращает технические коды вместо
утверждённых бизнес-названий, это отдельный contract gap: backend должен
добавить display-name или versioned dictionary. Frontend не содержит локальную
таблицу расшифровки.

## 4. Поддерживаемый scope Phase 2

Backend Phase C дополняет этот исторический Phase 2 map двумя source-of-truth
endpoints:

- `GET /api/v1/jobs/{job_id}/result-view` (`job_result_view_v1`);
- `GET /api/v1/jobs/{job_id}/media-plan` (`scenario_media_plan_v1`).

Для нового frontend result milestone приоритет имеют эти projections. Старый
`/overview` остается backward-compatible, но frontend больше не должен сам
выбирать default recommendation, извлекать ranks, строить reliability copy или
суммировать channel/geo totals. Детальная семантика зафиксирована в
`JOB_RESULT_VIEW_CONTRACT_V1.md` и `SCENARIO_MEDIA_PLAN_CONTRACT_V1.md`.

Текущий contract позволяет реализовать:

1. вкладку подробного сравнения S1–S6 с backend p10/p50/p90, ROAS,
   budget/status/quality/support; paired comparison отложен до явного reference;
2. вкладку надёжности без искусственного score: статусы, coverage,
   uncertainty, warnings и affected cells;
3. медиаплан на уровне `segment × geo × channel` с готовыми
   uploaded/recommended/delta/share/action;
4. вкладку отчёта с metadata и hash-checked Excel download по `download_path`;
5. loading, waiting, not-found, failed, timed-out, invalid-contract,
   unavailable и partial-coverage states;
6. standalone Model Passport из Product API v1.1 с периодом обучения,
   research-serving status, coverage, replay/OOT, blockers, target-specific
   channel policies, caveats и полным набором fail-closed states.

Все перечисленные экраны должны сохранять Phase 1 shell, tokens, themes,
типографику, responsive behavior и motion/reduced-motion правила.

## 5. Deferred scope и список contract gaps

До отдельного backend contract не реализуются:

1. **Агрегированные channel-only и geo-only decision totals/charts закрыты
   Backend Phase C.** `job_result_view_v1` и `scenario_media_plan_v1` возвращают
   reconciled `by_channel`, `by_geo` и `by_geo_channel`.
2. **Excel browser preview.** Contract предоставляет metadata и download, но не
   безопасное структурированное содержимое отчёта для browser rendering.
3. **Полная browser-copy projection каждого row-level gate/rejection code.** В
   allocation line присутствуют codes без display text. Для известных codes
   используется ограниченная presentation map; unknown code закрывается в
   `Нужна ручная проверка`. Полноценный backend dictionary остается gap.
4. **Независимый reliability score.** Такого показателя нет и вводить его не
   требуется. Надёжность показывается через contract statuses, support,
   coverage, uncertainty и warnings.
5. **Словарь технических geo/channel/segment codes.** Если backend отдаёт не
   утверждённые display names, нужен versioned dictionary/API projection.
6. **Daily scenario media plans и calendar/matrix by date.** Текущие artifacts
   содержат scenario totals по `geo × channel`, но не immutable S01-S06 daily
   rows. Backend Phase C возвращает controlled unavailable.
7. **Map base/polygon asset — закрыт в Phase E.1D.** Локальный versioned SVG
   создан из Natural Earth Admin 0 Countries 1:50m v5.1.1 (public domain),
   использует фиксированную Albers Equal Area projection и не делает runtime
   network requests. Runtime geocoder остается запрещен.
8. **Working media-plan XLSX.** Реального отдельного artifact kind нет. CSV не
   маскируется под XLSX; marketer report XLSX остается доступен.

Закрытый после первоначального Phase 2 анализа gap:

- **Approved point coordinates and alias policy.** Backend Phase E.1C добавил
  `geo_catalog_v1_2026_07_18`, 220/220 serving coverage, explicit partial
  states и server-side workspace aggregation.
- **Standalone Model Passport backend contract.** Product API v1.1 добавил
  `GET /api/v1/models/active`; текущий milestone также завершает frontend
  integration. Свободные package/action/role codes остаются скрытыми, пока
  backend contract не добавит для них enum и browser labels.

Эти gaps фиксируются документацией и UI unavailable states. Они не являются
разрешением менять Python backend, `mmm_core`, optimizer, model package, API
lifecycle или JSON schemas в рамках Phase 2 frontend PR.

## 6. Обязательные state semantics

- `loading`: запрос выполняется; старые значения другой кампании не
  подставляются как текущие;
- `empty`: допустим только для необязательной коллекции (например, warnings)
  или пустой истории; пустой `campaigns` — invalid contract;
- `invalid`: payload не прошёл client contract guard; fail closed;
- `failed` / `timed_out`: источник — lifecycle job/error API, не текст HTTP
  ошибки overview;
- `partial coverage`: источник — `budget`, `passport.unmodeled_channels`,
  `recommendation.plan_status` и warnings; недоступное не заменяется нулём;
- `S6 unavailable`: `available=false` и browser-safe статус по известному code;
  без candidate и metric invention;
- `sanitized_fixture`: всегда явно `Демонстрационные данные`; fixture никогда
  не считается реальным job result;
- unknown enum/version: controlled unsupported/invalid state, без optimistic
  fallback.
- `ModelPassport unavailable`: только подтвержденный
  `503 MODEL_PASSPORT_UNAVAILABLE`; неизвестный endpoint/version/shape даёт
  отдельный unsupported-contract, а не пустой ready state;
- `ModelPassport synthetic_fixture`: готовая структура может быть показана
  только с badge `Демонстрационные данные`.

## 7. Неприкосновенная domain boundary

Phase 2 не изменяет и не дублирует:

- Python backend и HTTP lifecycle;
- `mmm_core`, forecast, optimizer или model package;
- `decision_result_v1`, `result_overview_v1` и lifecycle JSON schemas;
- ROAS/quantile/reliability/allocation/recommendation mathematics;
- artifact integrity и download authorization.

Если реализация обнаружит новый обязательный field или endpoint, работа над
затронутым экраном останавливается: gap сначала добавляется в этот contract map
и выносится на отдельное согласование с backend owner.

## 8. Backend Phase D: navigation pages

Следующий frontend milestone должен использовать новые projections и не читать
storage/registry/content files:

| Экран | Endpoint | Contract | Source semantics |
|---|---|---|---|
| Главная | `GET /api/v1/workspace/home` | `workspace_home_v1` | Счетчики и карточки из persisted jobs, validation campaign summaries, published result/report flags, progress view и model overview. |
| История | `GET /api/v1/calculations/history` | `calculation_history_v1` | Server-side pagination, status/search/date filters и stable sort. Missing campaign facts равны `null`. |
| Модель | `GET /api/v1/model/overview` | `model_overview_v1` | Active ModelPassport плюс только реальные registry registrations; без fake quality score. |
| Справка | `GET /api/v1/help/catalog` | `help_catalog_v1` | Reviewed structured JSON; frontend не читает Markdown и не рендерит raw HTML. |

Frontend Phase D обязан валидировать `contract_name` и `schema_version`
fail-closed, различать loading/ready/empty/unavailable/error/unsupported-contract
и использовать только browser routes из response. Существующий
`GET /api/v1/models/active` остается источником подробных target-specific
channel policies; `model_overview_v1` предназначен для полной продуктовой
проекции страницы и истории реальных версий.
