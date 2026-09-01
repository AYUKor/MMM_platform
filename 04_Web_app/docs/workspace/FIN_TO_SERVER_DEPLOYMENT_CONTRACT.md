# Fin to Server Deployment Contract

## Boundary

The only permitted local source for a future corporate-server deployment is the
verified transfer artifact of one immutable Fin release:

```text
03_Fin/releases/<release_id>/transfer/<verified-artifact>
  -> approved corporate transfer route
  -> server-side checksum and preflight
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

## Authorization and observation

Deployment requires a separate explicit milestone covering transfer, service
changes, health/browser verification and rollback. C2.5 performs none of those
actions and does not assert current live-server HEAD or health.

The current Fin application is approved, while its model remains
`preprod_restricted` with `production_gate = not_passed`. Deployment approval must
not be presented as statistical production approval.
