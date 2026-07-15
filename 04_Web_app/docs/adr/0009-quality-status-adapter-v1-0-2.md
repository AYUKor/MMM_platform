# ADR 0009: Quality Status Adapter V1.0.2

- Status: Accepted
- Date: 2026-07-15
- Scope: marketer report quality display values to DecisionResult codes

## Context

The first real localhost optimizer job completed calculation and Excel
generation but DecisionResult publication failed closed because the report
quality label `Сопоставимо с историей` was not present in the adapter mapping.
The report generator assigns this label quality rank zero when support and
policy checks do not add uncertainty or manual-review conditions.

## Decision

Adapter `1.0.2` adds these generator-owned mappings:

- `Сопоставимо с историей` -> `reliable`;
- `Расчет невозможен` -> `not_calculated`.

No fuzzy matching or default fallback is introduced. Any other unknown display
value still raises `OptimizerResultAdapterError` and blocks publication.

## Consequences

The browser receives stable language-independent codes while preserving the
source Russian display text. Adapter, schema, fixtures and tests share the same
`1.0.2` pin. MMM calculations and report quality rules are unchanged.
