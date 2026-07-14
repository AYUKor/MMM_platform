# 01_Inbox

Put raw future-campaign Excel files here.

Rules:

- keep original files unchanged;
- use clear filenames with campaign name and date;
- one config should explicitly point to one file via `paths.campaign_file`;
- do not rely on "latest file" mode for production decisions.

The parser will later read files from this folder and create normalized outputs in `02_Validated/`.
