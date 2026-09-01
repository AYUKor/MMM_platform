# MMM Platform — Project Handoff

## 1. Purpose of this document

This handoff is the operational entry point for a new agent or engineer who must
continue MMM Platform work without relying on old chats. It explains why the
system exists, how its current pieces fit together, which design decisions are
intentional, where the evidence lives and what is still unresolved.

For a terse statement of facts as of 2026-09-02, read `CURRENT_TRUTH.md`. This
document adds architecture, decision history and continuation rules; it should not
be treated as stronger evidence than live code, contracts, Git or verified
artifacts.

## 2. Project purpose and business problem

MMM Platform turns an uploaded media plan into a transparent decision-support
result for marketers:

1. validate dates, channels, geographies and budget;
2. reconcile the uploaded plan to the model's supported decision space;
3. evaluate the factual plan and approved allocation scenarios;
4. expose posterior uncertainty, risk/support violations and unallocated budget;
5. provide a geo x channel plan and a reproducible Excel report.

The business question is not “what will total sales be?” The active result is:
“what incremental turnover does the model associate with this media allocation,
relative to a no-campaign media counterfactual, and how reliable is the allocation
inside the observed support?”

The platform is intentionally a research pilot. It supports human decisions; it
does not automatically launch campaigns, approve finance, prove universal
causality or replace an experimental holdout.

## 3. Where to start

Read in this order:

1. `AGENTS.md` — safety and working rules.
2. `04_Web_app/PROJECT_BRIEF.md` — stable product intent; note that some deployment
   wording is historical.
3. `04_Web_app/CURRENT_TRUTH.md` — verified current snapshot.
4. This `PROJECT_HANDOFF.md`.
5. Relevant accepted ADRs in `04_Web_app/docs/adr/`.
6. Live schemas/contracts, policies, pointers/manifests, implementation and tests.
7. Canonical project brain for decision history:
   `<MMM_WORKSPACE_ROOT>/01_Test/project_brain/wiki/`.
8. Workspace lifecycle, promotion and observation contracts in
   `04_Web_app/docs/workspace/`.

For current factual claims use this priority:

`live code/contracts/manifests/artifacts -> Git -> deployment/runbook evidence ->
CURRENT_TRUTH -> PROJECT_HANDOFF -> narrative handoffs -> old phase docs`.

If an accepted ADR and implementation disagree, record both: the ADR is approved
intent, while code is implemented behavior. Do not silently reinterpret either.

## 4. Workspace map

Canonical root verified during C2.6:

`<MMM_WORKSPACE_ROOT>`

- `00_Data/` — immutable/versioned data contour.
- `01_Test/` — research, experiments, project brain and the canonical
  application development checkout `MMM_platform/`.
- `02_Predfin/` — exact candidate checkout, physical model closure and
  immutable acceptance evidence.
- `03_Fin/` — versioned immutable releases and verified transfer
  artifacts.
- `01_Test/research/legacy_reference/server-deploy/` — preserved copy of
  the existing server runbook/evidence; do not copy infrastructure secrets or
  sensitive details into Git.

The old workspace is preserved at `<MMM_LEGACY_ROOT>` with role
`LEGACY_ROLLBACK_ONLY`; it is not an operational fallback. A remaining local copy
outside `<MMM_WORKSPACE_ROOT>` is migration staging, not canonical. Historical path
debt is inventoried and does not authorize cleanup or imply that archived
entrypoints are canonical.

## 5. End-to-end architecture

```text
campaign upload
  -> parsing and canonical validation
  -> geo alias normalization, federal expansion and support checks
  -> workspace + immutable input/artifact lineage
  -> background execution worker
  -> turnover-only forecast adapter
  -> S1-S6 scenario and risk policy
  -> DecisionResult / v2 result contracts
  -> same-origin HTTP API
  -> protected React portal
  -> canonical marketer Excel artifact
```

The browser never reads a model posterior directly. Product adapters and contracts
separate research artifacts from serving semantics. The worker owns the transition
from accepted upload to completed/failed calculation; the UI reads lifecycle,
progress and result views rather than recomputing KPIs.

Application release and model release are separate lineages:

```text
application: Test branch -> reviewed PR -> GitHub main -> Predfin -> Fin
model: Test candidate -> Predfin closure/acceptance -> Fin panel-free transfer
deployment: verified Fin artifact -> separately authorized server update
```

The source parquet remains outside the server serving bundle.

Federal upload semantics are versioned separately as
`FEDERAL_GEO_ALLOCATION_V1`. The allocator expands each federal daily source row
to canonical model geographies before forecast; durable audit/provenance artifacts
preserve source-row lineage. B2.2 exposes only a safe aggregate projection to the
browser and adds an active-package dictionary. See
`docs/integration/FEDERAL_GEO_ALLOCATION_V1.md` and
`docs/integration/B2_2_FEDERAL_CAMPAIGN_UX_V1.md`.

## 6. Model methodology

### 6.1 Research package

The active preproduction pointer resolves to package
`pkg_807d3ddbae57a52a_9aacd3beb350725b` with fingerprint
`807d3ddbae57a52ad184f94cd5442cdefd97764fe3903e5b250b5d04cd26c62c`.

The research package contains 12 posterior fits:

- segments: `ТС5/Онлайн`, `ТС5/Оффлайн`, `ТСХ/Онлайн`, `ТСХ/Оффлайн`;
- targets: `turnover_per_user`, `orders_per_user`, `avg_basket`.

The model package preserves posterior distributions and diagnostics. Media
transforms include the package's approved carryover/adstock and saturation logic;
serving must consume those artifacts and policies, not refit or approximate them in
the web layer.

Historical replay and diagnostics are evidence of internal consistency, not a
substitute for a sealed future-period test. The package is therefore
`posterior_ready` but `preprod_restricted`, blocked by
`MISSING_OR_FAILED_OOT_VALIDATION`. No production pointer exists.

### 6.2 Estimand and interpretation

For a candidate media plan, the forecast compares posterior media response under
that campaign with a no-campaign media counterfactual. The output is incremental
turnover attributable to the modeled media response under model assumptions.

Interpretation boundaries:

- this is incremental media effect, not full turnover;
- posterior uncertainty describes model uncertainty, not every business risk;
- observational MMM can retain confounding and specification risk;
- support risk matters: extrapolation outside observed spend is not repaired by a
  narrow posterior interval;
- ROAS is only interpretable with its explicit budget denominator.

### 6.3 Research versus serving

Only the four `turnover_per_user` segment fits are active in application serving.
Orders and average-basket posteriors remain research/package evidence. They are not
combined into user-facing bridge KPIs and do not participate in the current
recommendation policy.

The serving boundary is fail-closed:

- expected research package: exactly 12 fits;
- allowed active serving set: exactly 4 turnover fits;
- public target: `turnover`;
- package/policy mismatch blocks serving instead of silently degrading.

Key evidence:

- `03_Outputs/01_PyMC_outputs/00_Model_registry/channels/preprod.json`;
- active package manifest and run config under `03_Outputs/01_PyMC_outputs/`;
- `02_Code/02_Budget_optimizer/optimizer_decision_policy_v3.yaml`;
- `04_Web_app/services/business_semantics_v2.py`;
- `04_Web_app/services/local_campaign_service.py`;
- v2 schemas and model-passport tests.

## 7. Source data and lineage

Canonical panel physically verified in the data contour:

`<MMM_WORKSPACE_ROOT>/00_Data/panels/02_2025_2026Q1_second_pass/panel_final_v3.parquet`.

Metadata reverified during C2.5 operational smoke:

- SHA-256:
  `9aacd3beb350725be483145bf955dbc26f9b5dd7a510708c4ae4ec700e4b4552`;
- 308,886 rows;
- 109 columns;
- 220 unique model geographies;
- panel dates 2025-01-01–2026-05-31;
- training dates 2025-01-01–2026-03-20;
- development shadow/holdout 2026-03-21–2026-05-31.

This date distinction resolved a recurring documentation error: the source panel
continues through May, but the training window stops in March. Always read the run
manifest/config before describing a “training period”.

The application clone alone is not a complete reproducibility package. The
four-contour workflow supplies data, model closure and acceptance outside Git.
Model deployment must retain panel hash and package lineage without copying the raw
panel to the server.

## 8. Upload, validation and calculation lifecycle

The portal accepts a campaign/media-plan input, creates a workspace, validates the
canonical rows and only then permits execution. Validation owns:

- required columns and parsable values;
- supported dates/channels;
- explicit geo alias resolution;
- budget reconciliation;
- geo points for the campaign preview;
- warnings or blocking issues.

Unknown or ambiguous geo is never silently assigned to a nearby location. Its
budget remains visible and the coordinates remain null until a valid mapping is
available.

Calculation lifecycle and progress are represented by versioned contracts. A
background worker executes the accepted job and records artifacts/state. Result
adapters expose contract-safe views; the frontend does not infer success merely
from the existence of a file.

Important implementation/evidence areas:

- `04_Web_app/contracts/application_lifecycle_v1.*`;
- `04_Web_app/worker/execution_worker.py`;
- `04_Web_app/services/local_campaign_service.py`;
- `04_Web_app/services/job_progress_view.py`;
- lifecycle, worker, local-service and HTTP smoke tests.

## 9. Scenarios and optimizer

### 9.1 Public scenarios

- **S1 Uploaded plan**: factual/reference benchmark. The system keeps the uploaded
  plan and requires human review; S1 is never an automatic “optimized” answer.
- **S2 Equal cells**: equal allocation across eligible geo x channel cells.
- **S3 Equal geographies within channel totals**: preserves channel totals while
  equalizing eligible geographies.
- **S4 Equal channels within geography totals**: preserves geography totals while
  equalizing eligible channels.
- **S5 Conservative**: one public scenario with internal support-expansion search.
- **S6 Adaptive/effect-first**: posterior marginal-effect allocation subject to
  approved support/risk constraints.

### 9.2 S5 contract

S5 tests increasingly permissive approved support levels — p95, p99, then robust
upper — and internal projection modes. Internal candidates are implementation
details; the public scenario has only these meaningful outcomes:

- `full_conservative`: full requested budget allocated with no high-risk cells;
- `safe_partial`: only after every approved full-budget option is infeasible;
  reports allocated and unallocated budget, limiting constraints and manual-review
  status.

`fixed_at_plan` cannot bypass a support cap. A partial S5 is never auto-recommended.

### 9.3 S6 contract

S6 searches for higher posterior incremental effect inside p99/robust-upper risk
limits. To claim `full_effect_maximizing`, it must allocate the full requested
budget and reconcile unallocated budget to zero. Otherwise the scenario is
explicitly `infeasible`, with null business metrics. It must not return a partial
plan under a maximum-effect label.

“Effect maximizing” is a policy/heuristic description inside the approved search
space; the system does not claim a global mathematical optimum.

### 9.4 Recommendation policy

Recommendation is separate from scenario generation. A candidate must be complete,
policy-safe and materially better under the configured rules. If no candidate
meets that standard, S1 remains the decision reference. Human review is mandatory
for uploaded and partial/unsafe outcomes.

Canonical decision evidence is the optimizer policy YAML, scenario enums/contracts,
accepted scenario ADR and tests. Do not restore older scenario logic from phase
notes.

## 10. Result and contract semantics

The primary product contract is turnover-only v2. It exposes:

- incremental turnover `p10`, `p50`, `p90`;
- ROAS and its requested/allocated denominator;
- requested, allocated and unallocated budgets;
- allocation share and reconciliation;
- risk composition, uncertainty and warnings;
- scenario comparison and geo x channel media plan.

Orders, average basket, orders per 100k and average-basket bridges were removed from
active product semantics. Research artifacts must not be converted back into these
KPIs in the frontend.

Key contract areas:

- `04_Web_app/contracts/business_semantics_v2.py`;
- `04_Web_app/contracts/job_result_view_v2.schema.json`;
- `04_Web_app/contracts/scenario_media_plan_v2.schema.json`;
- `04_Web_app/contracts/model_passport_v2.schema.json`;
- `04_Web_app/contracts/openapi_v1.json`;
- `04_Web_app/services/business_semantics_v2.py`;
- result/business-semantic contract tests.

Legacy v1 views remain for compatibility and narrow artifact transport. They are
not an allowed fallback for v2 business KPIs.

## 11. Geo architecture and maps

### 11.1 Canonical geo policy

The catalog in `04_Web_app/data/geo_catalog/` contains 220 canonical geographies,
all with WGS84 coordinates, plus 402 explicit aliases. Its version is
`geo_catalog_v1_2026_07_18`; source attribution is a GeoNames RU snapshot under CC
BY 4.0.

Normalization is explicit. There is no runtime geocoder, fuzzy matching, external
map API or nearest-point guess. The active turnover-serving guard requires full
220/220 coverage and fails closed.

The frontend renders points over a locally bundled Natural Earth outline with a
fixed Albers projection. Coordinates describe canonical points, not administrative
polygon membership.

### 11.2 Historical Home map

Home calls `GET /api/v1/model/historical-geo-budget`. The source artifact aggregates
six spend fields from the model panel and records:

- 8,687,024,294.654741 RUB total historical spend;
- period 2025-01-01–2026-05-31;
- 220 canonical geographies;
- 220/220 located and zero unlocated budget;
- artifact SHA-256
  `b21266954f27b3f677e5262cb43c7ef7ee02269585d3e5bae9efd762db1de249`.

`active_days` remains backend artifact metadata, but PR #35 deliberately removed it
from the tooltip because it had low decision value. Do not re-add it based on old
screenshots or docs.

The older workspace endpoint `GET /api/v1/workspace/geo-budget` remains valid for
calculation-history context. It is not the Home-map source and must not be used as a
fallback there.

### 11.3 Campaign map

New Calculation receives `validation.geo_points` and displays the currently
uploaded media-plan budget. This is an upload-validation view, not historical model
spend. The two maps have different populations, periods and decisions and must stay
semantically separate.

## 12. Web portal

The current React portal has these route-level surfaces:

- `/login`;
- `/` Home;
- `/calculations` calculation history;
- `/calculations/new` upload plus validation states;
- `/calculations/:id/progress`;
- `/calculations/:id/result` with Overview, Scenarios & reliability, Media plan and
  Report tabs;
- `/model`;
- `/help`;
- `/admin/users`, `/admin/roles`, `/admin/system`, `/admin/audit`.

Validation is a state of New Calculation. Media Plan and Report are result tabs,
not independent top-level routes. Route guards require a session and the relevant
permission.

Frontend code under `04_Web_app/frontend/src/`, its router, API client and E2E tests
are the authority for actual navigation. Phase plans and design inventories are not
proof that a page exists.

## 13. Authentication and administration

The research-pilot auth boundary uses:

- local identity provider;
- Argon2id password hashing;
- opaque server-side sessions;
- HttpOnly SameSite=Lax cookie, Secure in research profile;
- HMAC session digest in SQLite;
- Origin/Host CSRF enforcement;
- no-cache auth/admin responses;
- central permissions for handlers and protected routes.

Roles are `viewer`, `analyst`, `admin`. Implemented flows include login, session,
logout and self-registration. Registration accepts any email domain, assigns the
analyst role, creates a session, shares rate limiting and avoids account enumeration
on duplicate input.

Admin contracts/endpoints cover user list/detail/create/update, enable/disable,
session revoke, role catalog, system status and audit log.

This is not corporate identity integration. Corporate SSO, MFA and password
recovery are absent. SQLite/session/file state is appropriate only for the current
single-node research-pilot boundary.

JupyterHub authentication is a separate operational boundary using its documented
local user/authenticator flow. Portal roles do not automatically govern notebook
access.

## 14. Reports and downloads

Business values in the UI come from v2 result and media-plan contracts. The
canonical marketer Excel report is produced as a real artifact, recorded with hash
metadata and served through an opaque download endpoint guarded by
`report.download`.

The Report tab may call legacy `result-view` only to discover report artifact
transport metadata. Contract tests intentionally prevent use of that legacy view as
a fallback for KPI semantics.

Current output boundary:

- canonical marketer report XLSX: available when the job produced and registered
  the artifact;
- on-screen v2 geo x channel media-plan table: available;
- separate working media-plan XLSX: normally unavailable unless a real artifact is
  present;
- daily media plan: unavailable;
- technical allocation CSV: reproducibility evidence, not automatically a public
  marketer deliverable.

Never create a download link for a path that has not been materialized, registered
and permission-checked.

## 15. Deployment and server workflow

### 15.1 Documented topology

Last accepted operational documentation is dated 2026-07-23. It records:

- primary URL `https://mmm.x5.ru`, with `.internal` reserved as fallback;
- nginx HTTPS/static frontend and same-origin reverse proxy;
- `x5-mmm-backend` systemd service under an unprivileged account, listening on
  loopback `127.0.0.1:8765`;
- JupyterHub behind the same nginx under `/hub/`, listening on loopback;
- health, backup and retention services/timers;
- separate application, auth/runtime state and artifact locations.

C0 did not connect to the server. Treat all of the above as **documented
operational**, not **live verified on 2026-08-31**.

### 15.2 Application release flow

The intended release sequence is:

1. accept code locally and merge the reviewed PR into GitHub `main`;
2. build frontend with an empty API base for same-origin requests;
3. create an offline Git transfer from the accepted `main` state;
4. transfer through the approved corporate route;
5. update server Git under the service account;
6. replace the verified frontend `dist`;
7. restart only the explicitly approved services;
8. check backend health, browser flow, artifact hashes and reconciliation.

Application code and model package are different deployables. The model transfer
must verify its pointer, manifest, package fingerprint and panel lineage while
remaining panel-free.

### 15.3 Evidence caveat

The current runbook documents an offline-bundle process, and the narrative handoff
states that it was used through PR #35. However, the inspected PR #35 helper script
assumes a prepared remote/bundle and does not itself create or upload one; inspected
local bundle snapshots do not independently establish a complete fresh PR #35
transfer. Therefore:

- accepted topology and offline flow: documented;
- exact currently deployed HEAD: not live verified in C0;
- fully reusable self-contained transfer automation: incomplete/requires audit.

Do not “fix” this by connecting to or changing the server in an unrelated task.

### 15.4 Stale deployment documents

Some onboarding/bootstrap material still treats `.internal`, manual hosts/CA or
basic auth as current, while newer runbooks document `.ru`, corporate TLS and portal
auth. `PROJECT_BRIEF.md` and `OPEN_DECISIONS.md` also retain pre-deployment or
pre-map statements. These files were outside the three-file C0 scope. Consult the
latest runbook plus live code and mark discrepancies rather than copying them.

## 16. Important decisions that must be preserved

1. **Turnover-only serving.** Twelve research fits remain, but only four turnover
   fits drive application forecasts and optimizer decisions.
2. **Restricted status is explicit.** No sealed OOT means no production claim.
3. **Incremental, not full turnover.** The product reports modeled incremental media
   contribution versus a no-campaign counterfactual.
4. **One public S5.** Internal support variants do not become multiple confusing
   user scenarios.
5. **No partial maximum-effect S6.** Full budget or explicit infeasible status.
6. **Recommendation is policy-gated.** Scenario generation alone is not a business
   recommendation.
7. **Explicit geo normalization.** No fuzzy/runtime guessing; unknown budget is
   preserved.
8. **Historical Home source.** Home shows model-panel historical media spend, not
   the sum of application forecast campaigns.
9. **Maps are separate.** Home history and current-upload validation have different
   semantics.
10. **v2 owns KPI semantics.** Legacy v1 is allowed only for narrow compatibility or
    artifact transport.
11. **Local pilot auth is honest.** Do not describe it as corporate SSO.
12. **Offline app release and separate model package.** Never mix Git release with
    raw-panel transfer.
13. **No live-server inference from docs.** “Documented operational” and “verified
    live” are different epistemic states.

## 17. Rejected or superseded approaches

Do not restore these without a new approved decision:

- exposing all 12 research fits as 12 serving models;
- reconstructing orders/basket bridge KPIs in the product;
- Home map based on workspace forecast totals;
- workspace endpoint fallback for Home;
- fuzzy geo match, nearest-point assignment or runtime external geocoding;
- allowing `fixed_at_plan` to bypass support caps;
- returning partial S6 under an effect-maximizing label;
- auto-recommending partial S5;
- treating legacy v1 result view as a business-semantic fallback;
- presenting Validation, Media Plan or Report as standalone routes;
- describing `.internal`/manual-hosts bootstrap as the primary current user path;
- treating the old basic-auth bootstrap as the current portal auth architecture;
- copying the source panel into the serving package;
- declaring a local directory obsolete from its name or date.

## 18. Known limitations and technical debt

### Model and decision quality

- sealed OOT gate blocks production activation;
- observational/specification and support-extrapolation risk remains;
- product is allocation-only and lacks an approved finance launch/cancel threshold;
- federal upload is implemented in the Test B2.2 candidate but has not yet passed
  acceptance: `ТСХ/Онлайн` completes the no-interception result/report path, but
  `ТС5/Онлайн` fails because Yakutsk has one denominator date and cannot cover the
  mandatory carryover horizon;
- no historical campaign evaluation capability.

### Product/runtime

- no corporate SSO, MFA or password recovery;
- local SQLite/file state, no Postgres, distributed durable queue, object storage or
  multi-node failover;
- no daily plan and normally no separate working media-plan XLSX;
- the two historical C0 HTTP `409` test-isolation failures were resolved in PR #37;
  C2.3S recorded 168 passing web tests with 10 expected skips;
- JupyterHub resource limits are not documented as enforced.

### Release/operations

- live server health and exact deployed HEAD were not checked in C0;
- transfer runbook, one-off script and bundle snapshots are not fully reconciled;
- model package extension/transfer must accompany application deployment when model
  lineage changes;
- some onboarding/governance docs are stale;
- private GitHub governance and branch protection remain unresolved;
- server-side app code readability by other local users is a documented hardening
  concern for later review.

### Workspace

- canonical workflow now spans four explicit contours under `<MMM_WORKSPACE_ROOT>`
  rather than one Git clone;
- historical/research files retain inventoried absolute-path debt, but operational
  runtime blockers are zero;
- historical worktrees and legacy copies remain protected until a later cleanup
  decision;
- a missing artifact inside Git may be intentionally external, not lost.

## 19. Canonical local workspace lifecycle

C2 migration and physical-root switch are complete through C2.6:

```text
<MMM_WORKSPACE_ROOT>/
├── 00_Data/    # canonical data contour
├── 01_Test/    # canonical development/research contour
├── 02_Predfin/ # exact staging and acceptance contour
└── 03_Fin/     # immutable deployable releases
```

Current release is
`release_2a6e07755f0d_807d3ddbae57_ed8a6c6c7642`. The application is approved;
the model remains `preprod_restricted` with `production_gate = not_passed`.

Development starts in Test, candidate acceptance occurs in Predfin, and each Fin
change creates a new `releases/<release_id>` directory. `CURRENT_RELEASE.json` may
switch only after PASS. The exact contracts are under
`04_Web_app/docs/workspace/`.

C3 cleanup is not authorized. The observation period must include one real B1/B2
Federal Geo Allocation cycle through all four contours and a new Fin release.

## 20. Federal geo allocation

B1, B2.0 and B2.1 established and implemented
`FEDERAL_GEO_ALLOCATION_V1`. Approved aliases are `РФ`, `Россия` and
`Российская Федерация`, with outer-whitespace trimming and case-insensitive
matching only. Each federal daily source row expands independently and only then
aggregates to the existing forecast grain. Weights use the pinned population over
the active package's eligible direction geographies. Missing population blocks the
plan; a mean fallback is not current policy.

B2.2 adds the completed Test-contour product path: an additive browser-safe
`federal_allocation` projection derived from the durable audit, an active-package
dictionary endpoint, federal validation/mixed/error UI and unchanged handoff of
canonical geo rows to campaign map, calculation, result, media plan and report.
See `docs/integration/B2_2_FEDERAL_CAMPAIGN_UX_V1.md`.

Acceptance is not complete. A real active-package job succeeds end-to-end for
`ТСХ/Онлайн` (114 geo). `ТС5/Онлайн` expands to 211 geo, but Yakutsk has only the
`2026-01-01` denominator row; forecast carryover requires dates through
`end_date + l_max` and correctly fails closed. Do not solve this by silently
dropping a geography or enabling a new fallback. It requires a separately approved
model/package-data or federal support-universe decision.

## 21. Historical campaign evaluation — future requirement

Agency data can contain campaign id, daily dates/start/end, geography, channel,
spend and additional media metadata. The current platform does not estimate a
historical campaign's separate causal effect.

Preliminary research estimand:

> marginal incremental turnover of one selected historical campaign while other
> concurrent observed media remains factual.

This is not identified merely by filtering the panel. A future methodology must
define campaign exposure, population, grain, counterfactual, overlap with concurrent
media, carryover, seasonality, selection/confounding, pre-period and uncertainty.
It must also distinguish causal evidence from a model-based attribution proxy.

No code, UI or result claim should be created until this estimand and validation
design are approved.

## 22. Next milestones

1. **B2.2 review and post-merge Predfin acceptance** — use the exact reviewed
   commit and workspace promotion gates; Codex must not merge the PR.
2. **B2.3 or later federal work** — do not start without a separate task.
3. **A — Historical Campaign Evaluation methodology** — establish identification
   and validation before product work.
4. **Model production gate** — separate future milestone for sealed OOT evidence and
   activation decision.
5. **Deployment milestone** — use only a verified Fin transfer artifact and do not
   change the server unless explicitly authorized.
6. **C3 cleanup review** — only after a successful observation release; exact
   destructive targets still require separate approval.

Do not start any of these automatically after C2.6.

## 23. Verification references and safe commands

Useful read-only Git checks from the application clone:

```bash
git rev-parse --show-toplevel
git status --short --branch
git rev-parse HEAD
git remote -v
git worktree list --porcelain
git log --oneline --decorate -n 20
git diff -- AGENTS.md 04_Web_app/CURRENT_TRUTH.md 04_Web_app/PROJECT_HANDOFF.md
```

Useful evidence locations:

- model pointer/package: `03_Outputs/01_PyMC_outputs/00_Model_registry/` and the
  pointed package/run manifest;
- optimizer/recommendation: `02_Code/02_Budget_optimizer/`;
- forecast semantics: `02_Code/03_AC_forecast/README.md`;
- business/geo/auth/result contracts: `04_Web_app/contracts/` and
  `04_Web_app/services/`;
- frontend routes and API use: `04_Web_app/frontend/src/`;
- historical geo artifact in the accepted model closure under
  `03_Outputs/01_PyMC_outputs/00_Model_registry/package_artifacts/`
  under the active package's `historical_geo_budget_v1/` extension;
- application tests: `04_Web_app/tests/` and frontend E2E tests;
- repository deployment: `04_Web_app/deployment/`;
- latest preserved operational evidence:
  `<MMM_WORKSPACE_ROOT>/01_Test/research/legacy_reference/server-deploy/`.
- workspace workflow and promotion gates: `04_Web_app/docs/workspace/`.

Safe artifact verification examples:

```bash
shasum -a 256 <MMM_WORKSPACE_ROOT>/00_Data/panels/02_2025_2026Q1_second_pass/panel_final_v3.parquet
git bundle verify <existing-bundle-path>
```

Do not run DWH queries, training, MCMC, forecast regeneration, deploy, SSH or service
commands merely to refresh documentation.

The two known failing tests were reconfirmed with:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest \
  04_Web_app.tests.test_auth_admin_v1.AuthAdminHttpTest.test_central_permissions_distinguish_401_and_403 \
  04_Web_app.tests.test_http_smoke_v1.HttpSmokeV1Test.test_product_metadata_readiness_schemas_and_job_query
```

These historical C0 failures were resolved before the C2.4 release. Re-verify the
relevant regression surface for any new application candidate rather than relying
on the old outcome.

## 24. Agent continuation rules

- Start from current evidence; do not trust this handoff blindly.
- State whether a claim is observed now, documented earlier, assumed or unknown.
- Keep raw data immutable and preserve non-reproducible artifacts.
- Respect task scope. Documentation-only means no “small” code or config fix.
- Do not change posterior mathematics, training methodology, optimizer or
  recommendation policy unless explicitly approved.
- Do not change or inspect the live server through SSH during a local audit.
- One task, one `codex/` branch, one PR; keep review fixes in that PR; never merge.
- Do not touch unrelated dirty/untracked files.
- Before SQL or analytics define population, grain, period, denominator, estimand,
  counterfactual and DQ checks.
- End meaningful work with changed files, verification, known limitations, blockers
  and the next explicitly approved action.

## 25. B2.2 handoff state

C2 relocation and legacy-root switch are complete. The B2.2 branch starts from
`origin/main@52461f6e00b4b6fe705a341d30747e0067ae3b24`, the user-merged PR #40
identity. Frozen Predfin/Fin remains at application commit
`2a6e07755f0db494a064b7db6517219325850179` and the same restricted model
identity. B2.2 is isolated in `codex/b2-2-federal-campaign-ux`; it must be reviewed
through its PR and not merged by Codex.

Pre- and post-rename operational smoke and path scans pass without legacy fallback.
The current Test milestone is B2.2 Federal Campaign User Flow. Post-merge Predfin
acceptance remains blocked by the `ТС5/Онлайн` denominator/carryover mismatch and
is a separate controlled operation; B2.3, Fin, deployment and C3 cleanup are not
authorized. The active model stays restricted and the server is unchanged.
