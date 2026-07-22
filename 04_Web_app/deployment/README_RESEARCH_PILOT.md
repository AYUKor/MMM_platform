# Research Pilot Deployment v1

## What This Layer Does

This is the first deployable, single-server form of the X5 MMM product. It
does not retrain the model and does not reimplement forecast or optimizer
mathematics. It packages and operates the existing chain:

`browser -> Nginx HTTPS/auth -> Product API -> immutable job -> worker -> budget_optimizer.py -> DecisionResult/Excel`

The accepted pilot topology is one Linux VM, one Python process, one worker
and file-backed application state. It is suitable for controlled research
testing. It is not the later multi-node company-contour architecture.

## Why The Model Is Transferred Separately

GitHub contains source code and synthetic fixtures. The trained posterior is
about 430 MB and is a runtime artifact, so it remains outside Git. The model
bundle contains:

- the exact inventory recorded in the selected immutable registration;
- the registration record, activation event and `preprod` channel pointer;
- SHA-256 and size for every transferred file;
- the original panel SHA-256 as provenance.

It deliberately excludes the training panel, raw media/target/control data,
past campaign uploads, optimizer outputs and credentials. `full_lineage`
verification remains the rule in the research/refit environment. The server
uses `serving_bundle`: it verifies the complete registered serving inventory
and package fingerprint while retaining, but not requiring a copy of, the
source-panel hash.

Packaging and startup also enforce a minimum serving-complete inventory:
manifest/config, capability and gate evidence, posterior index and NetCDF
files, fit-design metadata, media scales, target denominators, historical
support bounds and adstock warm start. A package missing any of these files is
rejected before the first marketer calculation rather than failing inside a
job.

## Server Layout

The renderer defaults to:

| Path | Purpose |
|---|---|
| `/opt/x5-mmm/app` | Approved Git checkout and frontend build |
| `/opt/x5-mmm/venv` | Python 3.11+ serving environment |
| `/etc/x5-mmm/research_backend.json` | Non-secret runtime configuration |
| `/var/lib/x5-mmm/state` | Lifecycle records and idempotency indices |
| `/var/lib/x5-mmm/runtime` | Worker attempts and protected technical logs |
| `/var/lib/x5-mmm/artifacts` | Uploaded plans and generated reports |
| `/var/backups/x5-mmm` | Verified runtime backups |

The Python server binds only to `127.0.0.1:8765`. Nginx is the only public
listener and provides HTTPS, basic authentication, upload size limits, SPA
fallback and reverse proxying. Passwords, TLS private keys and model archives
are never generated into or committed with the repository.

## 1. Build The Model Bundle

Run this in the environment that contains the full registered package and its
source panel:

```bash
python -B 04_Web_app/deployment/research_pilot.py package-model \
  --project-root /path/to/full/MMM/project \
  --registry-root /path/to/full/MMM/project/03_Outputs/01_PyMC_outputs/00_Model_registry \
  --channel preprod \
  --expected-package-id pkg_807d3ddbae57a52a_9aacd3beb350725b \
  --output /secure/export/x5-mmm-model-bundle.tar.gz
```

Verify the transferred archive on either side:

```bash
python -B 04_Web_app/deployment/research_pilot.py verify-model-bundle \
  --bundle /secure/export/x5-mmm-model-bundle.tar.gz
```

The current verified package produced 58 transferred files: 55 model
inventory files plus registration, activation event and channel pointer.

## 2. Render Server Configuration

The domain and certificate are infrastructure inputs, not source constants:

```bash
python -B 04_Web_app/deployment/research_pilot.py render \
  --domain mmm.example.company \
  --package-id pkg_807d3ddbae57a52a_9aacd3beb350725b \
  --output-dir /secure/export/x5-mmm-rendered
```

The empty output folder receives:

- backend JSON with the pinned package and `serving_bundle` verification;
- Nginx HTTPS/basic-auth configuration;
- backend, health, retention and backup systemd services/timers;
- production frontend environment (`http` provider, same-origin API);
- a manifest with hashes and confirmation that no secrets are included.

## 3. Install On Ubuntu

1. Create the locked `x5mmm` system user and the server directories. Keep app
   and venv readable/executable by that user, own `/var/lib/x5-mmm` as
   `x5mmm:x5mmm` mode `0700`, and keep `/var/backups/x5-mmm` root-owned mode
   `0700`.
2. Checkout the approved Git commit into `/opt/x5-mmm/app`. On servers
   without internet or GitHub access, transfer a `git archive` tarball of
   the approved commit instead and unpack it into `/opt/x5-mmm/app`.
3. Create `/opt/x5-mmm/venv` with Python 3.11+ and install
   `requirements-runtime-v1.txt`. On offline servers, download the wheel set
   in advance on a connected machine
   (`pip download -r requirements-runtime-v1.txt --platform manylinux_x86_64
   --python-version <target> --only-binary=:all:`) and install with
   `pip install --no-index --find-links <wheel-dir> -r
   requirements-runtime-v1.txt`.
4. Use Node 22, run `npm ci` and the production frontend build with the
   generated frontend environment. The resulting `dist` is served by Nginx.
   On offline servers, build `dist` on a connected machine and transfer the
   built directory; Node is not required on the server.
5. Give `x5mmm` write access to the ignored `03_Outputs` root, then run
   `install-model` as `x5mmm`. Existing files are never silently replaced;
   an identical reinstall is idempotent.
6. Create `/etc/x5-mmm` as `root:x5mmm` mode `0750`; install the rendered
   backend config as `root:x5mmm` mode `0640`. Create the htpasswd file
   separately and obtain the TLS certificate. A private internal CA is an
   acceptable TLS source in a closed network contour: keep the CA private
   key off the server, issue a server certificate whose SAN covers the
   chosen domain, and distribute only the CA root certificate to users.
7. Create `/etc/x5-mmm/backend.env` as `root:x5mmm` mode `0640` with the
   environment-only secrets the backend requires (at minimum
   `MMM_AUTH_SESSION_SECRET`, a random value of 32+ characters). The
   rendered backend unit loads this file through
   `EnvironmentFile=-/etc/x5-mmm/backend.env`; never place secrets in the
   unit file itself.
8. Install the generated Nginx and systemd files, run `daemon-reload`, then
   enable the backend and timers.

Before public access, execute:

```bash
/opt/x5-mmm/venv/bin/python -B /opt/x5-mmm/app/04_Web_app/backend_runtime.py \
  --config /etc/x5-mmm/research_backend.json \
  --project-root /opt/x5-mmm/app \
  --check-only
```

`ready` means code, policy files, channel pointer, package ID, registration,
model inventory and Model Passport are mutually consistent. It does not mean
the model passed sealed OOT or became production-ready.

## 4. Health, Retention And Backup

Health combines `/health`, `/ready` and a free-disk threshold:

```bash
python -B 04_Web_app/deployment/research_pilot.py health \
  --config /etc/x5-mmm/research_backend.json \
  --min-free-gb 20
```

Retention and backup are fail-closed. If an upload, validation or calculation
is non-terminal, maintenance refuses to start. The systemd jobs briefly stop
the backend, recheck idle state, perform the operation and start the backend
again in a `finally` path. This avoids inconsistent file-backed snapshots and
lock contention. Maintenance must be scheduled outside active pilot usage.

Backups include only application `state`, `runtime` and `artifacts`. Source
code comes from Git and the model comes from its separately verified bundle.
To test disaster recovery without touching live state:

```bash
python -B 04_Web_app/deployment/research_pilot.py verify-backup \
  --backup /var/backups/x5-mmm/x5-mmm-runtime-YYYYMMDDTHHMMSSZ.tar.gz

python -B 04_Web_app/deployment/research_pilot.py restore-backup \
  --backup /var/backups/x5-mmm/x5-mmm-runtime-YYYYMMDDTHHMMSSZ.tar.gz \
  --target-root /tmp/x5-mmm-restore-test
```

Restore only accepts an empty target and verifies every file after writing.

## Model Update And Rollback

A quarterly model refresh remains a separate process:

1. collect and validate new media, target and control data;
2. run guarded fit and model gates;
3. register the immutable package and explicitly activate `preprod`;
4. build and verify a new serving bundle;
5. install it on the server without modifying the old package;
6. change the pinned package ID in a newly rendered backend config;
7. run `--check-only`, restart the backend and execute one acceptance campaign.

Rollback means restoring the previous registry channel pointer and matching
pinned backend config, then restarting after preflight. It is not a Git revert
of model artifacts.

## Remaining Boundary

The research pilot still has no PostgreSQL, distributed queue, object storage,
SSO/RBAC or multi-node failover. Sealed OOT remains unavailable, and the
business policy remains `allocation_only`. The product can forecast campaign
incrementality and recommend a budget distribution; it must not claim formal
production validation or decide whether a campaign should be launched.
