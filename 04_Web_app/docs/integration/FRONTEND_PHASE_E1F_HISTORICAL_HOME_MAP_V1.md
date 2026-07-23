# Frontend Phase E.1F: historical model budget on Home

## Статус и граница

Phase E.1F переключает только карту Главной с product-workspace aggregation на
исторические рекламные расходы из данных активной модели. Ветка начата от
`origin/main@370ea98024c7931dfd92c8ec4e289c6b0116e3da` после merge PR #27.

Python backend, schemas/OpenAPI, deployment, MMM, optimizer, auth, validation,
report flow, локальный SVG, projection, scaling, paint order и label layout не
меняются. Новых npm dependencies нет. Campaign mode продолжает получать точки
только из `validation_result_v2.geo_points`.

## Contract boundary

Home использует ровно один новый источник:

```text
GET /api/v1/model/historical-geo-budget
```

Typed client принимает только `HistoricalModelGeoBudgetV1` версии `1.0.0`,
выполняет fail-closed runtime validation, использует cookie session через
`credentials: "include"` и не читает registry, model files или Parquet.
`GET /api/v1/workspace/geo-budget` остается совместимым client method, но Home
его не вызывает и не использует как fallback.

Runtime parser проверяет exact object shape, contract identity, package/artifact
identities, period, coordinates, non-negative historical budget, active-day
counters, row/total/share reconciliation, unique geographies, coverage and
controlled unavailable semantics. Frontend не суммирует расходы и не выводит
period из дат отдельных строк.

## Home projection

`adaptHistoricalModelGeoBudget` передает в существующий `GeoBudgetMap`:

- `budgetRub` из `historical_total_budget_rub`;
- `budgetShare` из backend;
- `activeDaysN` и `activeRowsN` из backend;
- общий `periodDisplayText` из backend;
- готовые coverage counts, unlocated geography identities, budget и share.

Заголовок — `Исторический рекламный бюджет в данных модели`. Summary показывает
общий исторический бюджет, число географий, period и map coverage. При
`model_package_artifact_unavailable` значения не превращаются в нули: summary и
карта показывают controlled `Нет данных` / backend unavailable copy.

Historical tooltip содержит географию, исторический рекламный бюджет, долю
общего бюджета и общий period. Число дней с рекламной активностью скрыто из
UI с 2026-07-23 по решению владельца: метрика малоинформативна (у 181 из 220
географий значение 503 из-за always-on аллокации национальных каналов в
исходной панели). Поле `active_days_n` продолжает отдаваться backend-контрактом
без изменений. Число кампаний, запусков и прогнозный budget отсутствуют.

## Renderer invariants

Phase E.1F не меняет renderer E.1D:

- fixed Albers Equal Area projection и local Natural Earth outline;
- sqrt bubble radius, relative brightness и ascending-budget paint order;
- top-10 desktop / top-5 compact по backend
  `historical_total_budget_rub`;
- mouse, keyboard, click/touch, Escape и visible attribution;
- partial coverage сохраняет unlocated count, names, budget and share;
- campaign labels, tooltip, channels and limitations remain unchanged.

## Verification

| Gate | Result |
|---|---|
| Generated contract drift | passed; regeneration produced no tracked diff |
| TypeScript | passed |
| ESLint | passed with zero warnings |
| Targeted unit/component tests | 68/68 passed |
| Full frontend unit/component regression | 497/497 passed across 42 files |
| Production build | passed; 156 modules transformed |
| Targeted fixture Playwright | 18/18 passed in Chromium |
| Campaign map regression | 1/1 targeted fixture test passed |
| Live local historical artifact, no interception | 1/1 passed against the real registered package |
| GitHub CI | required to be green before the Draft PR is marked Ready |

The live Home acceptance observed `status=available`, 220/220 canonical
geographies, period 2025-01-01 through 2026-05-31, zero unlocated budget and
the backend-published top three Москва, Санкт-Петербург and Московская область.
It also verified one historical request, no workspace fallback, the historical
tooltip without campaign counts and a clean browser console.

Review screenshots and browser evidence are tracked in
`docs/ui-review/phase-e1f-historical-home-map-v1/REVIEW_NOTES.md`.

## Deployment limitation

The hosted research-pilot transfer bundle currently does not carry the local
`package_artifacts` extension. Hosted `status=unavailable` is therefore an
expected controlled state for this frontend phase, not a reason to fall back to
workspace totals. Deployment packaging is outside Phase E.1F.
