# Model Lifecycle

## Current status

The current package is `pkg_807d3ddbae57a52a_9aacd3beb350725b`. It remains
`preprod_restricted`; `production_gate = not_passed`. C2.5 does not change either
status and does not create a production registry pointer. This section describes
the deployed package A; the portal label for any package follows that package's
own verified record (ADR 0026).

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
  -> manifest rebuild -> registry and promotion gates
```

- `fit` ends at `fit_complete`. It does not build the model package.
- `package` is the first package/export of a completed fit
  (`02_pymc_model.py --mode package`). It is technical: it does not accept, validate
  or promote a model.
- `validation` writes OOT and response-replay verdicts bound to the package
  fingerprint, so it refuses to write them before the package exists.
- the manifest rebuild (`python 02_Code/01_PyMC/mmm_core/model_package.py --run-dir <run> --write`)
  recompiles the gates and blockers with those verdicts. It reads the files as they are
  and exports nothing, so the package fingerprint, and every verdict bound to it, stays
  valid. Do not use `02_pymc_model.py --mode replay` for this step: on a guarded-fit
  package it re-exports `fit_design_metadata.json` with a new `generated_at_utc`, that
  file is part of the fingerprint, and every verdict becomes
  `STALE_OR_UNBOUND_OOT_VALIDATION` / `STALE_OR_UNBOUND_HISTORICAL_REPLAY` (seen when
  the Q2 final model B was first released).
- Registry registration and promotion stay separate gates (below). CLI details are in
  `02_Code/01_PyMC/mmm_core/README.md`.

## A model change changes the serving side

A new model (a refit on new data, or any change of the response, exposure or time
logic) is not finished when the fit is. Forecast engine, budget optimizer, historical
replay and the past-campaign catalog must compute every channel exactly as that fit
did, and this is proven before the package is released:

- **Exposure rule.** When a fit replaces a channel's city exposure by something else,
  the serving side uses the same basis. V4k assumption channels (national TV, digital
  without a city split) are trained on the unweighted cross-city mean per date; the
  forecast, the optimizer kernels and the replay use that national index for them
  (`exposure_basis` in the forecast rows). Rule, formula and limits are in
  `02_Code/01_PyMC/mmm_core/README.md`, section "V4k time effect and assumption
  channels".
- **Parity gate.** `validation.run_serving_roas_parity`, part of
  `03_model_validation.py --mode response-replay`, replays the training window through
  the serving geo loop on the 200 posterior draws behind the package's own
  `roas_rub_all_fits.csv` and requires the same ROAS per turnover channel (p5, median,
  p95, relative tolerance 1%). A failure fails the replay verdict
  (`MISSING_OR_FAILED_HISTORICAL_REPLAY`), so the package cannot be released.
- **Order.** `forecast_engine.py` and `validation.py` are part of the package
  fingerprint (see "Code bound to a package"). Their change for the new model is
  merged before the final package is built; a failed parity check means: fix the code,
  build a new package (new fingerprint), run the replay again.
- The standing rule of the project owner (31.10.2026) is in `AGENTS.md`, section
  «Смена модели».

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
`forecast_engine.py` and `validation.py` (and of `fit_design_metadata.json`), and
`ModelPackage.from_run_dir` recomputes it where hash validation is on: registry
`full_lineage` verification, the validation and replay CLIs, the package and manifest
steps. A package therefore passes `full_lineage` only under exactly the code it was
built with: any later change to those files makes it stale there and requires a rebuilt
package and new replay and OOT evidence.

A serving bundle (portal, MacBook, server) is loaded in `serving_bundle` mode: the
registered inventory is verified byte for byte and the registered fingerprint must equal
the manifest's, but the hash is not recomputed against the running code. An older bundle
therefore keeps loading under newer code. That is a compatibility fact, not evidence:
when serving math changes (for example the national-index exposure above), a package
built before the change carries no proof of the new rule until it is rebuilt.

Merge a release branch exactly as the package was built and do not touch these files
between the package and the release in Fin. Change them before the package is built.
