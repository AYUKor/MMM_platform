# X5 MMM Frontend v1

Phase 1 implements the application foundation and the contract-backed Result
Overview page. The browser consumes the existing `decision_result_v1` shape;
it does not contain MMM, optimizer, reliability, or allocation mathematics.
The HTTP provider reads an immutable completed result from the local backend by
`job_id`; fixture mode remains available for isolated visual development.

The local core marketer flow is also available:

- `/calculations/new`: upload and model-aware validation;
- `/calculations/:id/progress`: background-job progress and cancellation;
- `/calculations/:id/result`: completed forecast and optimizer result;
- `/calculations`: server-side local job history.

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
npm run build
npm run test:e2e
```

The approved visual references live under `../docs/design/reference/`.
