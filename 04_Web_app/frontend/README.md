# X5 MMM Frontend v1

Phase 1 implements the application foundation and the contract-backed Result
Overview page. The browser consumes the existing `decision_result_v1` shape;
it does not contain MMM, optimizer, reliability, or allocation mathematics.

## Local development

```bash
cp .env.example .env.local
npm ci
npm run generate:contracts
npm run dev
```

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
