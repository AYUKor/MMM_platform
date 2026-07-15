# X5 MMM Frontend v1

Phase 1 implements the application foundation and the core marketer flow.
Phase 2 extends the completed-result workspace with scenario comparison,
status-based reliability, warnings, line-level media-plan comparison, report
downloads, and controlled incomplete/error states.
The Model Passport milestone connects `/model` to the versioned Product API
without reading registry, documentation, or model files in the browser.

The browser prioritizes `GET /api/v1/jobs/{job_id}/overview` and keeps the full
`/result` payload as an audit contract outside the product presentation. It does
not calculate MMM effects, ROAS quantiles, reliability scores, allocation
deltas, or optimizer recommendations.

The local core marketer flow is also available:

- `/calculations/new`: upload and model-aware validation;
- `/calculations/:id/progress`: background-job progress and cancellation;
- `/calculations/:id/result`: completed forecast and optimizer result;
- `/calculations`: server-side local job history.
- `/model`: active `ModelPassport v1` from `GET /api/v1/models/active`, with
  fail-closed runtime validation and explicit research/preprod boundaries.

The result workspace contains five tabs:

- Overview;
- Scenarios 1–6;
- Reliability and warnings;
- Media plan (`segment × geo × channel` line items);
- Report downloads.

Channel/geo aggregates and report preview/status remain explicit contract
gaps. The Model Passport page shows loading, ready, unavailable, error and
unsupported-contract states and never reconstructs missing values.

## Local development

```bash
cp .env.example .env.local
npm ci
npm run generate:contracts
npm run dev
```

Start `04_Web_app/backend_runtime.py` first, then open
`http://127.0.0.1:4173/calculations/<job_id>/result`. When a result contains
multiple campaigns, add `?campaignId=<campaign_id>` or select one on the page.

Set `VITE_RESULT_PROVIDER=fixture` when the backend is intentionally not used.
Fixture mode is available only in a development build and always shows the
`Демонстрационные данные` badge. A production build without an API provider
fails closed with a controlled unavailable state.

## Checks

```bash
npm run typecheck
npm test
npm run lint
npm run build
npm run test:e2e
```

Browser tests intercept the existing API routes with explicit sanitized or
synthetic responses. They cover desktop/mobile, dark/light themes, S6
unavailable, partial coverage, result failure states, all Model Passport
states, keyboard tabs, document overflow, and raw internal-name leakage.

The approved visual references live under `../docs/design/reference/`.
