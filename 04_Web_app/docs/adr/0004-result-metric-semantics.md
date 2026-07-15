# ADR 0004: Result Metric Semantics

- Status: Accepted
- Date: 2026-07-15
- Scope: DecisionResult units and browser-facing interpretation

## Context

The completed optimizer artifacts use legacy marketer-report column names. In
particular, `orders_p10_mln`, `orders_p50_mln`, and `orders_p90_mln` contain
raw incremental order counts, while the suffix suggests millions. The result
adapter multiplied those values by one million for Scenarios 1-5. Scenario 6
was enriched from finalist totals, where the unit is explicit, so one result
contained incompatible order scales.

The `avg_basket` target has a second interpretation risk. The posterior effect
is first estimated in RUB per order and then multiplied by the relevant order
denominator. Its campaign total is therefore an incremental-turnover bridge
attributed to the average-basket mechanism, not a predicted change in average
basket per order.

## Decision

1. DecisionResult keeps the schema name and version `decision_result_v1`
   `1.0.0`; the wire shape is unchanged.
2. The result adapter is patched from `1.0.0` to `1.0.1` because the old
   adapter emitted numerically wrong order values.
3. Legacy `orders_*_mln` source fields are read as raw order counts. The
   DecisionResult unit remains `orders`.
4. The basket total uses the explicit unit
   `turnover_bridge_from_avg_basket_rub`. Browser copy must not call this value
   an average-basket delta.
5. Incremental orders remain a diagnostic metric. They do not drive Scenario
   6, automatic recommendations, or campaign launch decisions.
6. ROAS uncertainty shown by future presentation contracts is derived from
   the same turnover posterior quantiles and fixed scenario spend. A frontend
   must not invent an uncertainty range from `roas_p50`.
7. Tests compare DecisionResult values with real completed-run evidence so a
   future misleading source-column suffix cannot silently change units again.

## Consequences

- Existing DecisionResult consumers do not need a structural migration, but
  fixtures and adapter-version pins move to `1.0.1`.
- Any cache created by adapter `1.0.0` must be rebuilt before UI testing.
- Product labels must distinguish incremental turnover, incremental orders,
  and turnover bridge through average basket.
- This change corrects result interpretation only. It does not refit the
  model, rerun optimizer search, or alter MMM mathematics.

## Validation

The contract test suite validates real runs 16, 17, and 18 when the evidence
root is available. It checks raw order-count parity, basket conversion to RUB,
explicit units, schema validity, tamper detection, and path safety.

