# Frontend Phase 2: contract map

Статус: обязательное contract-first ограничение для Phase 2 Product Pages.

Базовая версия репозитория: `52d8d03168b1f6d85606ab9740d6ca08e825e349`
(`52d8d03`).

Post-merge update, 2026-07-15: этот документ был написан до Product API v1.1.
В текущем `main` (`61901af`) backend уже публикует versioned
`GET /api/v1/models/active` с `ModelPassport v1`. Поэтому прежний gap
Standalone Model Passport закрыт на backend-стороне; frontend route `/model`
пока остается controlled shell и требует отдельного typed-client integration.

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
| Подробное сравнение сценариев 1–6 | `scenarios[].scenario_id`, `available`, `budget.*`, `metrics.incremental_turnover`, `metrics.turnover_roas`, `metrics.incremental_orders`, `metrics.incremental_orders_usage`, `metrics.avg_basket_turnover_bridge`, `calculation_status`, `cell_support_status`, `optimizer_status`, `support`, `quality`, `paired_comparison` | `GET /api/v1/jobs/{job_id}/overview` | Абсолютные p10/p50/p90, budget и quality/support поддержаны. Для `available=false` метрики не подменяются нулями; показываются причина и `Нет данных`. S5 получает presentation-label `Устойчивый benchmark`. Orders явно маркируются `Диагностический показатель`; basket bridge нельзя называть изменением среднего чека. `paired_comparison` пока не выводится: contract не называет reference scenario, поэтому подпись сравнения нельзя утверждать. |
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
| Standalone Model Passport `/model` | Текущий разрешённый пакет, display-name/version, activation/readiness, blockers с человекочитаемым текстом, период модели, model quality/validation summary, lineage | `GET /api/v1/models/active` | **Backend contract поддержан Product API v1.1.** Payload строится из registry-verified package, сохраняет policy на уровне `segment x channel x target`, показывает replay/OOT/blockers и запрещает production claim. Frontend route пока не подключен: нужен typed client, runtime validation и loading/error/unavailable states без чтения registry/docs/local files. |

## 3. Политика человекочитаемых названий

UI не выводит raw backend names как пользовательские подписи.

| Backend-представление | UI-представление |
|---|---|
| `status.code`, warning `code` | Использовать для branching и browser-safe presentation map; raw code и технический `display_text` не показывать. Unknown code → общее fail-closed сообщение. |
| `scenario_id` | Использовать для порядка и логики; пользовательский заголовок брать из согласованной presentation map. Для S5 использовать label `Устойчивый benchmark`. |
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
6. controlled shell standalone Model Passport; после Phase 2 backend уже
   предоставляет ModelPassport v1, но подключение endpoint остается отдельной
   frontend integration задачей.

Все перечисленные экраны должны сохранять Phase 1 shell, tokens, themes,
типографику, responsive behavior и motion/reduced-motion правила.

## 5. Deferred scope и список contract gaps

До отдельного backend contract не реализуются:

1. **Агрегированные channel-only и geo-only decision totals/charts.** Overview
   содержит строки `segment × geo × channel`; если нужны отдельные backend-
   сверенные totals, их должна предоставить новая projection.
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

Закрытый после первоначального Phase 2 анализа gap:

- **Standalone Model Passport backend contract.** Product API v1.1 добавил
  `GET /api/v1/models/active`; остается только frontend integration, а не
  проектирование нового backend endpoint.

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
