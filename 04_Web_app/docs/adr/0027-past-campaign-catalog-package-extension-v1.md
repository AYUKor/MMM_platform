# ADR 0027: past-campaign catalog as a package extension v1

## Status

Accepted for the past-campaigns tab on 2026-11-05. Publishing the catalog to a
server is a separate step that needs the model owner's explicit decision.

## Context

The model owner approved a portal tab that lists past campaigns, a card for
each campaign and an Excel file with the whole catalog (mock-up v2 of
2026-10-28). The numbers belong to the MMM side: the campaign catalog of the
active model gives, for every campaign, leave-one-out effects with an estimate
and an 80% range for turnover, orders per 1000 buyers, the change of the
average basket and ROAS on the full campaign budget, plus overlaps with other
campaigns of the same direction and a reliability flag. The portal must show
these numbers as published and never recompute effects.

A registered model package is immutable (ADR 0025), so the catalog cannot be
written into the package directory or its inventory.

ADR 0021 removed orders and the average basket from calculation-job results
because they are diagnostic for the optimizer. The catalog is a different
product: a read-only description of past campaigns, where the owner asked to
see all three effects.

## Decision

1. The MMM side builds `campaign_catalog_v1` offline with
   `mmm_core.campaign_catalog_extension` from the model's catalog folder and
   the registered package. It writes three files to
   `package_artifacts/<package_id>/campaign_catalog_v1/`: the JSON data, the
   Excel workbook and a metadata file.
2. The metadata binds the files to `package_id`, `package_input_fingerprint`
   and `model_run_id`, records the sha256 and size of the data and workbook
   files and lists the builder's checks. A build with a failed check writes
   nothing. An existing version is never overwritten; a new catalog is a new
   `catalog_version`.
3. The portal reads only these files. Without metadata the catalog is not
   published: the list returns a controlled `unavailable` payload, the card
   and the download return `404 CAMPAIGN_CATALOG_NOT_PUBLISHED`. Any mismatch
   (hash, identity, failed check, missing file) returns
   `503 CAMPAIGN_CATALOG_UNAVAILABLE`; no catalog data and no server path is
   shown.
4. Endpoints without query parameters:
   `GET /api/v1/campaign-catalog` and `GET /api/v1/campaign-catalog/{number}`
   need `model.read`; `GET /api/v1/campaign-catalog/download` needs
   `report.download`.
5. Orders per 1000 buyers and the average basket change appear only in the
   catalog, always with their ranges. No calculation, recommendation or
   optimizer path reads them; ADR 0021 still governs calculation-job results.
6. Every catalog screen shows the label of the ROAS level published with the
   catalog (for the «Заноза» model, «уровень ROAS по отрасли») and explains
   that a campaign effect is what would be lost without that campaign while
   the other campaigns stay.
7. The release pipeline accepts either the five historical extension files or
   those five plus the three catalog files. When the catalog ships, preflight
   requires the live API to return the same artifact and every campaign.
8. The frontend checks exact key sets, recomputes the summary from the rows
   and shows an error instead of a catalog that does not add up.

## Consequences

- the tab, the card and the Excel show one set of numbers produced and checked
  on the MMM side;
- package immutability and registration hashes remain valid;
- a catalog has to be built for every package that should show the tab;
  older packages show a plain "not published yet" state;
- the real catalog files are model outputs and are not committed to the
  source repository; tests use a synthetic catalog built by the same code.
