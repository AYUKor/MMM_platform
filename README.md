# MMM Platform

Source-code and documentation baseline for a Bayesian Marketing Mix Modeling
platform. The repository contains the data-preparation, model lifecycle,
forecast, budget-optimization and reporting code that will later be integrated
into an internal web application.

## Repository map

- `00_Data/` — data contracts, refresh code and local runtime input areas;
- `02_Code/01_PyMC/` — model lifecycle, validation and model registry;
- `02_Code/03_AC_forecast/` — future-campaign forecast workflow;
- `02_Code/02_Budget_optimizer/` — budget optimization and marketer reporting;
- `03_Outputs/README.md` — storage contract for generated artifacts;
- `04_Web_app/` — canonical application requirements and architecture documents.

Git contains source code, safe configuration templates and documentation only.
Real data, posterior files, immutable model packages, generated forecast and
optimizer results, and business reports are external runtime artifacts and are
not part of the source repository.

Read the stable product scope in
[`04_Web_app/PROJECT_BRIEF.md`](04_Web_app/PROJECT_BRIEF.md) and the verified
current state in
[`04_Web_app/CURRENT_TRUTH.md`](04_Web_app/CURRENT_TRUTH.md).

The web application is not implemented yet. There is currently no frontend,
backend, database, queue or worker runtime in this repository.

Local development and future server deployment must use the same versioned
calculation interfaces and immutable artifact contracts. Environment-specific
storage, credentials, queues and databases are supplied by deployment
configuration; MMM mathematics must not be copied into the web layer.
