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

## Test-contour stages

Inside the Test contour a research run moves through explicit stages; finishing one
never starts the next:

```text
prepare -> fit -> review fit diagnostics -> package -> validation (OOT, response replay)
  -> replay -> registry and promotion gates
```

- `fit` ends at `fit_complete`. It does not build the model package.
- `package` is the first package/export of a completed fit
  (`02_pymc_model.py --mode package`). It is technical: it does not accept, validate
  or promote a model.
- `validation` writes OOT and response-replay verdicts bound to the package
  fingerprint, so it refuses to write them before the package exists.
- `replay` rebuilds the package with those verdicts and refreshes its gates and
  blockers.
- Registry registration and promotion stay separate gates (below). CLI details are in
  `02_Code/01_PyMC/mmm_core/README.md`.

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

## OOT inheritance for a refit (policy v1)

A refit of the same specification on a longer window has no out-of-time period of its
own. It may reuse the sealed OOT verdict of the earlier fit only through
`oot_inheritance_policy` version 1, and only when the owner's decision file
(`final_model_admission_decision_v1`) pins both runs and the code finds every condition
true. Nothing is scored again, thresholds and gates do not change, and the verdict file
says so: `evidence_basis = inherited_from_validated_refit`.

`03_model_validation.py --mode inherit-oot --run-dir <refit> --source-run-dir <validated> --decision <file> --write-verdict`
issues `oot_validation.json` bound to the refit's package fingerprint. It refuses to
overwrite an existing verdict and writes nothing when a condition fails. Conditions
(`model_package.evaluate_oot_inheritance`):

- the decision is approved by the owner, quotes the owner's message, names policy
  version 1 and pins the validated OOT file (SHA-256 and package fingerprint) and the
  refit (panel SHA-256, `run_config.json` SHA-256, training end);
- the validated OOT is sealed (`sealed_activation_oot`, `development_seen = false`),
  `passed`, `activation_eligible`, with turnover required pass and full turnover geo
  coverage, and is not itself inherited;
- the refit has the same specification: every `run_config.json` leaf is identical
  except the training window, panel and media-ledger identity, run labels and the
  sampler profile (draws, tune, chains, decay grid step); channel sets are compared as
  sets; the refit window extends the validated one;
- the same twelve fits, each with R-hat at most 1.05, ESS per draw at least 0.10 and at
  most 5 divergences. A violation is allowed only through an `accepted_exceptions` entry
  of the decision pinned to that fit, metric, threshold and observed value;
- the decision attests that nothing was tuned after the validated OOT quality was seen,
  and records the post-release monitoring plan;
- the historical replay of the refit has passed and is bound to the same fingerprint.

The package builder and the registry (`_assert_production_eligible`) re-run these
checks against the embedded decision, and, where the validated run folder is still
reachable, against its files. A failed check is the production blocker
`INVALID_INHERITED_OOT_VALIDATION`. The manifest records `oot_basis` with the policy
version, decision SHA-256 and the validated OOT identity. The independent sealed OOT of
the refit remains possible only on data after its training window; the decision's
monitoring plan names that check.

## Code bound to a package

The package fingerprint includes the SHA-256 of `model_package.py`,
`forecast_engine.py` and `validation.py`, and `ModelPackage.from_run_dir` recomputes it
(hash validation is on by default). A package therefore only loads under exactly the
code it was built with: any later change to those three files makes the package stale
and requires a rebuild (`--mode replay`) and new replay and OOT evidence. Merge a
release branch exactly as the package was built and do not touch these files until the
release is in Fin.
