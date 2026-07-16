# UI review notes: `/calculations/{job_id}/result` V1

Review status: **local acceptance passed**.

Backend baseline:
`591193f433e5eb3f80f924539bd09cd1c27e50ef`

Branch:
`codex/frontend-result-experience-v1`

GitHub CI and final Ready-for-review status are tracked in the Pull Request.

## Review boundary

The result route reads only:

- `GET /api/v1/jobs/{job_id}/result-view`;
- `GET /api/v1/jobs/{job_id}/media-plan`;
- the artifact download path published by `result-view`.

The frontend does not reconstruct recommendation, ranks, ROAS, P10/P50/P90,
reliability, allocation deltas or Scenario 6 policy. It does not call legacy
`GET .../result`, `GET .../overview`, raw progress or lifecycle resources
to assemble the result.

S1 remains `Исходный план` / `Как загружено`. S5 remains
`Устойчивый ориентир`. Switching the scenario in the media-plan tab changes
only the viewed, already-calculated plan and never changes the canonical
recommendation.

Synthetic payloads are used only by unit/E2E tests and review screenshots.
Every such result uses `record_origin=sanitized_fixture` and visibly shows
`Демонстрационные данные`.

## Screenshot matrix

Every committed PNG is exactly `1440 x 900` and was manually inspected for
hierarchy, wrapping, contrast, clipping and overlap.

| File | State | Result |
|---|---|---|
| `01-overview-recommended-dark.png` | canonical recommendation, dark | passed |
| `01-overview-recommended-light.png` | canonical recommendation, light | passed |
| `02-overview-no-safe-dark.png` | no safe automatic recommendation, dark | passed |
| `02-overview-no-safe-light.png` | no safe automatic recommendation, light | passed |
| `03-scenarios-dark.png` | S1-S6 and reliability, dark | passed |
| `03-scenarios-light.png` | S1-S6 and reliability, light | passed |
| `04-best-raw-dark.png` | separate non-recommended best raw, dark | passed |
| `04-best-raw-light.png` | separate non-recommended best raw, light | passed |
| `05-media-plan-dark.png` | scenario plan, filters and table, dark | passed |
| `05-media-plan-light.png` | scenario plan, filters and table, light | passed |
| `06-media-plan-partial-dark.png` | unallocated remainder, dark | passed |
| `06-media-plan-partial-light.png` | unallocated remainder, light | passed |
| `07-report-dark.png` | ready workbook and sheets, dark | passed |
| `07-report-light.png` | ready workbook and sheets, light | passed |
| `08-unavailable-dark.png` | controlled unavailable structures, dark | passed |
| `08-unavailable-light.png` | controlled unavailable structures, light | passed |

Review directory:
`04_Web_app/docs/ui-review/job-result-v1/`

Screenshot generator:
`04_Web_app/frontend/e2e/job-result.visual.spec.ts`

## Product and contract checks

- Four URL-backed tabs are present: overview, scenarios/reliability,
  media-plan and report.
- Refresh, deep links, Back and Forward restore the tab and viewed media
  scenario.
- S1, S5 and recommendation semantics remain distinct without duplicate
  scenario cards.
- No-safe state creates no synthetic winner.
- Best raw is conditional and explicitly marked as non-recommended audit
  evidence.
- Missing metrics and ranks render `Нет данных`; numeric zero stays visible.
- P10/P50/P90 are rendered directly from the response.
- A null reliability score does not become `0/10`; all six qualitative
  reliability components remain visible.
- Orders metrics retain a diagnostic label.
- The average-basket bridge is not presented as average-basket delta.
- Channel, geo and geo-channel charts use published aggregates.
- Paginated rows are not summed into canonical totals.
- Requested, allocated and unallocated budget remain visible.
- Exact channel/geo filters, reset, page size and pagination use only the
  media-plan contract.
- Empty valid filters render an empty state; HTTP 422 stays inside the
  media-plan tab.
- Ready report uses the validated artifact metadata and canonical download
  path. Failed/unavailable reports invent neither a file nor a retry action.
- Map, daily plan and channel calendar remain controlled unavailable states.
  The current working XLSX is unavailable; the existing v1 `ready` artifact
  state has its own validated download UI.
- Loading, missing, not-ready, 409, 503, network, refresh and
  unsupported-contract states fail closed.
- Refetch failure preserves the last validated result snapshot.
- Visible product copy contains no raw implementation names.

## Accessibility and responsive checks

- Tabs expose `tablist`, `tab`, `tabpanel` and selected state.
- ArrowLeft, ArrowRight, Home and End keyboard navigation passed.
- Focus remains visible in both themes.
- Tables have captions and headers and scroll inside their own region.
- Charts expose text alternatives with exact values.
- Status is not encoded only by color.
- Mobile `375 x 812`: zero document overflow.
- Landscape `812 x 375`: zero document overflow.
- Long campaign, segments and warning copy wrap safely.
- The media table remains wider than its mobile viewport and scrolls only
  inside its own region; the document itself stays at zero horizontal
  overflow.
- Reduced motion left no active looping animation.
- Live browser console contained zero application errors and warnings.

## Automated quality gates

| Check | Result | Evidence |
|---|---|---|
| Generated contracts | passed | 8 files; second generation produced identical hashes |
| TypeScript | passed | `tsc -b --pretty false` |
| ESLint | passed | zero warnings |
| Unit tests | passed | 285/285 across 24 files |
| Production build | passed | Vite 8.1.4, 126 modules |
| Phase C Playwright | passed | 36/36 |
| Full frontend Playwright | passed | 110/110 on a clean port |
| Screenshot dimensions | passed | 16/16 at `1440 x 900` |
| Manual visual inspection | passed | 16/16 PNGs inspected in both themes |
| Live no-interception acceptance | passed | real local backend and in-app browser |

Production output:

```text
dist/index.html                   0.51 kB | gzip 0.31 kB
dist/assets/index-vIuI1Dsh.css  109.71 kB | gzip 18.73 kB
dist/assets/index-DZ7XqNod.js   530.71 kB | gzip 152.33 kB
```

Vite reports the advisory warning for a minified JavaScript chunk above
500 kB. The production build succeeds. Route-level code splitting remains a
separate performance follow-up, not a Phase C contract/correctness blocker.

## Live backend acceptance

The no-interception run used the actual backend from the exact baseline and a
previously completed `application_runtime` job:

- runtime baseline:
  `591193f433e5eb3f80f924539bd09cd1c27e50ef`;
- job: `job_484bd2e6480ba82c30cf`;
- result: `result_5588884df3c47127d6e8`;
- job status: `succeeded`;
- startup recovery: zero resumed uploads, validations and queued jobs; zero
  interrupted jobs;
- `result-view`: passed; S1 source, S5 benchmark, canonical recommendation
  S01, ready report;
- media-plan: S1, S5 and S6 passed with reconciled totals;
- exact S6 filter: `channel=OOH_Total`, `geo=МОСКВА`,
  `page_size=1` passed;
- browser scenario switching changed the viewed plan only;
- legacy `/result` requests: 0;
- legacy `/overview` requests: 0;
- console errors/warnings: 0;
- desktop/mobile document overflow: 0.

The canonical report artifact was downloaded through the real artifact
endpoint:

```text
artifact_id: artifact_07f854a1d3540e252469
size: 12887 bytes
sha256: 25c909f212754e3828880b5ad647cc6bea75cd47ef6172223d57b1b86ac33500
XLSX container check: passed
```

The four source artifact hashes were unchanged before and after acceptance.
No POST request or optimizer rerun was performed.

The job originated from the synthetic acceptance input
`progress_acceptance.csv`. The run therefore validates the application
runtime, contracts, browser integration and artifact transport only. Its
calculation values must not be cited as model-quality or business-effect
evidence.

## Controlled contract limitations

- numeric reliability score is unavailable;
- average-basket delta is unavailable;
- daily scenario plan and channel calendar are unavailable;
- approved map coordinates/projection are unavailable;
- separate working media-plan XLSX is unavailable;
- allocation recommendation is not a launch/cancel campaign decision.

These are honest controlled states, not values for frontend inference.

## Accepted stale-document conflicts

The user explicitly authorized Phase C to proceed with two non-blocking stale
truth-document conflicts:

1. `PROJECT_BRIEF.md` still describes Frontend Phase B progress integration
   as a future milestone although PR #16 is merged.
2. `CURRENT_TRUTH.md` points to nonexistent
   `frontend/src/pages/CalculationProgressPage.tsx`; the actual implementation
   is `frontend/src/pages/JobProgressPage.tsx`.

Neither truth document is edited in this PR. Their cleanup belongs to a
separate truth-freeze/documentation task and does not change the accepted
Phase C contracts.

Backend, schemas, OpenAPI, worker, MMM, forecast, optimizer, Scenario 6 ranking
and recommendation policy are outside this review.
