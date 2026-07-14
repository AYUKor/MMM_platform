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
