# 00_Data

Compact storage for MMM data passes.

## Folder Contract

- `01_2025_first_pass/` - first model/data pass for 2025.
- `02_2025_2026Q1_second_pass/` - second pass with refreshed 2025-2026 data, preserved panel v2 and the current reviewed panel v3.
- Future passes should use the next numeric prefix, for example `03_YYYY_scope_third_pass/`.

Each pass keeps its raw inputs, audit artifacts, intermediate reference files, and final model parquet together.

## Main Scripts

- `data_pipeline.py` - main data-refresh pipeline: media intake/DQ, geo mapping, controls, weather/macro joins, target handling, and final model panel assembly.
- `data_pipeline_config.yaml` - current run config for the second pass.
- `build_weather_v2_exact.py` - exact weather artifact builder used by the v2 pass.
- `clean_panel_v2_dq.py` - historical one-off v2 cleanup evidence. The reviewed target-imputation policy now lives in `data_pipeline.py`.

Current canonical model-ready parquet for the panel v3 model line:

`00_Data/02_2025_2026Q1_second_pass/panel_final_v3.parquet`

`panel_final_v2.parquet` remains immutable lineage evidence for the previous Q1 model package.

Quarterly refresh automation is currently partial: calendar and RUONIA acquisition are automated, while exact weather refresh and USD/RUB/Brent tails still require upstream artifacts. See `01_Main_Brain_MMM/wiki/synthesis/x5-mmm-production-backend-readiness-roadmap-2026-07-12.md`.
