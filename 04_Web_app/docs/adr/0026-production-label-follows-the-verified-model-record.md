# ADR 0026: The production label follows the verified model record

## Status

Accepted on 2026-10-28 by the project owner (decision card in the Q2 model B
release thread: "make the portal production-ready"). It amends ADR 0014, which
fixed `production_claim_allowed=false` as a schema constant. ADR 0001 section 6
keeps its meaning: no application feature relabels a `preprod_restricted`
package as production-ready.

## Context

ADR 0014 described a research pilot built around package A, which has no
sealed OOT and is `preprod_restricted`. To make that impossible to misstate,
`serving.production_claim_allowed` was a schema constant `false` in
`product_api_v1`, `model_passport_v2` and `model_overview_v2`, enforced by the
Python validators and by the frontend parsers. The Home page, the model page,
the passport and every calculation result also carried hard-coded
"Research / preprod" and "model is not admitted to production" texts.

Q2 package B has a different record: `package_stage=posterior_ready`,
`activation_status=production_ready`, no production blockers, historical replay
`passed`, OOT `passed`. B's OOT is inherited from the validated refit A under
the owner-approved policy v1 (decision of 2026-10-27), and the passport labels
that basis as inherited. With the old constant the portal would have called B
"Research / preprod" although its own record says otherwise, and no model could
ever be shown as production-ready.

## Decision

1. One rule decides the label. A model is shown as production-ready only when
   its own verified record says so: `record_origin=verified_model_package`,
   `package_stage=posterior_ready`, `activation_status=production_ready`, an
   empty `production_blockers` list, historical replay `passed` and OOT
   `passed`. Anything missing, unknown or failed keeps the restricted label.
   The rule lives in `contracts/product_api_v1.production_claim_supported` and
   is reused by every validator and builder.
2. The label does not depend on a registry channel name, a deployment profile
   or a configuration switch. Portal, Fin and server still read the `preprod`
   channel pointer; activating the registry `production` channel is a separate
   model-governance step on the machine that holds the full run folder and is
   not required for the label.
3. `serving.production_claim_allowed` becomes a boolean in the passport v1,
   passport v2 and overview v2 contracts. The builders derive it from the
   record; the validators reject `true` when the record underneath does not
   support it (one direction, so a fabricated claim cannot pass) and reject
   non-boolean values. The frontend parsers repeat both checks.
4. The same boolean is published as `workspace_home_v1.model.production_claim_allowed`
   and `model_overview_v1.active_model.production_claim_allowed` (always `false`
   for an unavailable model; `true` is rejected next to the
   `sealed_oot_unavailable` limitation).
5. Texts follow the flag. For a production-ready model: no "Research / preprod"
   on Home, model page and passport, status "Готова к production", display name
   without "исследовательская", no research caveat in the passport, no
   `model_preprod_restricted` warning in a calculation result (that warning is
   now emitted for every result whose lineage is not clean `production_ready`),
   and a neutral business-review limitation in the result view. The model page
   still shows the inherited basis of the OOT check.
6. Unchanged: the portal stays allocation-only and does not decide whether a
   campaign launches or is cancelled; the word "pilot" for the contour (local
   accounts, one machine, no corporate SSO, ADR 0020) stays until those
   decisions change; package A and any restricted or unknown record keep every
   old label; the Excel file name and the registry/package files are not
   touched.

## Consequences

- Contract `schema_version` values stay `1.0.0` / `2.0.0` because backend and
  frontend ship together in one Fin release; the OpenAPI document version moves
  from `1.11.0` to `1.12.0`, as for earlier contract changes, and the generated
  TypeScript types are regenerated in the same change. An older frontend would
  reject the new Home and overview fields, so the two must not be mixed.
- A new model package changes the portal's wording with no code change, and a
  package that fails any part of the record cannot be mislabelled.
- Fin manifests (`model.serving_status`, `model.production_gate`) are written
  by release tooling outside this repository. When Fin is built for a
  production-ready package those fields must carry the package's own recorded
  status instead of the values copied from the previous release; this is
  checked at the Predfin acceptance of the first production-ready package.
- The live-server documents (`CURRENT_TRUTH.md`, `PROJECT_HANDOFF.md`) describe
  package A and stay true until a different package is deployed; they are
  refreshed at that deployment.
- The three fingerprint-bound core files (`model_package.py`,
  `forecast_engine.py`, `validation.py`) are not changed, so existing package
  fingerprints are unaffected.

## Validation

Python tests cover the rule for every missing part, tampered claims in all
three validators, the navigation payloads, the result warning and the result
limitation. Frontend tests cover the parsers (accepted, tampered and
non-boolean claims), the Home and model views and the legacy passport widget.
