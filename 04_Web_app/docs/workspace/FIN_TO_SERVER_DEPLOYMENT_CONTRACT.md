# Fin to Server Deployment Contract

## Boundary

The only permitted local source for a corporate-server deployment is the
verified transfer artifact of one immutable Fin release:

```text
03_Fin/releases/<release_id>/transfer/<verified-artifact>
  -> approved corporate transfer route
  -> server-side checksum
  -> new <release_id>__deployN candidate materialization
  -> complete model/extension structure verification
  -> production-equivalent alternate-port preflight
  -> expected business-state endpoint gates
  -> explicitly authorized service update
```

Test, Predfin, the legacy workspace, an arbitrary Git checkout and a stale
historical bundle are not deployment sources.

## Architecture preserved

This contract does not replace the existing server architecture. Operational steps
remain governed by the accepted `SERVER_RUNBOOK.md` and
`04_Web_app/deployment/README_RESEARCH_PILOT.md`:

- application Git/source and model package remain separate identities;
- offline transfer is used when the server cannot reach GitHub;
- frontend is built for same-origin API access;
- backend binds to loopback behind the documented reverse proxy;
- environment-specific config and secret values are provisioned separately;
- source panel is excluded from serving transfer;
- server runtime state and backups are not release payload.

The copied runbook under the new Test contour is operational evidence, not a reason
to copy infrastructure details or secrets into release manifests.

## Required pre-deployment evidence

- selected release ID equals the intended `CURRENT_RELEASE.json` target;
- transfer artifact SHA-256 and byte size match Fin evidence;
- every transfer checksum passes after delivery;
- application commit/tree match the release manifest;
- model package, registry and extensions match the frozen closure;
- no secrets are embedded in the artifact;
- environment-specific secrets/config are supplied through the approved server
  process;
- backend `--check-only` succeeds in serving-bundle mode;
- frontend build identity and same-origin configuration are verified;
- rollback source and acceptance checklist are identified before service changes.

## Server candidate materialization

The Fin release ID and a server materialization attempt are different identities.
The immutable Fin release remains `<release_id>`; every server candidate uses a new
name such as `<release_id>__deploy2`. Reusing or overwriting an existing candidate
is forbidden.

Use the reviewed D1R.1 `04_Web_app/deployment/server_release.py` at its recorded Git
commit and SHA-256. The materializer is deployment control tooling, not a new source
of application or model files. Candidate content still comes exclusively from the
verified Fin transfer, so using the corrected materializer does not change the
application commit/tree or model identity of an existing Fin.

After the transferred archive SHA-256/bytes and safe extraction have been verified,
run the following against the extracted release root:

```bash
python -B 04_Web_app/deployment/server_release.py verify-transfer \
  --fin-root /var/tmp/<verified-transfer>/<release_id>

python -B 04_Web_app/deployment/server_release.py materialize \
  --fin-root /var/tmp/<verified-transfer>/<release_id> \
  --releases-root /opt/x5-mmm/releases \
  --candidate-id <release_id>__deploy2
```

The materializer verifies the complete extracted transfer and resolves
`package_id` by agreement among the release manifest, model closure, registry
registration/channel and package-artifacts manifest. It does not derive identity
from a directory name, `current`, or a hard-coded package. The transformation is
driven by every `MODEL_CLOSURE.json` row:

```text
Fin source                 server candidate target
release_relative_path  -> source_relative_path
```

For package extensions this necessarily produces:

```text
model/package_extensions/package_artifacts_manifest_v1.json
  -> 03_Outputs/01_PyMC_outputs/00_Model_registry/
     package_artifacts/<package_id>/package_artifacts_manifest_v1.json

model/package_extensions/historical_geo_budget_v1/*
  -> 03_Outputs/01_PyMC_outputs/00_Model_registry/
     package_artifacts/<package_id>/historical_geo_budget_v1/*
```

All work happens in a new sibling staging directory. The final candidate appears
only after application Git identity, frontend dist, complete model closure and all
five package-extension files pass path, SHA-256, byte and semantic binding checks.
An existing candidate is never replaced and a failed partial staging directory is
removed without touching any completed release.

If the service user needs Git metadata at runtime, allowlist only this exact new
candidate in the dedicated `GIT_CONFIG_SYSTEM` file before its preflight. A wildcard
`safe.directory=*` remains forbidden.

## Production-equivalent preflight and business gates

Run the candidate through a relative `current`-like pointer, isolated shared state
and an unused loopback port. The command below uses a sanitized HTTPS public origin,
the research-pilot runtime profile, `serving_bundle`, the same registry/package
lookup semantics and the candidate's policy paths. It never reads production state
or secrets and removes its temporary runtime directory on exit:

```bash
python -B 04_Web_app/deployment/server_release.py preflight \
  --fin-root /var/tmp/<verified-transfer>/<release_id> \
  --candidate-root /opt/x5-mmm/releases/<release_id>__deploy2 \
  --work-root /var/tmp/<release_id>__deploy2-preflight \
  --port <unused-loopback-port> \
  --python-executable /opt/x5-mmm/venv/bin/python
```

PASS requires all of the following in one run:

- exact application commit/tree and package ID;
- complete frontend dist and 63-file model closure;
- package extensions `5/5`, with zero missing, unexpected, SHA or byte mismatch;
- `/health = ok` and `/ready = ready`;
- authenticated `GET /api/v1/model/historical-geo-budget` returns HTTP 200,
  `record_origin=verified_model_package_artifact`, `status=available`, the expected
  package/artifact identity, full expected coverage and exact manifest-backed
  business totals.

HTTP 200 and a schema-valid response are not enough when a contract supports
`available`, `partial` and `unavailable`. Deployment acceptance must assert the
business state expected by the Fin evidence. A schema-valid `unavailable` response
is a deployment failure.

Do not switch `current` after only `/health` and `/ready`. The current pointer may be
changed only after the full materialization verification, production-equivalent
preflight and all release-specific business-state gates pass. Any failure leaves
the current production release unchanged.

Activation then requires a final zero-work drain, fresh verified persistent-state
backup, atomic relative-symlink switch, backend restart, health/readiness,
origin/external/browser frontend asset identity and release-specific product
acceptance. `index.html` must revalidate; hashed JavaScript/CSS may remain immutable.
After complete PASS, write and seal the release-local `SERVER_RELEASE.json` as
root-owned read-only evidence. Do not mutate the immutable Fin manifest to reflect
the later server state. The full joined process is in
`END_TO_END_CHANGE_LIFECYCLE.md`.

## Authorization and observation

Deployment requires a separate explicit milestone covering transfer, service
changes, health/browser verification and rollback. C2.5 performs none of those
actions and does not assert current live-server HEAD or health.

D1R5 is the first live proof of this contract: on 2026-09-03 it accepted deploy5
for Fin release
`release_9355c6c8fdaf_807d3ddbae57_ed8a6c6c7642_77973f4d424c`, while preserving
the separate restricted model status and all persistent state.

The current Fin application is approved, while its model remains
`preprod_restricted` with `production_gate = not_passed`. Deployment approval must
not be presented as statistical production approval.
