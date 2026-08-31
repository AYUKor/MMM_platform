# MMM Platform — Current Truth

## Last verified

- Verification date: **2026-08-31**.
- Mode: **C0 — VERIFICATION + DOCUMENTATION ONLY**.
- Verified against local live code, Git/GitHub state, contracts, policies,
  manifests, tests, physically present artifacts and local deployment runbooks.
- No DWH query, model/data recalculation, server connection or deployment was
  performed.
- Server facts below are explicitly labelled as documented status; they were not
  live-verified during C0.

## Product status

MMM Platform is an internal research-pilot web application for uploading campaign
plans, validating geo/channel inputs, calculating posterior-based incremental
turnover scenarios, reviewing uncertainty and downloading a canonical report.

The application and portal are implemented. The active model package is **not a
production model**: it is `preprod_restricted` because sealed OOT validation is
missing or failed. The product is therefore decision support under explicit risk
limits, not an automated media-buying or finance approval system.

## Repository

- Released application repository:
  `/Users/aleksan.korenkov/Work/01_ML_projects/03_ML_MMM/05_MMM_localapp`.
- Remote: `https://github.com/AYUKor/MMM_platform.git`.
- `origin/main` is the source of truth for released application code.
- Data, research outputs, project brain and server-deploy evidence also exist in
  the parent `03_ML_MMM/` workspace and are not all stored in this Git clone.
- Pre-existing untracked `05_Presentations/` was found in the clone during C0 and
  deliberately left untouched.

## Current Git state

- Verified baseline: local `main` and remote `origin/main` both pointed to
  `2ead610a56ab26eb38aeb29210d1bab86251f856` on 2026-08-31.
- Latest verified merged release PR: **#35**, hiding the low-information active-days
  metric in the historical Home-map tooltip.
- C0 documentation work is isolated in branch
  `codex/c0-current-truth-freeze`; its commit SHA is intentionally not embedded in
  this document because Git history is the authoritative record.
- Several older temporary worktrees are present/prunable outside this clone. They
  are not evidence of the current release and were not modified.

## Deployment

The accepted deployment flow is:

`accepted local code -> GitHub main -> same-origin frontend build -> offline Git
bundle transfer -> corporate server Git -> static dist replacement -> backend/UI
health and hash checks`.

- Frontend production build uses `VITE_API_BASE_URL=""` and same-origin `/api`.
- The corporate server is documented as having no outbound GitHub access; offline
  Git bundles are therefore the intended application-code transfer mechanism.
- The panel-free model serving package is transferred and hash-verified separately
  from application Git.
- `server-deploy/deploy-frontend-pr35.sh` is a release-specific script, not a
  complete reusable transfer pipeline: it assumes the required bundle/remote state
  is already available. Local bundle snapshots inspected during C0 do not by
  themselves prove a fresh PR #35 transfer. This deployment evidence gap remains.

## Server status

**Documented operational status, last accepted 2026-07-23; not live-verified in
C0:**

- Primary product URL: `https://mmm.x5.ru`.
- Reserved fallback name: `mmm.x5.internal`.
- Nginx terminates HTTPS and serves the frontend; backend systemd service
  `x5-mmm-backend` listens on loopback `127.0.0.1:8765`.
- JupyterHub is exposed by the same nginx under `/hub/` and listens on loopback.
- Documented acceptance included browser calculation flow, exact reconciliation,
  health checks, backups and retention timers.

Local onboarding and historical DevOps documents still contain stale `.internal`,
manual-hosts, CA, firewall or certificate wording. Current runbook evidence makes
`.ru` the primary documented URL, but employee reachability was not independently
checked on 2026-08-31.

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

`/Users/aleksan.korenkov/Work/01_ML_projects/03_ML_MMM/00_Data/02_2025_2026Q1_second_pass/panel_final_v3.parquet`.

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
6. Two targeted HTTP tests were reconfirmed failing with `409` on 2026-08-31:
   workspace home in `AuthAdminHttpTest.test_central_permissions_distinguish_401_and_403`
   and model overview-v2 in
   `HttpSmokeV1Test.test_product_metadata_readiness_schemas_and_job_query`.
7. No daily media plan and no generally available separate working media-plan XLSX.
8. Server live health/reachability and deployed HEAD were not checked in C0.
9. Offline transfer is the accepted flow, but release-specific scripts/bundle
   snapshots do not form a fully self-contained reusable deployment pipeline.
10. `PROJECT_BRIEF.md`, `OPEN_DECISIONS.md`, onboarding and older DevOps notes retain
    stale deployment/map wording outside the three-file C0 edit scope.
11. Application Git and model/data artifacts have separate lineage and transfer
    paths; both must be verified for a reproducible release.
12. Local workspace contains duplicated/historical structures and stale worktrees;
    no item may be removed based on name or age alone.
13. Corporate governance of the private GitHub repository and branch protection
    remains unresolved.

## Current milestone

**C0 — MMM Platform Current Truth Freeze.**

Deliverable: verified documentation only. No application, model, data, deployment
or server mutation belongs to C0. After Draft PR creation, work stops for review.

## Planned milestones

These are recorded plans, not implemented functionality:

1. **C1 — Local Workspace Read-Only Audit.** Inventory and dependency map of the
   parent `03_ML_MMM/` workspace. No move, rename or deletion. The proposed target
   structure `03_ML_MMM/{00_Data,01_Test,02_Predfin,03_Fin}` must not be created
   during the audit.
2. **B1 — Federal Geo Allocation Audit.** Investigate how the current training and
   serving transforms handle geo before designing support for uploaded `geo=РФ`.
   Pre-expansion and reconciliation must be evidence-based. A mean-population
   fallback is a future requirement to validate, not current behavior.
3. **A — Historical Campaign Evaluation.** Future causal/research capability, not
   implemented. Preliminary estimand: marginal incremental turnover of one selected
   historical campaign while concurrent observed media remains factual. This
   estimand requires explicit assumptions, identification design and validation
   before productization.
