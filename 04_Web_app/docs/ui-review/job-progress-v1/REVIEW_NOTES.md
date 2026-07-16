# UI review notes: `/calculations/{job_id}/progress` V1

## Review setup

Review screenshots создаются
`04_Web_app/frontend/e2e/job-progress.visual.spec.ts` при точном viewport
`1440 x 900` попарно в dark/light themes. Fixture responses существуют только
в E2E code, имеют `record_origin=synthetic_fixture` и всегда показывают badge
`Демонстрационные данные`. Production frontend не содержит fixture provider
или fallback values для progress page.

Screenshot matrix:

- `01-queued-dark.png`, `01-queued-light.png`;
- `02-running-prepare-dark.png`, `02-running-prepare-light.png`;
- `03-running-scenario6-dark.png`, `03-running-scenario6-light.png`;
- `04-running-report-dark.png`, `04-running-report-light.png`;
- `05-succeeded-dark.png`, `05-succeeded-light.png`;
- `06-failed-dark.png`, `06-failed-light.png`.

Все PNG имеют размер `1440 x 900`. Screenshot — visual review artifact, а не
production campaign result или свидетельство корректности MMM mathematics.

## Contract-backed UI coverage

- campaign summary только из `progressView.campaign`;
- status badge по поддержанным `job_status.code`;
- known и unknown queue positions без подстановки zero;
- P01-P09 в backend order;
- все шесть stage statuses;
- active stage counter без общего percent или ETA;
- Scenario 6 pending/running/completed/unavailable/failed;
- `null` candidate counters скрываются, а известный numeric zero показывается
  как `0`;
- report pending/running/completed/failed/not_required;
- blocking errors выше warnings, с browser-safe action;
- cancel только через modal confirmation;
- succeeded остается на progress URL, result открывается только по ссылке;
- temporary refetch error сохраняет последний snapshot;
- facts unavailable не ломает страницу;
- 404, 409, unsupported version и route job mismatch fail closed;
- raw `/progress` route запрещен E2E assertion.

## Visual and accessibility QA

Проверено в system Chrome:

- dark/light parity;
- desktop `1440 x 900`;
- mobile `375 x 812`;
- landscape `812 x 375`;
- long campaign name, four long segments и long safe error;
- zero horizontal document overflow;
- keyboard open/Escape/focus return для cancel dialog;
- visible text statuses, а не color-only meaning;
- reduced motion отключает looping indicators;
- terminal polling прекращается;
- visible copy не содержит `backend`, `API`, `worker`, `phase`,
  `Progress events`, `posterior`, `candidate_id` или `attempt_id`.

## Live HTTP acceptance

Status: **passed 2026-07-16 without route interception**.

Backend baseline:

- commit `b7208d4b4b2e224204675e6e7b2d81f2cd75e7d7`;
- deployment profile `local_development`;
- panel-free `serving_bundle` verification;
- package `pkg_807d3ddbae57a52a_9aacd3beb350725b`;
- package fingerprint
  `807d3ddbae57a52ad184f94cd5442cdefd97764fe3903e5b250b5d04cd26c62c`;
- source panel `provenance_only_not_copied`;
- 55 verified inventory files;
- `/ready = ready`;
- facts contract `mmm_fact_catalog_v1@1.0.0`, 20 facts.

Real application resources created through HTTP from an explicit synthetic
two-cell campaign input:

- upload `upload_4647cda719094177943d`, status `parsed`;
- validation `validation_d4a615e1ac1e3c198a44`, status `valid`, one campaign;
- cancel flow job `job_0e6e65ac66cc05893305`;
- success flow job `job_484bd2e6480ba82c30cf`.

Observed through the actual browser page:

1. Success job initially returned `queued`, position `1 of 1`; UI showed the
   same queue text.
2. `MMM за минуту` loaded from the real facts endpoint.
3. Running job exposed `can_cancel=true`; browser dialog confirmation issued
   `POST /api/v1/jobs/{job_id}/cancel` and backend reached `cancelled`.
4. The queued job then ran through the real worker and reached `succeeded`,
   `current_stage_id=P09`, `result_available=true`.
5. Terminal Scenario 6 counters were exactly backend values:
   `attempts_checked=60`, `attempt_budget=128`,
   `finalists_scored=5`, `finalists_total=5`; safe/blocked remained `null`.
6. Report status was `completed`, display text `Excel-отчет готов.`
7. After 1.8 seconds browser URL remained the progress route; result link was
   visible and no automatic navigation occurred.
8. Full refresh restored terminal state from `progress-view`.
9. Mobile document overflow was `0 px`.
10. Browser Network contained only `GET .../progress-view`,
    `GET /api/v1/meta/mmm-facts` and the explicit cancel POST. Raw
    `GET .../progress` count was zero.
11. Final terminal browser run had zero failed application API responses and
    zero JavaScript runtime errors. The browser's unrelated automatic
    `/favicon.ico` request returned `404` and is outside this screen milestone.

Reduced sampling and synthetic input prove application integration only. They
are not production-effect evidence and do not change the research/preprod
status of the model.

## Quality gates

- generated contract drift: none;
- TypeScript: passed;
- ESLint: passed, zero warnings;
- Vitest: `20` files, `187/187` passed;
- production Vite build: passed;
- progress Playwright suite: `39/39` passed;
- full Playwright regression: `81/81` passed;
- 12 required review screenshots regenerated after manual visual inspection.

Production build reports the existing bundle-size advisory above 500 kB; build
completes successfully. Route-level code splitting remains a future
application-wide optimization, not a blocker for this isolated milestone.

## Known limitations

- safe/blocked candidate aggregates are unavailable in the current backend;
- P03-P05 are product checkpoints over a batched calculation window;
- no overall percent, ETA or report-only retry endpoint exists;
- Safari was not run in this acceptance and is not claimed as passed.

Backend, schemas, OpenAPI, worker, MMM, forecast, optimizer, result pages and
`/calculations/new` were not changed.
