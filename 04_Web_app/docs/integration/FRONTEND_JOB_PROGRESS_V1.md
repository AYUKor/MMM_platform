# Frontend Job Progress V1

Status: implemented in Frontend Phase B

Backend baseline: `b7208d4b4b2e224204675e6e7b2d81f2cd75e7d7`

## Scope

Маршрут `/calculations/{job_id}/progress` показывает продуктовый процесс
расчета для маркетолога. Экран не читает technical progress events и не
воспроизводит логику worker в браузере.

Используются только:

- `GET /api/v1/jobs/{job_id}/progress-view` для всего состояния расчета;
- `GET /api/v1/meta/mmm-facts` для необязательного блока `MMM за минуту`;
- существующий `POST /api/v1/jobs/{job_id}/cancel` только после явного
  подтверждения пользователя.

Raw `GET /api/v1/jobs/{job_id}/progress`, отдельные job/error GET-запросы,
frontend-derived percent и автоматический redirect на result не используются.

## Typed boundary и runtime validation

Client использует сгенерированные `JobProgressViewV1` и `MMMFactCatalogV1`,
но не доверяет TypeScript type assertion как runtime-проверке. Parser
fail-closed проверяет:

- `contract_name` и `schema_version`;
- exact object keys и поддержанные enums;
- совпадение `job_id` ответа с ID текущего route;
- opaque IDs, ISO dates и timezone-aware timestamps;
- ровно девять этапов P01-P09, их ID, order и contract titles;
- допустимые timestamps по status и хронологию этапов;
- queue consistency;
- nullable и bounded stage/Scenario 6 counters;
- terminal constraints, `can_cancel`, `result_available` и обязательный
  completed report для succeeded;
- отсутствие absolute workstation paths;
- минимум 20 уникальных и коротких MMM facts.

Malformed или future payload не отображается частично: пользователь получает
controlled unsupported-contract state.

## Polling и recovery

- `queued`, `running`, `cancel_requested`: polling каждые 1.5 секунды;
- terminal status: polling прекращается;
- fetch получает `AbortSignal` от React Query при unmount и смене `job_id`;
- один query хранит последний успешный snapshot;
- temporary network/409/unsupported refetch не стирает уже показанные данные;
- refresh и deep link полностью восстанавливаются из `progress-view`;
- 404, 409, initial network failure и unsupported contract имеют разные
  безопасные состояния и действия.

## Экран

Campaign header использует только `progressView.campaign`: название,
сегменты, период, бюджет, число каналов и географий. `synthetic_fixture`
всегда получает badge `Демонстрационные данные`.

Current status card использует `job_status`, `queue`, `current_stage_id` и
соответствующий backend stage. В нем нет общего процента или ETA. При наличии
stage counter показываются исходные `current` и `unit`; `total` добавляется
только когда он присутствует в contract.

Timeline отрисовывает `stages[]` строго в полученном порядке. `pending`,
`active`, `completed`, `warning`, `failed` и `skipped` имеют отдельный текст,
иконографику и цвет; status не кодируется только цветом. Отсутствующее время
не заменяется `0:00`.

## Scenario 6 и отчет

Панель `Адаптивный поиск` ветвится только по `scenario6.status`.
`attempts_checked` и `finalists_scored` отображаются, когда доступны;
`attempt_budget` и `finalists_total` добавляются к ним только при наличии.
Строки `safe_candidates` и `blocked_candidates` скрываются только при `null`;
известный numeric zero отображается как `0`, как и любое положительное значение.
Winner, ROAS, forecast effect и recommendation на progress page не показываются.

Report — отдельная панель на основе `report.status`, `display_text` и
`retryable`. Progress page не добавляет download или retry action, которых нет
в contract.

## Errors и cancellation

Используются только `progressView.errors`. Записи с `blocking=true`
сортируются выше остальных, а подпись и tone карточки определяются реальным
`severity`. UI показывает product stage, `display_text` и `recommended_action`.
`error_id`, component, stack trace и raw internals не выводятся.

Cancel action доступен только при `can_cancel=true`. Собственный modal dialog:

- объясняет последствия;
- поддерживает Tab loop, Escape и возврат focus;
- блокирует повторное нажатие во время запроса;
- не выставляет terminal status optimistic;
- после успешного POST запрашивает новый `progress-view`.

## MMM facts

Catalog загружается независимо от progress snapshot. Один факт выбирается
детерминированным hash от `job_id`, поэтому он не прыгает при каждом polling и
не меняется чаще 15 секунд. Machine category скрыта, source label показан. При
network или contract error весь блок скрывается, а progress page продолжает
работать. В production bundle нет локального fallback-каталога.

## Accessibility и responsive behavior

- `aria-live` для current status;
- semantic ordered list для P01-P09;
- text labels для всех statuses и counters;
- visible focus, skip link и 44px controls из существующего design system;
- focus-managed modal без native `confirm`;
- `prefers-reduced-motion` отключает sweep/pulse;
- одна колонка на mobile, без horizontal document overflow;
- длинные campaign names, segments и browser-safe errors переносятся;
- обе темы используют Phase A tokens и accent `#C7FD72`.

## Verification

На implementation head выполнены:

- generated contract regeneration без drift;
- TypeScript: passed;
- ESLint: passed, zero warnings;
- Vitest: `187/187` passed;
- production Vite build: passed;
- full Playwright regression on system Chrome: `81/81` passed;
- light/dark review screenshots: 12 файлов `1440 x 900`;
- mobile `375 x 812`, landscape, long content, reduced motion, keyboard,
  cached-refetch error и no-overflow checks: passed.

Live no-interception acceptance и screenshot semantics описаны в
`04_Web_app/docs/ui-review/job-progress-v1/REVIEW_NOTES.md`.

## Known limitations

- backend пока возвращает `safe_candidates` и `blocked_candidates` как
  `null`;
- честных live counters для пакетных P03-P05, общего percent и ETA нет;
- report-only retry endpoint отсутствует;
- review PNG используют explicit synthetic E2E payloads и не являются
  evidence модельного результата;
- Safari отдельно не проверялся и не заявлен как passed.

Python backend, JSON Schemas, OpenAPI, worker, lifecycle contracts, MMM,
forecast, optimizer, recommendation policy и result pages не изменены.
