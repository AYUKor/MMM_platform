# 03_Outputs

Typed output storage for model and business calculations.

## Folder Contract

- `01_PyMC_outputs/` - PyMC model runs, diagnostics, and model-facing reports.
- `02_Budget_optimizer_outputs/` - budget optimization runs.
- `03_AC_forecast_outputs/` - advertising campaign forecast and scenario runs.

## Run Naming

Use a numeric prefix plus run type and date:

- PyMC: `01_PyMC_05062026/fast`, `01_PyMC_05062026/medium`, `01_PyMC_05062026/production`.
- Budget optimizer: `01_Budget_optimizer_05062026/`.
- AC forecast: `01_AC_forecast_05062026/`.

When the date changes or a new same-date run is needed, increment the prefix while keeping the date in the folder name.
