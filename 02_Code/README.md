# 02_Code

Compact code layout for the MMM project.

## Main Folders

- `01_PyMC/` - model code, notebooks, shared `mmm_core`, convergence/report scripts, and model handoffs.
- `02_Budget_optimizer/` - budget optimization workflow and config templates.
- `03_AC_forecast/` - advertising campaign forecast workflow and config templates.

## PyMC Contract

The current panel-v3 model lifecycle uses stable script entry points backed by
`01_PyMC/mmm_core/`:

- `01_PyMC/01_panel_priors.py` - model-side panel checks, priors, and panel-regression artifacts.
- `01_PyMC/02_pymc_model.py` - PyMC fits and tiered run outputs.
- `01_PyMC/03_model_validation.py` - replay, OOT and package-gate validation.
- `01_PyMC/03_model_registry.py` - package registration, channel resolution, activation and rollback.

Notebooks are thin run cards or historical analytical references; they are not
runtime dependencies for forecast, optimizer or future web-application jobs.
