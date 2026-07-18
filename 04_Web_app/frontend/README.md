# X5 MMM Frontend

React/Vite frontend for the local X5 MMM research-pilot application. The
current Phase E.1D milestone adds one contract-backed interactive geo-budget
map to Home and campaign validation while preserving the turnover-only product
semantics, authenticated shell, upload flow, progress, history and
administration.

The browser never calculates MMM effects, ROAS quantiles, recommendation,
allocation deltas, risk composition or optimizer policy. It validates and
formats versioned backend projections. Unknown or internally inconsistent
payloads fail closed; v2 screens do not silently fall back to legacy v1
semantics.

## Product routes

- `/login` — session login;
- `/` — workspace summary and server-projected geo budget map;
- `/calculations/new` — upload, file validation and grouped model limitations;
- `/calculations/:id/progress` — backend-projected calculation progress;
- `/calculations/:id/result` — turnover-only result, scenarios, media plan and
  report state;
- `/calculations` — server-side history search, filtering and pagination;
- `/model` — turnover-only model overview and Model Passport;
- `/help` — structured help catalog;
- `/admin/*` — permission-protected administration.

Protected requests use `credentials: "include"`. The HttpOnly session cookie
is not read by JavaScript, auth state is not persisted in browser storage and
permissions come only from `session.user.permissions[]`.

## Product projections

| View | Endpoint |
|---|---|
| Result and scenarios | `GET /api/v1/jobs/{job_id}/result-view-v2` |
| Scenario media plan | `GET /api/v1/jobs/{job_id}/media-plan-v2` |
| Report artifacts only | `GET /api/v1/jobs/{job_id}/result-view` |
| Validation presentation | `GET /api/v1/validations/{validation_id}/view-v2` |
| Active Model Passport | `GET /api/v1/models/active-v2` |
| Model overview | `GET /api/v1/model/overview-v2` |
| Geo catalog readiness | `GET /api/v1/meta/geo-catalog` |
| Workspace geo budget | `GET /api/v1/workspace/geo-budget` |

The result shows incremental turnover, both explicit ROAS denominators,
requested/allocated/unallocated budget, allocation share, uncertainty, risk
composition and the published media plan. Orders, orders per budget,
average-basket mechanics and turnover pseudo-decomposition are not product
metrics.

S1 is the uploaded reference plan and requires manual review. S5 is one public
conservative scenario: either `full_conservative` or `safe_partial`. S6 is
either a full feasible plan or a controlled infeasible state without fake KPI.
Changing the media-plan scenario changes only the viewed calculated plan; it
does not change the recommendation.

Validation keeps `Проверка файла` separate from grouped
`Ограничения модели`. Channel labels come from `channel_display_name`, while
IDs remain query identities. All structured geographies stay available in
filters.

## Phase E.1D maps

Home and campaign validation share `GeoBudgetMap`. Raw API objects are first
converted by typed adapters; the visual component receives only canonical
located points and server-published coverage/totals. Home uses
`workspace_geo_budget_v1`, labels its backend-budget top ten and does not sum
jobs or recalculate shares. Campaign validation uses `validation_result_v2`,
labels every located geography and keeps the complete text list beside the
map.

Both modes use one fixed spherical Albers Equal Area projection and a local
Natural Earth 1:50m outline. The outline is bundled into JavaScript and causes
no runtime tile or map-provider request. There is no browser geocoding, alias
matching or per-response min/max fitting. Bubble radius and brightness use a
square-root presentation scale; smaller points are painted first and larger
points last. Zero-budget points are intentionally not interactive.

`available`, `partial`, `unavailable`, empty, loading, network-error and
unsupported-contract states are distinct. Partial coverage retains the
unlocated geography list and the backend-published unlocated budget/share.
Visible attribution:

- `Координаты городов: GeoNames, CC BY 4.0.`
- `Контур карты: Natural Earth, public domain.`

Source, license, projection and product-use boundaries are documented in
`src/assets/maps/RUSSIA_OUTLINE_SOURCE.md` and
`../docs/adr/0024-frontend-fixed-geo-map-projection-v1.md`.

`job_result_view_v2` remains the only source of KPI, ROAS, budget, scenario,
recommendation and reliability semantics. A separate fail-closed client reads
only the `report` artifact envelope from `job_result_view_v1`; legacy campaign
and scenario fields are neither returned nor rendered.

Detailed boundary and current verification status:

- `../docs/integration/FRONTEND_PHASE_E1B_BUSINESS_SEMANTICS_V1.md`;
- `../docs/integration/FRONTEND_PHASE_E1D_INTERACTIVE_GEO_MAPS_V1.md`;
- `../docs/ui-review/phase-e1d-interactive-geo-maps-v1/REVIEW_NOTES.md`.

## Local development

Start the local backend first, then:

```bash
cp .env.example .env.local
npm ci
npm run generate:contracts
npm run dev
```

The default Vite address is `http://127.0.0.1:4173`. Configure
`VITE_API_BASE_URL` for the local backend. Synthetic fixtures are allowed only
in tests and review screenshots and must be visibly marked
`Демонстрационные данные`.

## Checks

```bash
npm run generate:contracts
npm run typecheck
npm test
npm run lint
npm run build
npm run test:e2e
```

Fixture Playwright, live backend acceptance without interception, Chromium
automation, Safari manual smoke and light/dark/mobile visual review are
separate evidence. A check is not considered passed until its actual result is
recorded in the current phase review notes.
