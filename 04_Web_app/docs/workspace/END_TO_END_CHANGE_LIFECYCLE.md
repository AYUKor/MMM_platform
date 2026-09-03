# MMM Platform End-to-End Change Lifecycle

## Purpose and governing boundary

This is the canonical path from a business idea or a new data delivery to a
verified change on `https://mmm.x5.ru/`. It joins the existing data, development,
Predfin, Fin and server contracts without replacing their detailed runbooks.

The lifecycle keeps four approvals separate:

1. the business question and methodology are fit for the intended decision;
2. application code is reviewed and merged;
3. a model package is accepted for an explicitly named serving status;
4. one immutable Fin release is verified and activated on the server.

An application can be deployed while its model remains
`preprod_restricted / production_gate=not_passed`. In that state the portal is a
research-pilot decision-support system, not an unrestricted production model.

## Source-of-truth hierarchy

| Question | Authoritative evidence |
|---|---|
| Stable product intent | `04_Web_app/PROJECT_BRIEF.md` |
| Current operational truth | `04_Web_app/CURRENT_TRUTH.md` and live verification evidence |
| Current continuation state | `04_Web_app/PROJECT_HANDOFF.md` |
| Long-term decisions and context | canonical project brain under `01_Test/project_brain/wiki/` |
| Application implementation | reviewed Git commit/tree on GitHub `main` |
| Data identity | immutable `00_Data` artifact plus manifest and SHA-256 |
| Model identity | package manifest, registry entry, panel lineage and serving policy |
| Predfin acceptance | immutable Predfin handoff and acceptance evidence |
| Fin identity | `03_Fin/releases/<release_id>` manifests and checksums |
| Active server release | `/opt/x5-mmm/current`, release-local `SERVER_RELEASE.json`, and append-only deployment evidence |

Narrative documents do not override physical artifacts, Git identities, manifests
or current live evidence.

## A. From business idea to an executable task

Examples include “support federal advertising” and “estimate a past campaign”.

```text
business idea
  -> discussion and problem framing
  -> methodology and decision boundary
  -> recorded assumptions/ADR/brain decision
  -> bounded implementation task for Codex
```

Before implementation, define:

- user decision and prohibited overclaim;
- population, grain, period and outcome;
- estimand and counterfactual when the change is causal or model-based;
- input/output contracts and failure semantics;
- acceptance scenarios, including one negative control;
- whether application approval and model approval are both required.

ChatGPT or another reasoning workspace may help develop the question and
methodology. Stable conclusions belong in the project brain or an ADR; Codex then
implements the bounded change against those recorded decisions.

## B. New data and quarterly refresh

New agency or source data enters `00_Data` as a new immutable version. Raw input is
never overwritten.

```text
source delivery
  -> immutable raw registration
  -> source manifest and SHA-256
  -> reproducible preparation
  -> DQ, coverage and reconciliation
  -> versioned panel candidate
  -> panel manifest and fingerprint
```

The manifest must bind source files, preparation code/config, population, grain,
period, shape, rejected rows, join cardinality, reconciliation results, bytes and
SHA-256. A new panel does not automatically replace the panel used by an accepted
model. DWH execution, panel rebuild and data replacement require explicit
authorization.

## C. Research and development in Test

`01_Test` contains research, notebooks, training, experiments, application code
and tests. Application work occurs in `01_Test/MMM_platform`:

```text
current GitHub main
  -> codex/<task> branch
  -> implementation and focused tests
  -> broader regression/security/path checks
  -> pull request
  -> owner review and merge
```

No production hotfix is made directly on the server. Repeated notebook logic moves
to versioned modules when this improves reproducibility. Development output alone
is not release evidence.

## D. Model change lifecycle

When data, posterior fits, feature preparation or serving policy changes:

```text
00_Data accepted panel
  -> 01_Test training/research
  -> diagnostics and historical replay
  -> required OOT/holdout/model gates
  -> immutable package build
  -> registry registration and serving policy
  -> Predfin model acceptance
  -> Fin model closure
```

Every model package binds its input panel hash, training code/config, posterior
artifacts, diagnostics, target/segment coverage and package status. Application
release approval never upgrades `preprod_restricted` to production-approved. A
production pointer or status change requires its own model-governance decision and
evidence.

## E. Application change lifecycle

Frontend/backend runtime changes require a reviewed Git commit and tree. Tests or
documentation can advance on later commits without changing a previously frozen
runtime identity, but release evidence must state that distinction explicitly.

Required application checks are proportional to the change and include contract,
unit, integration, browser, auth/permission, path-independence and security gates.
Acceptance tooling must bind assertions to exact request/response evidence; an
unrelated or stale DOM message is not proof that a specific API contract failed.

## F. Predfin

Predfin materializes one exact GitHub-approved application identity together with
one explicit model candidate. It is a controlled acceptance contour, not a mutable
development checkout.

Predfin verifies:

- backend and frontend behavior;
- exact model, registry and package-extension closure;
- reports, maps, auth/state compatibility and representative business flows;
- a clean same-origin production frontend build;
- security, secrets exclusion and path independence;
- owner manual acceptance of the targeted product scenarios.

A PASS produces an immutable handoff. A changed runtime artifact requires a new
Predfin acceptance; a test-only or docs-only commit does not silently change the
frozen application source.

## G. Fin

Owner-accepted Predfin becomes a new immutable
`03_Fin/releases/<release_id>`. Fin contains:

- exact application source at the approved commit/tree;
- reproducible `04_Web_app/frontend/dist`;
- model package, registry and all required package extensions;
- release, frontend, model and checksum manifests;
- minimal immutable acceptance evidence;
- one verified transfer artifact.

Fin excludes raw/source panels, secrets, runtime databases, logs, caches, virtual
environments and `node_modules`. `03_Fin/CURRENT_RELEASE.json` changes only after
all Fin gates pass and is a relative machine-readable pointer, not a server
symlink.

## H. Server materialization

Only the verified Fin transfer artifact may create a server candidate:

```text
verified Fin bundle
  -> transfer to approved server staging path
  -> exact archive and per-file checksum verification
  -> tracked server_release.py
  -> new /opt/x5-mmm/releases/<release_id>__deployN
  -> isolated production-equivalent preflight
```

Every attempt uses a new candidate directory; failed or earlier candidates are not
repaired in place or reused as a target. Materialization verifies application
commit/tree, frontend identity, complete model/registry/extension mapping and
release-specific business artifacts. Git trust, when required by runtime code, is
restricted to the exact candidate; `safe.directory=*` is forbidden.

## I. Corporate deployment

The external corporate layer is outside the application release lifecycle: DNS,
FIP/load balancer, firewall, VPN publication, proxy, TLS certificate/chain and the
public hostname remain unchanged.

The server-local deployment sequence is:

```text
verify rollback candidate
  -> drain: running jobs=0, queued jobs=0, running validations=0, optimizer=0
  -> fresh verified persistent-state backup
  -> verify candidate and alternate-port business gates
  -> atomically switch /opt/x5-mmm/current
  -> restart backend only
  -> health, ready, historical, frontend and product acceptance
  -> seal SERVER_RELEASE.json after complete PASS
```

Nginx, systemd references and backend configuration resolve application assets
through `/opt/x5-mmm/current`. Persistent auth, audit, jobs, validations, uploads,
reports, artifacts, logs, secrets and server configuration remain outside the
release. JupyterHub is independent and must not be restarted for an MMM release.

## J. Frontend delivery and acceptance

Nginx serves `current/04_Web_app/frontend/dist`. `index.html` uses
`Cache-Control: no-cache` so a release switch revalidates the application shell.
Hashed JavaScript and CSS assets are content-addressed and may use immutable
caching.

Acceptance always proves the delivery chain before product smoke:

```text
current switch
  -> backend restart
  -> local origin index.html and expected asset names/hashes
  -> external URL byte identity
  -> clean or revalidated browser context
  -> network-loaded index, JavaScript and CSS identity
  -> product scenarios
```

A browser tab opened before the switch is not sufficient evidence. If the browser
shows an error, bind it to the exact validation/job id, API URL, HTTP status, raw
response SHA, contract parse, frontend projection, route, console evidence and DOM
assertion before classifying the defect.

## K. Rollback

Release rollback is different from persistent-state restore.

```text
critical acceptance failure
  -> atomically point current to the verified previous release
  -> restart backend
  -> verify health, ready, portal, auth/history/report and /hub/
```

Rollback must not require GitHub, internet, `npm install`, a frontend rebuild or a
new Mac-to-server transfer. The previous release and its frontend/model assets are
already present. Persistent state is restored only after separately proven state
corruption and an explicit restore decision.

## L. Observation and cleanup

After deployment PASS, observation begins immediately. Monitor real user jobs,
validation failures, queue/running counts, report downloads, model readiness and
service/timer failures while preserving release identity. Record incidents against
the exact release and job/validation ids without copying secrets or user payloads
into Git.

Cleanup is a later, separately authorized destructive milestone. Fin releases,
server candidates, legacy snapshot, `/opt/x5-mmm/app`, transfer/staging evidence and
backups are retained until an explicit retention decision names exact targets.

## M. Shortened paths by change type

| Change type | Required path | What is not rebuilt |
|---|---|---|
| Tests or documentation only | branch -> tests/review -> PR -> owner merge | Predfin, Fin and server runtime release |
| Deployment tooling only | branch -> tests/review -> PR -> owner merge -> new server candidate from the same verified Fin | application source, frontend dist and model package |
| Frontend/backend runtime code | Test branch -> PR/merge -> Predfin -> owner acceptance -> new Fin -> new server candidate -> deployment | model package when its closure is unchanged |
| Model package or serving policy | data/model Test -> model gates -> Predfin -> new Fin -> deployment | application only when its pinned identity is unchanged and compatible |
| New data plus retraining | immutable `00_Data` intake -> preparation/DQ -> Test training -> validation/OOT -> package/registry -> Predfin -> Fin -> deployment | nothing across the model lineage |

The shortened path never weakens identity, checksum, rollback, state-compatibility
or acceptance evidence.

## N. Mandatory STOP conditions

Stop and request an owner decision when:

- methodology or estimand is not approved;
- data lineage, population or counterfactual is unclear;
- an operation is destructive or its exact target is not proven;
- a persistent-state/schema migration is required;
- the model production gate or status would change;
- DNS, load balancer, firewall, proxy, VPN or TLS/CA must change;
- rollback cannot be proven from assets already present.

A reproducible application, acceptance-tooling or server-materialization bug is not
by itself a reason to abandon the product goal. Classify the layer, rollback live
production when required, fix through the governed branch/PR path, rebuild only the
affected immutable layer and resume the same approved goal.

## First live proof of this lifecycle

D1R5 activated server candidate
`release_9355c6c8fdaf_807d3ddbae57_ed8a6c6c7642_77973f4d424c__deploy5`
on 2026-09-03 from Fin release
`release_9355c6c8fdaf_807d3ddbae57_ed8a6c6c7642_77973f4d424c`. The accepted
application identity is commit `9355c6c8fdaf9d715434848ec306670e944ff263`, tree
`d8f69aa5c47a1cbacca1aee6c94aaab85f841a31`. Federal full-flow, mixed
federal/local validation, blocking geo, ordinary regression, historical map,
frontend asset identity, auth/state and JupyterHub route gates passed. The model
remains `preprod_restricted / production_gate=not_passed`. Observation is active;
cleanup is not authorized.
