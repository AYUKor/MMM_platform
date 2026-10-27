# mmm_core

Общий слой переиспользуемой MMM-логики.

Что здесь должно жить:

- accepted PyMC MMM specification and wrappers;
- единые функции чтения/записи и config validation;
- shared reporting builders;
- scenario planning primitives, которые нужны и forecast, и optimizer.

Что здесь не должно жить:

- разовые notebook experiments;
- сырые path-хардкоды конкретного запуска;
- orchestration конкретного batch/run.

Если функция нужна только одному workflow и занимает пару строк, сначала держим ее внутри workflow. Выносим в `mmm_core` только когда появляется реальное переиспользование или код становится сложно читать.

## Model Package Contract

`model_package.py` builds the bridge between the fitted PyMC model and downstream
planning layers. Forecast and budget optimizer code should read the generated
`model_manifest.json`, `capability_matrix.csv`, `risk_registry.csv`, and
`posterior_index.json` instead of hard-coding model assumptions.

The builder supports partial runs: if only `run_config.json` exists, the package
is marked `config_only_or_partial`; once posterior/diagnostic artifacts appear,
rerunning the builder upgrades the package to `posterior_ready`.

## Fit → package stage boundary

A guarded fit ends at `fit_complete`: posteriors, `fit_execution_card.json` and the post-fit evidence
(`diagnostics_summary.csv`, `adequacy.json`, `roas_all_fits.csv`, `channel_reliability.csv`,
`target_effects_all_fits.csv`, `prior_posterior_contraction.csv`). The model package (`model_manifest.json`,
`capability_matrix.csv`, ...), the exported design metadata (`fit_design_metadata.json`, ...) and
`model_fit_card.json` belong to the separate package/export stage, so fit diagnostics can be reviewed before
any package exists.

| Command | Result |
|---|---|
| `02_pymc_model.py --mode fit ...` | Default `--package skip`: stops at `fit_complete`; the printed card has `package_created: false` and `next_stage`. |
| `02_pymc_model.py --mode fit --package auto ...` | Single shot as before the boundary: package, design metadata and `model_fit_card.json` right after `fit_complete`. |
| `02_pymc_model.py --mode fit --orchestrate ...` | Same policy for every isolated fit job (`--package` is passed explicitly). Completion needs a `fit_complete` `fit_execution_card.json` of this run identity (`skip`) or `model_fit_card.json` (`auto`); `fit_orchestrator_status.json` records `package_policy` and `package_created`. |
| `02_pymc_model.py --mode package --run-dir <run>` | Package/export stage of a completed fit; never samples. Refuses an incomplete fit, a missing or tampered posterior, missing post-fit evidence and an existing package; `--no-write` only checks these preconditions. Writes the same `model_fit_card.json` as `--package auto` (`package_policy: stage`). |
| `02_pymc_model.py --mode replay --run-dir <run>` | Rebuilds an existing package and re-exports its design metadata (new `generated_at_utc`). It needs a package, so it cannot create the first one. On a guarded-fit package the exported `fit_design_metadata.json` is part of the package fingerprint, so replay changes the fingerprint and every verdict written before it stops matching (`STALE_OR_UNBOUND_*`). Do not run it after validation. |
| `mmm_core/model_package.py --run-dir <run> --write` | Manifest rebuild: recompiles `model_manifest.json`, the capability matrix and the gate files from the files as they are. Exports nothing, so the fingerprint stays and verdicts written for it are picked up. This is the step after validation. |

Order for a new run: prepare → fit → review fit diagnostics → package → validation (`03_model_validation.py`) →
manifest rebuild (`mmm_core/model_package.py --run-dir <run> --write`) to refresh the package gates and blockers →
registry and promotion, which stay separate gates.
Validation verdicts bind to the package fingerprint, so `03_model_validation.py` refuses to write a verdict (OOT
with `--write-verdict`, response replay) until `model_manifest.json` exists, and points at `--mode package`;
thresholds and gates are unchanged.
The package stage is technical: it does not accept, OOT-validate or promote a model.
Before this boundary `--mode fit` always built the package after the last fit; pass `--package auto` for that.

A refit on a longer window of an already OOT-validated specification can inherit that OOT instead of repeating it:
`03_model_validation.py --mode inherit-oot --run-dir <refit> --source-run-dir <validated run> --decision <owner
decision> [--write-verdict]`. The conditions (owner decision, same specification, same twelve fits, runtime
acceptance or pinned exceptions, passed replay) are checked by code; see "OOT inheritance for a refit" in
`04_Web_app/docs/workspace/MODEL_LIFECYCLE.md`.

## Forecast Engine Audit

`forecast_engine_audit.py` checks whether a completed model run folder is ready for the posterior forecast/optimizer engine. It does not run PyMC and does not calculate campaign effects. It validates:

- model-package files;
- capability/risk artifacts;
- posterior response variables (`beta`, `alpha`, `lam`);
- baseline variables (`gamma`, `tau_g`, `sigma`);
- missing strict-replay metadata that must be exported before forecast math.

Example:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B 02_Code/01_PyMC/mmm_core/forecast_engine_audit.py \
  --run-dir 03_Outputs/01_PyMC_outputs/<run_folder>/<production_folder>
```

Do not copy a package ID or readiness status from an old handoff into runtime
code. Resolve the current package through the live registry and verify its
registration and inventory. The evidence-backed status and remaining blockers
are maintained in `04_Web_app/CURRENT_TRUTH.md`; production activation remains
fail-closed until its required gates pass.

## Historical Geo Budget Artifact

`historical_geo_budget.py` builds a deterministic package-bound aggregate for
the Home historical-spend map. It resolves the source panel only through model
registry registration metadata, verifies size and SHA-256, projects date, geo
and the six columns declared in
`configs/historical_geo_budget_spend_columns_v1.json`, and writes:

- `historical_geo_budget_v1.parquet`;
- `historical_geo_budget_v1.metadata.json`;
- `package_artifacts_manifest_v1.json`.

The extension lives under
`03_Outputs/01_PyMC_outputs/00_Model_registry/package_artifacts/<package_id>/`
so an already registered immutable package is not mutated. The web service
verifies this identity chain and reads the small metadata aggregate; it never
opens the training panel during a Home request. Null, infinite and negative
spend values fail closed, and aggregate OOH cannot be combined with its raw
components.
