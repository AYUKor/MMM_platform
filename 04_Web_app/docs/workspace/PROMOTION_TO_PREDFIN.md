# Promotion to Predfin

## Contract

```text
01_Test candidate
  + approved application commit
  + approved model candidate
  + required package extensions
  -> controlled 02_Predfin materialization
  -> acceptance evidence
```

Predfin is a staging/acceptance contour. It never receives unreviewed experiment
outputs automatically.

## Prerequisites

1. The Test source inventory is explicit and the candidate scope is allowlisted.
2. Application changes are committed to a review branch. The commit selected for
   Predfin is approved and resolves to an exact tree.
3. Model candidate has an immutable package ID, complete manifest and exact panel
   binding.
4. Required package extensions are named and hash-addressed.
5. Research-only outputs, source panel, credentials, runtime state, caches,
   `node_modules` and virtual environments are excluded unless a gate explicitly
   requires a source-only artifact.
6. Existing Predfin evidence is preserved; promotion creates new versioned evidence
   rather than silently rewriting prior acceptance history.

## Materialization rules

- Copy physical files first; do not symlink or hardlink to Test or the legacy
  workspace.
- Verify destination SHA-256 and bytes independently.
- Materialize the application as an exact clean checkout or verified archive.
- Resolve model registry and extension paths relative to the candidate application.
- Record source and destination inventories, provenance and exclusions.
- Do not mutate model status during copy.

## Acceptance gates

Predfin PASS requires all applicable gates:

- application commit/tree identity and clean status;
- model package, registry pointer, package fingerprint and complete closure;
- exact source-panel lineage;
- package-extension completeness;
- backend import/startup preflight;
- registry/package/extension resolution;
- historical geo-budget availability when required by the application;
- targeted and regression tests appropriate to the candidate diff;
- frontend lockfile reproducibility and security evidence;
- secrets scan;
- path independence with zero runtime/application/model-lookup/registry blockers;
- source-contour integrity and immutable acceptance manifests.

Any mismatch fails closed. A partial PASS is not permission to create Fin.

## Outputs

The promotion must produce machine-readable evidence covering application, model,
data freeze, regression/security results, path independence and a Fin handoff. The
handoff names the exact identities that a later Fin milestone may consume.

Predfin PASS does not deploy, switch the server or activate production serving.
