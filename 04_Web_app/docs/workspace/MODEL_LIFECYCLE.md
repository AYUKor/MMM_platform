# Model Lifecycle

## Current status

The current package is `pkg_807d3ddbae57a52a_9aacd3beb350725b`. It remains
`preprod_restricted`; `production_gate = not_passed`. C2.5 does not change either
status and does not create a production registry pointer.

## Lifecycle

```text
versioned panel
  -> 01_Test training/research run
  -> validation and candidate package
  -> controlled promotion to 02_Predfin
  -> acceptance against exact application candidate
  -> frozen model closure
  -> new immutable 03_Fin release
  -> separate production-gate decision
```

Training, MCMC, posterior generation and model recalculation are allowed only in an
explicit Test milestone. Predfin and Fin do not retrain.

## Research and serving packages

Research evidence and serving semantics are distinct:

- the research package may preserve diagnostic targets and additional artifacts;
- application serving activates only policy-approved targets and packages;
- source-panel identity remains lineage even when the panel is excluded from the
  serving transfer;
- package extensions are part of the closure when the runtime requires them;
- a clean internal replay or QA result does not replace sealed OOT evidence.

For the current package, 12 research fits are retained while four turnover fits are
the application-serving boundary. Orders and average-basket fits do not become
active product KPIs.

## Candidate requirements

A candidate model must record:

- package ID and package fingerprint;
- source panel SHA-256, size, period and training window;
- code/config identity and deterministic seeds where applicable;
- complete artifact inventory with hashes and byte sizes;
- capability matrix and gate-policy identity;
- diagnostics, replay/OOT evidence and explicit failed/missing gates;
- allowed serving targets and registry channel intent;
- required package extensions.

Incomplete candidates fail closed. Experiment folders are never promoted merely
because a model run completed.

## Promotion and activation

Promotion to Predfin is governed by `PROMOTION_TO_PREDFIN.md`. Materialization into
Fin is governed by `PROMOTION_TO_FIN.md`.

Fin approval means that application code and a restricted model closure are
deployable together under their recorded limits. It does not mean the statistical
model has passed the separate production gate.

Production activation requires its own evidence and explicit decision. Missing or
failed OOT keeps the current package restricted even when application, transfer and
runtime checks pass.
