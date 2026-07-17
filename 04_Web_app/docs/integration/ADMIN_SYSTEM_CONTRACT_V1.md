# Admin System Contract v1

`GET /api/v1/admin/system/status` requires `admin.system.read` and returns
`admin_system_status_v1`.

The response is built at request time from real checks:

- application process and published service version;
- calculation state/runtime/artifact directories;
- local worker count and persisted queued/active/failed jobs;
- active model availability and `calculation_allowed` fact;
- marketer-report implementation availability;
- SQLite `PRAGMA quick_check` for auth storage;
- config version and source revision when the runtime preflight supplied it.

Each subsystem is `healthy`, `degraded` or `unavailable`. `overall_status` is
derived from subsystem values and cannot be supplied independently.

The endpoint does not return filesystem paths, hostnames, environment values,
connection strings, secrets or exception messages. A missing model/report is
reported explicitly; the backend does not invent a quality score or a service
version. Every successful view adds `admin_viewed_system_status` to the audit
log.
