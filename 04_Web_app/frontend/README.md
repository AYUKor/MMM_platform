# X5 MMM Frontend

React/Vite frontend for the local X5 MMM research-pilot application. The
current Phase E.1B milestone migrates business presentation to turnover-only
v2 contracts while preserving the existing authenticated product shell,
upload flow, progress screen, history and administration.

The browser never calculates MMM effects, ROAS quantiles, recommendation,
allocation deltas, risk composition or optimizer policy. It validates and
formats versioned backend projections. Unknown or internally inconsistent
payloads fail closed; v2 screens do not silently fall back to legacy v1
semantics.

## Product routes

- `/login` — session login;
- `/` — workspace summary and server-projected geo budget readiness;
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

## Phase E.1B projections

| View | Endpoint |
|---|---|
| Result and scenarios | `GET /api/v1/jobs/{job_id}/result-view-v2` |
| Scenario media plan | `GET /api/v1/jobs/{job_id}/media-plan-v2` |
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

Approved coordinates are currently unavailable, so the UI does not draw a
pseudo-map. `job_result_view_v2` also has no report artifact metadata; the
Report tab remains controlled unavailable instead of calling legacy v1.

Detailed boundary and current verification status:

- `../docs/integration/FRONTEND_PHASE_E1B_BUSINESS_SEMANTICS_V1.md`;
- `../docs/ui-review/phase-e1b-business-semantics-v1/REVIEW_NOTES.md`.

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
recorded in Phase E.1B review notes.
