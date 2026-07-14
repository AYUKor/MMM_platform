# Campaign forecast

This folder contains the future campaign forecast workflow.

## Current executable workflow

The workflow is now end-to-end for incremental media-effect forecasting:

1. read explicit future campaign brief from `00_Data/00_Future_Campaigns/01_Inbox/`;
2. normalize campaign rows and build daily flighting;
3. validate requested `campaign x segment x geo x channel x target` rows against the selected model package;
4. export or reuse fit-design metadata from the fitted MMM package;
5. simulate posterior p10/p50/p90 effects with the fitted MMM response logic.

Full run:

```bash
cd /path/to/MMM_platform
PYTHONDONTWRITEBYTECODE=1 python -B \
  02_Code/03_AC_forecast/ac_forecast.py \
  --config 02_Code/03_AC_forecast/ac_forecast_template.yaml
```

Useful partial runs:

```bash
# Check selected fitted model package only.
PYTHONDONTWRITEBYTECODE=1 python -B \
  02_Code/03_AC_forecast/ac_forecast.py \
  --config 02_Code/03_AC_forecast/ac_forecast_template.yaml \
  --check-model-package-only

# Parse, flight and validate the campaign brief only.
PYTHONDONTWRITEBYTECODE=1 python -B \
  02_Code/03_AC_forecast/ac_forecast.py \
  --config 02_Code/03_AC_forecast/ac_forecast_template.yaml \
  --prepare-campaign-only

# Export strict replay/forecast metadata from the model package only.
PYTHONDONTWRITEBYTECODE=1 python -B \
  02_Code/03_AC_forecast/ac_forecast.py \
  --config 02_Code/03_AC_forecast/ac_forecast_template.yaml \
  --export-model-metadata-only
```

## Forecast semantics

The forecast is an incremental media-effect simulation: campaign scenario versus no-campaign counterfactual. It is not a full business forecast of total turnover.

The scorer reuses fitted MMM posterior response variables and transforms:

`raw spend -> per-capita spend -> model scaling -> geo-reset adstock -> tanh saturation -> posterior beta -> target units`.

Outputs include p10/p50/p90 posterior intervals, `allowed_use`, `optimizer_use`, `risk_level`, model flags and historical-support flags.

## Campaign input folder

Future campaign Excel/CSV files should be placed in:

`00_Data/00_Future_Campaigns/01_Inbox/`

Configs should use:

```yaml
paths:
  campaign_input_dir: ../../00_Data/00_Future_Campaigns/01_Inbox
  campaign_file: your_campaign_file.xlsx
```

Keep `campaign_file` explicit for production work. Do not rely on an automatic latest-file rule.

Supported input forms:

- daily: `date + segment + geo + channel + budget_rub`;
- interval: `start_date + end_date + segment + geo + channel + budget_rub`.

If the source has interval rows, budget is spread evenly over active days and total budget is reconciled before downstream use.

## Current limitations

- Future controls are not used in incremental forecast because baseline and controls cancel in scenario-vs-no-campaign effects.
- Historical-support warnings are reported; production usage should add hard constraints or penalties for support violations.
- Full business forecast can be added later as a separate layer, but must not be mixed with incremental media-effect forecast.
