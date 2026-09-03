# MMM Platform — Current Truth

## Last verified

- Verification date: **2026-09-03**.
- Mode: **D1R5 — accepted federal functionality live deployment and observation**.
- Verified against local code, Git/GitHub state, Fin manifests and transfer
  checksums, server materialization evidence, live server identity, HTTP/browser
  acceptance and persisted product state.
- No DWH query, model/data recalculation, model-status change, persistent-state
  migration, JupyterHub restart or external infrastructure change was performed.

## Product status

MMM Platform is an internal research-pilot web application for uploading campaign
plans, validating geo/channel inputs, calculating posterior-based incremental
turnover scenarios, reviewing uncertainty and downloading a canonical report.

The application and portal are implemented. The active model package is **not a
production model**: it is `preprod_restricted` because sealed OOT validation is
missing or failed. The product is therefore decision support under explicit risk
limits, not an automated media-buying or finance approval system.

## Repository

- Canonical local workspace root: `<MMM_WORKSPACE_ROOT>`.
- Canonical local development repository: `01_Test/MMM_platform` under that root.
- Remote: `https://github.com/AYUKor/MMM_platform.git`.
- `origin/main` is the source of truth for released application code.
- Data, research outputs, project brain, staging evidence and Fin releases remain
  outside this Git clone in their canonical four-contour locations.
- The old workspace is physically preserved at `<MMM_LEGACY_ROOT>` as
  `LEGACY_ROLLBACK_ONLY`; it is not an operational fallback.
- A local migration staging copy outside `<MMM_WORKSPACE_ROOT>` is non-canonical,
  not a development, release or deployment source.
  C2.6 found zero staging-only files and zero unique staging evidence; it is not an
  exact current copy because canonical Git/docs/evidence advanced after relocation.
  It is only a future delete candidate requiring separate authorization.

## Current Git state

- Fetched `origin/main` after user-merged test-only PR #44:
  `b0d91d3936435d1fb849c957add20a1a4ec31f83`.
- The accepted and deployed application runtime remains commit
  `9355c6c8fdaf9d715434848ec306670e944ff263`, tree
  `d8f69aa5c47a1cbacca1aee6c94aaab85f841a31`.
- PRs #43 and #44 changed tests/acceptance tooling only and did not create a new
  runtime application or Fin identity.
- D1R5 lifecycle documentation is isolated in
  `codex/d1r5-end-to-end-lifecycle` from the current `origin/main`.
- Old Git clones/worktrees remain rollback/reference evidence and were not pruned
  or deleted.

## Canonical local workspace

- `00_Data` — canonical local data contour.
- `01_Test` — canonical local development/research contour.
- `02_Predfin` — canonical local staging/acceptance contour.
- `03_Fin` — canonical immutable deployable release contour.

Pre- and post-rename operational smoke passed using only these contours at the
exact canonical root. Both path scans found zero runtime, model-lookup, registry or
application blockers and no legacy fallback. Historical/provenance/evidence path
records remain factual history and are not mass-rewritten in C2.6.

Current Fin release:
`release_9355c6c8fdaf_807d3ddbae57_ed8a6c6c7642_77973f4d424c`. Its application
and frontend closure are approved and deployed; its model remains
`preprod_restricted` with `production_gate = not_passed`.

## Deployment

The accepted deployment flow is:

`accepted local code -> GitHub main -> Predfin acceptance -> immutable Fin release
-> verified Fin transfer artifact -> immutable server candidate materialization
-> atomic current switch -> backend/UI health, identity and business-flow checks`.

- Frontend production build uses `VITE_API_BASE_URL=""` and same-origin `/api`.
- The corporate server is documented as having no outbound GitHub access; offline
  Git bundles are therefore the intended application-code transfer mechanism.
- The panel-free model serving package is transferred and hash-verified separately
  from application Git.
- The only permitted local deployment source is the verified transfer artifact of
  a selected Fin release. Test, Predfin and the legacy workspace are not deployment
  sources.
- Server candidates are created only through the reviewed
  `04_Web_app/deployment/server_release.py` from the verified Fin transfer; every
  attempt receives a new `<release_id>__deployN` identity.
- D1R5 proved the complete transfer, materialization, alternate-port preflight,
  atomic switch, rollback readiness, frontend delivery identity and product
  acceptance path for deploy5.

## Server status

**Live verified during D1R5 on 2026-09-03:**

- Primary product URL: `https://mmm.x5.ru`.
- `/opt/x5-mmm/current` is the relative symlink
  `releases/release_9355c6c8fdaf_807d3ddbae57_ed8a6c6c7642_77973f4d424c__deploy5`.
- Backend process CWD resolves to that exact immutable deploy5 directory and serves
  commit `9355c6c8...`, tree `d8f69aa5...` and package
  `pkg_807d3ddbae57a52a_9aacd3beb350725b`.
- External `/health` is `ok`; external `/ready` is `ready`; the historical endpoint
  is available with 220/220 geographies and exact total
  8,687,024,294.654741 RUB.
- Nginx serves target `index.html`, `index-Bz99Cbil.js` and
  `index-DmSMKp-y.css` through `current`; external bytes and clean-browser assets
  match the Fin manifest. Nginx was not restarted or reloaded in D1R5.
- JupyterHub remains a separate active `x5-jupyterhub.service`; `/hub/` reaches its
  login route. It was not restarted.
- Backend switch downtime was approximately 6.43 seconds. Auth, existing history,
  an old result and an old report remained readable.
- Release-local `SERVER_RELEASE.json` is sealed as `root:root`, mode `0444`, status
  `accepted`, SHA-256
  `a9f590447c12b47aab5dde323075f4e227a92ab8ac302089ff3a1029a16a1544`.
- External DNS, FIP/load balancer, firewall, corporate proxy/VPN and TLS are
  existing infrastructure and were not changed.

## Model

Active pointer chain:

`03_Outputs/01_PyMC_outputs/00_Model_registry/channels/preprod.json`
-> `pkg_807d3ddbae57a52a_9aacd3beb350725b`.

- Package fingerprint:
  `807d3ddbae57a52ad184f94cd5442cdefd97764fe3903e5b250b5d04cd26c62c`.
- Package schema: `0.4.0`; gate policy: `1.2.0`.
- Stage: `posterior_ready`.
- Activation: `preprod_restricted`.
- Blocking gate: `MISSING_OR_FAILED_OOT_VALIDATION`.
- No `production.json` pointer was found.
- Research package contains 12 posterior fits:
  4 segments (`ТС5/Онлайн`, `ТС5/Оффлайн`, `ТСХ/Онлайн`, `ТСХ/Оффлайн`)
  x 3 targets (`turnover_per_user`, `orders_per_user`, `avg_basket`).
- All 12 expected fits and diagnostics are present; historical replay passed.
  This does not replace sealed OOT validation.

The model estimates incremental media contribution under a campaign versus a
no-campaign counterfactual. It is not a full turnover forecast and does not prove
causality against all unobserved confounding.

## Serving

- Product serving activates only `turnover_per_user`: **4 active serving models**,
  one per segment.
- The 8 orders/basket research fits remain package evidence but are not active
  business-serving targets.
- Public target id is `turnover`.
- Serving contracts fail closed unless the package has exactly 12 research models
  and the allowed 4 turnover serving models.
- Serving status must be described as restricted preproduction, never as
  unrestricted production readiness.

## Source data

Canonical physical panel:

`<MMM_WORKSPACE_ROOT>/00_Data/panels/02_2025_2026Q1_second_pass/panel_final_v3.parquet`.

- Recomputed SHA-256:
  `9aacd3beb350725be483145bf955dbc26f9b5dd7a510708c4ae4ec700e4b4552`.
- Physical metadata: 308,886 rows, 109 columns, 220 unique `geo_label` values.
- Panel period: **2025-01-01–2026-05-31**.
- Model training period: **2025-01-01–2026-03-20**.
- Development shadow/holdout: **2026-03-21–2026-05-31**.

Therefore 2026-05-31 is the end of the source panel, not the end of model training.
The registry records a workspace-relative data path; the physical panel is outside
the application Git clone. It is excluded from the panel-free server bundle.

## Scenarios

The public scenario set is S1–S6:

- **S1 Uploaded plan** — factual/reference allocation. It is always retained and
  requires manual review; it is never automatically presented as an optimized
  recommendation.
- **S2 Equal cells** — equal budget across eligible geo x channel cells.
- **S3 Equal geographies within channel totals** — preserves channel totals and
  equalizes eligible geographies.
- **S4 Equal channels within geography totals** — preserves geography totals and
  equalizes eligible channels.
- **S5 Conservative** — searches approved support levels from p95 through p99 to
  robust upper bounds. Public result is either `full_conservative` with the full
  budget and no high-risk cells, or `safe_partial` only after full safe allocation
  is infeasible. A partial result exposes unallocated budget and cannot be an
  automatic recommendation.
- **S6 Adaptive/effect-first** — posterior marginal-effect search inside approved
  risk limits. `full_effect_maximizing` must allocate the full requested budget;
  otherwise status is explicitly `infeasible` with null business metrics. The
  policy does not claim a global mathematical optimum.

Only a complete policy-safe plan with material improvement may be recommended. If
that condition is absent, S1 remains the decision reference.

## Result semantics

Primary business result is posterior incremental turnover with uncertainty:

- incremental turnover `p10 / p50 / p90`;
- ROAS with an explicit requested- or allocated-budget denominator;
- requested, allocated and unallocated budget;
- allocation share and reconciliation;
- risk composition, warnings and limiting constraints;
- geo x channel media plan.

`orders`, `average basket`, orders per 100k and related bridge metrics are not v2
product KPIs. They must not be reconstructed from research fits and shown as active
serving outcomes.

## Geo

Federal campaign upload in the B2.2S Test candidate uses
`FEDERAL_GEO_ALLOCATION_V1`. Approved aliases are `РФ`, `Россия` and
`Российская Федерация`, with outer-whitespace trimming and case-insensitive
matching only. Expansion happens independently per federal daily source row over
the source row's date-ready subset of active-package direction geographies;
missing population inside that ready subset fails closed and no mean fallback
exists.

`ForecastGeoAvailabilityResolver` and `ForecastEngine` use the same pure
denominator lookup. Required coverage is `campaign_start .. campaign_end + lmax`
inclusive; active policy is analog year 2025, same geo and nearest observation no
farther than 7 days. There is no extrapolation, cross-geo fill or Yakutsk special
case. Runtime forecast denominator resolution remains fail-closed.

`validation_result_v2.federal_allocation` is derived from the durable allocation
audit and exposes only a browser-safe aggregate/direction breakdown. The
active-package dictionary is available at
`GET /api/v1/templates/media-plan-dictionary`. Full product semantics and test
matrix are in `docs/integration/B2_2_FEDERAL_CAMPAIGN_UX_V1.md`.

For a one-day `2026-09-01` campaign the current package regression is
`175 / 182 / 103 / 104` ready out of declared `211 / 220 / 114 / 117`. These
counts are test evidence, not production constants. Federal budget is conserved
inside the ready subset; an explicit local geo outside it blocks validation before
job creation. D1R5 live acceptance passed a full federal 100 million RUB job with
211 declared, 175 ready and 36 period-excluded geographies, exact budget
reconciliation, 175 map points, result, expanded media plan and report. Four mixed
federal/local cases passed with exactly one grouped warning and job creation
allowed; `РФ + Якутск` blocked before job creation. The accepted parser and
allocation/forecast contracts were unchanged by the later test-only harness fixes.

- Canonical catalog: `04_Web_app/data/geo_catalog/geo_catalog_v1.csv` plus explicit
  aliases.
- Catalog version: `geo_catalog_v1_2026_07_18`, based on a GeoNames RU snapshot,
  WGS84, CC BY 4.0.
- Verified coverage: 220 catalog geographies, 220 complete unique coordinate
  pairs, 402 explicit unique aliases.
- Active turnover serving guard requires 220/220 coverage and fails closed.
- No runtime geocoding, fuzzy match, nearest-neighbour guess or external map API.
  Unknown/ambiguous geo retains budget and null coordinates.
- Frontend uses a bundled Natural Earth outline and a fixed Albers projection.

## Home map

- Source: `GET /api/v1/model/historical-geo-budget` only.
- It shows historical model-panel advertising budget, not current workspace uploads.
- Verified artifact total: **8,687,024,294.654741 RUB** across 220 geographies,
  220/220 located, zero unlocated budget.
- Period: 2025-01-01–2026-05-31.
- Artifact SHA-256:
  `b21266954f27b3f677e5262cb43c7ef7ee02269585d3e5bae9efd762db1de249`.
- Spend source combines six media columns: `Digital_Performance`, `OOH_Total`,
  `Indoor`, `Радио`, `Нац_ТВ`, `Рег_ТВ`.
- `active_days` remains in backend artifact/contract metadata, but the frontend
  tooltip intentionally does not display it after PR #35.

`GET /api/v1/workspace/geo-budget` still serves calculation-history context; it is
not the Home-map source.

## Campaign map

New Calculation uses the uploaded plan after validation:

- geo points come from `validation.geo_points`;
- budget is the current campaign-plan budget;
- unknown geo is preserved and reported rather than guessed.

Historical Home budget and uploaded campaign budget are different populations and
must not be mixed in one semantic layer.

## Auth

- Local pilot identity provider with Argon2id password hashes.
- Opaque server-side sessions; HttpOnly, SameSite=Lax cookie; Secure in research
  profile; HMAC session digest in SQLite.
- CSRF Origin/Host checks and no-cache auth/admin responses.
- Roles: `viewer`, `analyst`, `admin`; route and handler enforcement uses central
  permissions rather than role-name shortcuts.
- Login, session, logout and self-registration are implemented. Registration
  accepts any email domain, assigns `analyst`, opens a session, rate-limits attempts
  and uses non-enumerating duplicate responses.
- Admin surfaces cover users, enable/disable, session revoke, roles, system status
  and audit log.
- Corporate SSO, MFA and password recovery are not implemented.
- Auth state is local single-node SQLite, not a multi-node identity platform.

## Reports

- Business KPI source: v2 `result-view-v2` and `media-plan-v2` contracts.
- Canonical marketer Excel report is hash-verified and downloadable through an
  opaque artifact endpoint with `report.download` permission.
- The Report tab calls legacy `result-view` only to obtain narrow report-artifact
  transport metadata. It is not a fallback for business KPI semantics.
- Media-plan table is v2 geo x channel total. A daily media plan is unavailable.
- A separate working media-plan XLSX is normally unavailable unless a real artifact
  was produced; the technical allocation CSV is evidence, not automatically a
  public marketer download.

## Portal pages

Actual frontend routes:

- `/login`;
- `/` — Home with historical map;
- `/calculations` — calculation history;
- `/calculations/new` — upload and validation states;
- `/calculations/:id/progress`;
- `/calculations/:id/result` with tabs **Overview**, **Scenarios & reliability**,
  **Media plan**, **Report**;
- `/model` and `/help`;
- `/admin/users`, `/admin/roles`, `/admin/system`, `/admin/audit`.

There are no separate top-level Validation, Media Plan or Report routes. Protected
routes use session and permission gates.

## Known limitations

1. Model is `preprod_restricted`; sealed OOT gate blocks production activation.
2. Product is `allocation_only`; no approved finance launch/cancel hurdle exists.
3. No corporate SSO/MFA/password recovery; auth and job state are local/single-node.
4. No Postgres, durable distributed queue, object storage or multi-node failover.
5. JupyterHub resource limits are not documented as enforced.
6. The two C0 HTTP `409` test-isolation failures were resolved in PR #37. C2.3R
   recorded 168 passing web tests and 10 expected skips; C2.3S reconfirmed the
   post-merge regression state.
7. No daily media plan and no generally available separate working media-plan XLSX.
8. Live server health, release identity and product acceptance passed in D1R5.
   This does not change the model production gate.
9. The `x5-mmm-retention.service` last observed invocation was already failed
   before the D1R5 switch, while its timer remained active/waiting. Its cause was
   not inspected in this deployment and belongs in observation, not in a runtime
   release hotfix.
10. `PROJECT_BRIEF.md`, `OPEN_DECISIONS.md`, onboarding and older DevOps notes retain
    stale deployment/map wording outside the three-file C0 edit scope.
11. Application Git and model/data artifacts have separate lineage and transfer
    paths; both must be verified for a reproducible release.
12. Historical/research files retain inventoried absolute-path debt; canonical
    operational blockers are zero, but archived entrypoints may need explicit
    rehabilitation before reuse.
13. Corporate governance of the private GitHub repository and branch protection
    remains unresolved.
14. The static dictionary intentionally shows declared package support, while
    actual calculability is date-dependent and is resolved during validation.
    Consumer code must not treat `211 / 220 / 114 / 117` as ready counts.

## Current milestone

**D1R5 — FEDERAL_FEATURE_DEPLOYED; observation active.**

The accepted federal functionality is live through deploy5. Full federal,
mixed-validation, blocking-geo and ordinary-regression acceptance passed. The
application release is deployed, while model status remains
`preprod_restricted / production_gate=not_passed`. Cleanup is not authorized.

## Planned milestones

1. **D1R5 observation.** Monitor real user validations, jobs, reports, service
   health and the pre-existing retention-service failure without changing release
   identity or starting cleanup.
2. **A — Historical Campaign Evaluation.** Future causal/research capability, not
   implemented. Preliminary estimand: marginal incremental turnover of one selected
   historical campaign while concurrent observed media remains factual. This
   estimand requires explicit assumptions, identification design and validation
   before productization.
3. **Model production gate.** A separate future milestone for sealed OOT evidence
   and explicit activation decision.
4. **C3 cleanup.** Not authorized until the observation cycle completes and a
   separate destructive-action review approves exact targets.
