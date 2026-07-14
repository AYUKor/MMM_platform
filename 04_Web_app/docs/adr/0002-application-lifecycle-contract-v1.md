# ADR 0002: Application Lifecycle Contract V1

- Status: Accepted
- Date: 2026-07-15
- Scope: upload, validation, asynchronous calculation, progress, and safe errors

## Context

DecisionResult v1 defines what the browser may read after a forecast and
optimization job has completed. It does not define how an uploaded campaign
becomes a validated immutable job, how a worker reports progress, or how a
failure is represented before a result exists.

Without a separate lifecycle contract, an implementation could collapse file
parsing, model validation, calculation state, and UI progress into one enum.
That would make states such as "file parsed but campaign invalid" or
"cancellation requested but worker still running" impossible to represent
truthfully. It would also encourage the API to infer machine behavior from
localized display text or from the presence of files in a directory.

## Decision

### 1. Six resources form lifecycle v1

The application uses six independently versioned records in
`application_lifecycle_v1`:

- `campaign_upload_v1`: immutable source-file acceptance and parse outcome;
- `validation_result_v1`: campaign normalization, capability validation,
  reconciliation, warnings, and permission to create a job;
- `decision_job_v1`: immutable calculation request, lineage, policies, seeds,
  artifact hashes, and current execution state;
- `job_event_v1`: append-only audit event for every legal job-state transition;
- `progress_event_v1`: append-only stage and counter update for the browser;
- `application_error_v1`: machine-readable failure with safe user text and
  optional affected rows or model cells.

The wire representation is Draft 2020-12 JSON Schema version `1.0.0`. The
Python module supplies typed immutable records plus semantic validation and a
`JSON object -> typed record` parser.

### 2. Upload, validation, and execution remain separate state machines

Upload states are:

```text
received -> parsed | rejected
```

Validation states are:

```text
running -> valid | invalid
```

Job states are:

```text
queued -> running -> succeeded | failed | timed_out
                    -> cancel_requested -> cancelled | succeeded | failed | timed_out
```

`parsed` means that a canonical candidate payload exists. It does not mean the
campaign is supported by the selected model. Only a `valid` validation with no
blocking issues can permit immutable job creation.

`cancel_requested` is non-terminal. A late cancellation request can race with
normal completion, so the worker may still report `succeeded`, `failed`, or
`timed_out`; only `cancelled` confirms that calculation stopped because of the
request.

### 3. Lifecycle state and progress are different concepts

Job state answers whether work is queued, running, or terminal. Progress
answers what the worker is currently doing. Stable progress stages are:

```text
prepare, forecast, benchmarks, scenario6, final_scoring, report
```

Progress events may contain a localized message, percentage from 0 to 100, and
named counters such as campaigns completed or Scenario 6 candidates evaluated.
They do not create new job states and cannot mark a job successful.

### 4. Machine codes drive behavior; display text is presentation only

Every state and failure has a stable machine code and separate user-facing
text. API branching, persistence, retries, and tests use the machine code.
Russian display text can change without changing the contract version and must
never be parsed to recover application behavior.

### 5. Jobs are immutable execution definitions

A DecisionJob records selection provenance and pins:

- normalized plan and daily flighting artifact identities and hashes;
- registry channel provenance or explicit-package mode, plus the resolved
  immutable package ID and expected package fingerprint in both modes;
- optimizer, gate, and business-policy versions and hashes;
- search and finalist posterior draws;
- deterministic seeds;
- source-code reference and idempotency key.

Resolving only a mutable channel name is prohibited: a registry pointer can
change while a job waits in the queue. The worker must use the package pin from
the job and fail if its registration, fingerprint, inventory, or serving policy
cannot be verified; it must not silently substitute the channel's newer
package.

Lifecycle updates change the stored status and append events. They do not
rewrite the job inputs. A retry creates a new execution attempt and preserves
the earlier audit history.

### 6. Errors are browser-safe and operationally actionable

ApplicationError exposes a stable code, component, stage, category, severity,
retryability, safe display text, support reference, and optional affected rows
or cells. It does not expose stack traces, credentials, workstation paths, raw
exception dumps, or model internals to the browser.

Detailed server diagnostics remain in protected logs linked by the opaque
support reference. `failed` and `timed_out` jobs require a terminal error;
`cancelled` is not misclassified as an error.

### 7. Artifact references are path-safe

Lifecycle records contain opaque artifact IDs, SHA-256 hashes, sizes, media
types, filenames, and canonical relative storage keys. Absolute paths,
`file://` references, parent traversal, and Windows backslash keys are rejected.

### 8. Fixtures prove contract behavior, not model quality

The happy-path and failure-path fixtures are explicitly marked
`synthetic_fixture`. They contain no real package ID, campaign, metric, or
workstation path. They are suitable for API, worker, and frontend contract
tests but are not evidence that MMM calculations or optimizer decisions are
correct.

## Validation Boundary

JSON Schema validates the transport shape, primitive types, enums, formats, and
safe artifact-reference patterns. Python semantic validation additionally
checks rules that are awkward or impossible to express portably in JSON Schema,
including timestamp order, budget reconciliation, legal state combinations,
job transitions, model-selector exclusivity, and progress counter bounds.

Any Python API or worker entry point must call `parse_lifecycle_contract()` or
`validate_lifecycle_payload()` before persistence or execution. Other
implementations must reproduce the same semantic test cases rather than rely on
schema validation alone.

## Consequences

- The worker can now be implemented against a stable input and event contract.
- The future API can expose lifecycle state without reading calculation folders
  or parsing CLI output text.
- The frontend can render upload, validation, queue, progress, cancellation,
  success, and failure states before any real server infrastructure is chosen.
- PostgreSQL tables, queue messages, and HTTP endpoints must preserve these
  resource boundaries instead of introducing a second lifecycle vocabulary.
- Breaking field or semantic changes require a new contract version and fixture
  migration; display-text changes do not.

## Non-Goals

This ADR does not implement a worker, HTTP route, queue, PostgreSQL schema,
object-storage provider, frontend, authentication, or deployment. It does not
run forecast or optimizer calculations and does not change MMM mathematics.

## Related Documents

- `04_Web_app/docs/adr/0001-source-of-truth-and-boundaries.md`
- `04_Web_app/contracts/application_lifecycle_v1.py`
- `04_Web_app/contracts/application_lifecycle_v1.schema.json`
- `04_Web_app/tests/test_application_lifecycle_v1.py`
- `04_Web_app/PROJECT_HANDOFF.md`
- `04_Web_app/CURRENT_TRUTH.md`
