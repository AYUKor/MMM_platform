# MMM Workspace Lifecycle

## Status and scope

This document defines the canonical local workflow at `<MMM_WORKSPACE_ROOT>`. This
placeholder identifies the local root containing `00_Data/`, `01_Test/`,
`02_Predfin/` and `03_Fin/`. The workflow changes local roles and promotion rules
only; following this document does not by itself authorize a corporate deployment,
activate a production model, run OOT validation or authorize C3 cleanup. The joined
idea-to-server process is defined in `END_TO_END_CHANGE_LIFECYCLE.md`.

All paths below are relative to the local workspace root. New code and config must
not embed a user-specific absolute path.

## Canonical contours

| Contour | Canonical role | Allowed work | Forbidden use |
|---|---|---|---|
| `00_Data` | Local data source of truth | immutable raw intake, reproducible prepared data, versioned panels and data manifests | model experiments, application development, in-place overwrite of accepted panels |
| `01_Test` | Development and research | preparation pipelines, panel candidates, training, experiments, B1/B2 Federal Geo Allocation, historical-campaign research and application branches | claiming acceptance or release readiness from development output alone |
| `02_Predfin` | Staging and acceptance | exact application candidate, approved model candidate, required extensions, security/regression/path checks and immutable acceptance evidence | automatic ingestion of unreviewed experiments or mutable development work |
| `03_Fin` | Immutable deployable release | versioned approved releases, verified transfer artifacts and machine-readable current-release pointer | development, training, experiments, notebook work or in-place hotfixes |

The old workspace at `<MMM_LEGACY_ROOT>` is `LEGACY_ROLLBACK_ONLY`. It remains
physically available, but is not an operational
fallback for data update, development, acceptance, release creation or deployment.
A remaining local migration staging copy outside `<MMM_WORKSPACE_ROOT>` is
`MIGRATION_STAGING_COPY`, not canonical.

## End-to-end workflow

```text
agency/raw source
  -> 00_Data immutable intake
  -> reproducible prepared data and versioned panel
  -> 01_Test research, training and application branch
  -> approved Git commit plus approved model candidate
  -> 02_Predfin controlled materialization and acceptance
  -> new 03_Fin/releases/<release_id>
  -> verified offline transfer artifact
  -> corporate server only in a separately authorized deployment milestone
```

Application code follows a separate review boundary:

```text
01_Test/MMM_platform
  -> codex/<task> branch
  -> Pull Request
  -> reviewed merge
  -> GitHub main
```

GitHub `main` is the source of truth for approved application code. A local branch,
Predfin checkout or Fin copy never silently supersedes it.

## Current release

- Release ID: `release_9355c6c8fdaf_807d3ddbae57_ed8a6c6c7642_77973f4d424c`.
- Application commit: `9355c6c8fdaf9d715434848ec306670e944ff263`.
- Application tree: `d8f69aa5c47a1cbacca1aee6c94aaab85f841a31`.
- Model package: `pkg_807d3ddbae57a52a_9aacd3beb350725b`.
- Model status: `preprod_restricted`.
- Production gate: `not_passed`.
- Live server candidate:
  `release_9355c6c8fdaf_807d3ddbae57_ed8a6c6c7642_77973f4d424c__deploy5`.
- Deployment status: D1R5 accepted on 2026-09-03; observation active.

`03_Fin/CURRENT_RELEASE.json` is a relative machine-readable pointer. It may change
only after a new release passes every Fin gate. Existing release directories are
never modified in-place.

## Path policy

New code and configuration must resolve files from one of these boundaries:

- discovered project/workspace root;
- versioned configuration;
- environment variable supplied by the runtime;
- package-relative path;
- model registry lookup.

New user-specific absolute-path hardcoding is prohibited. Existing historical path
debt is inventoried evidence, not a template. C2.6 does not mass-rewrite archived
notebooks, old manifests or frozen model provenance.

## Git and release policy

- `01_Test/MMM_platform` is the development checkout.
- `02_Predfin/MMM_platform` is an exact candidate checkout used for acceptance.
- `03_Fin/releases/<release_id>` is immutable after PASS.
- Old Git clones and worktrees are rollback/reference evidence only.
- No worktree pruning, old `.git` deletion, force push or history rewrite belongs
  to C2.6.

## Cleanup policy

C3 is not authorized. Future cleanup candidates must first be classified as one of:

- `SAFE_GENERATED`;
- `ARCHIVE`;
- `LEGACY_REFERENCE`;
- `DELETE_CANDIDATE`;
- `MANUAL_DECISION`.

No destructive cleanup may start until the observation gate in
`C2_5_OBSERVATION_PLAN.md` is satisfied and a separate explicit authorization is
given. Old data, model runs, Git/worktrees, web application copies,
presentations and deployment evidence remain preserved.
