# Promotion to Fin

## Contract

```text
02_Predfin PASS
  + approved GitHub main identity
  + frozen model closure
  + security gates
  + path independence
  -> new 03_Fin/releases/<release_id>
```

Existing Fin releases are immutable. A hotfix or changed artifact always starts a
new Test -> PR -> Predfin -> Fin cycle.

## Source freeze

Fin materialization consumes one explicit Predfin handoff. The handoff must pin:

- repository, application commit and tree;
- model package ID, serving status and production gate;
- model closure file count, bytes and closure digest;
- package-extension identities;
- panel hash and metadata;
- accepted security, regression and path-independence evidence.

“Latest” is not a valid source identity. If GitHub `main` advances after the
freeze, the Fin release still uses the pinned approved commit unless a new Predfin
acceptance explicitly supersedes it.

## Release gates

1. Target release ID is deterministic from application commit, model package ID
   and model-closure digest.
2. Target release directory does not already exist.
3. Application snapshot matches the exact approved commit/tree and is clean.
4. Model closure is copied physically and independently verified.
5. Minimal immutable acceptance evidence is copied without secrets or runtime
   state.
6. Release, application, model and checksum manifests are valid JSON.
7. A transfer artifact is built only from the materialized Fin release.
8. Transfer contains the exact application, complete registry/model closure and all
   required extensions, with no source panel, secrets, runtime DB, logs, cache,
   venv or `node_modules`.
9. Transfer is independently extracted and verified.
10. Fin and extracted transfer have zero runtime, application, model-lookup and
    registry path blockers.
11. Source contours remain intact and deployment is not performed.

Only after every gate passes may `03_Fin/CURRENT_RELEASE.json` move to the new
relative release path. The pointer is a regular JSON file, never an absolute
symlink.

## Status semantics

- `application.release_status = approved` means the application release is
  deployable.
- `model.serving_status = preprod_restricted` remains an explicit restriction.
- `model.production_gate = not_passed` remains separate from Fin approval.
- `deployment.deployed = false` until a separately authorized server milestone
  actually runs and verifies deployment.
