# Frontend Phase E.1F Handoff: Historical Model Home Map

## Goal

Change only the Home map's data source and copy so it shows historical media
spend in the selected model data. Do not change the campaign map.

## Required source

Use:

```text
GET /api/v1/model/historical-geo-budget
```

Contract discovery:

```text
GET /api/v1/contracts/historical-model-geo-budget-v1.json
```

Generate and use `HistoricalModelGeoBudgetV1`. Runtime validation must remain
fail closed. Do not read registry files, model metadata, Parquet or local JSON
directly from the browser.

## Home changes

1. Replace the Home map request to `/api/v1/workspace/geo-budget` with
   `/api/v1/model/historical-geo-budget`.
2. Keep the existing `GeoBudgetMap` rendering and local map asset unless a
   typed adapter rename is required.
3. Use title `Исторический рекламный бюджет в данных модели`.
4. Show `period_start` and `period_end` using backend values.
5. Home tooltip must show geography, historical budget, budget share,
   `active_days_n` and the overall period.
6. Remove campaign count from the Home tooltip. The historical contract does
   not and must not expose it.
7. Continue selecting top labels by the backend-published
   `historical_total_budget_rub`; do not reconstruct spend from another source.
8. Preserve `available`, `partial`, `unavailable`, loading, HTTP error and
   unsupported-contract states. For `partial`, unlocated geographies and money
   remain visible in the coverage explanation.

## Must remain unchanged

- campaign map source: validation `view-v2`;
- campaign upload/validation;
- workspace calculation-history endpoint;
- MMM, forecast, optimizer, Scenario 6 and recommendation policy;
- canonical geo catalog and coordinate projection;
- backend aggregation and all budget arithmetic.

## Important distinction

`workspace_geo_budget_v1` means campaigns processed by the product.
`historical_model_geo_budget_v1` means approved spend columns in the model
training panel. Home uses the second after E.1F; a future history screen may
still use the first.

## Acceptance

- Home calls the historical endpoint exactly once per load/retry path;
- no frontend sum, campaign count or period inference;
- all 220 available rows can be rendered from the real local contract;
- partial and unavailable fixtures retain honest coverage copy;
- campaign map snapshots and behavior do not change;
- generated-contract drift, TypeScript, ESLint, unit tests, production build
  and desktop/mobile browser QA pass.
