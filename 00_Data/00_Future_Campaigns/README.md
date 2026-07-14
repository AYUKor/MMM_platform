# 00_Future_Campaigns

Permanent input area for future advertising campaign briefs.

Use this folder when business or an agency sends an Excel file for:

- campaign forecast;
- budget optimization;
- budget reallocation scenarios.

The workflow must treat these files as input data. Do not edit the original Excel in place.

Expected subfolders:

- `01_Inbox/` - raw Excel briefs from business or agency;
- `02_Validated/` - normalized campaign plan tables produced by scripts;
- `03_Flighting/` - daily budget flighting produced by scripts when the source file has only budget plus start/end dates.

Configs should point here through `paths.campaign_input_dir` and an explicit `paths.campaign_file`.
