# Data Lifecycle

## Decision boundary

`<MMM_WORKSPACE_ROOT>/00_Data` is the canonical local data contour. Data acceptance
does not
by itself approve a model, application release or deployment.

## Layers

### Raw

Agency exports and other source files enter a versioned raw/source area. Raw files
are immutable. A correction is a new source version with its own manifest, not an
overwrite of the accepted file.

### Prepared

Prepared datasets are reproducible transformation outputs. Each output must record:

- input artifact identities and SHA-256 values;
- preparation code commit and configuration identity;
- transformation parameters and execution timestamp;
- population, grain, date coverage and join/reconciliation checks;
- row/column counts and rejected-record handling.

Prepared output is never relabelled as raw evidence.

### Panels

Every accepted panel is versioned. Its manifest must contain at least:

- artifact path relative to `00_Data`;
- period start and end;
- row and column counts;
- geography field and geography count;
- SHA-256 and byte size;
- source manifest identity;
- preparation code commit/config identity;
- target/control/media schema version;
- DQ and reconciliation results;
- intended use and known limitations.

An accepted panel is not overwritten. A refresh creates a new panel artifact and a
new manifest while preserving the prior panel and its model lineage.

## Quarterly update flow

```text
new agency/raw data
  -> immutable source registration in 00_Data
  -> reproducible preparation
  -> DQ, coverage and reconciliation
  -> versioned panel candidate
  -> 01_Test model/research validation
  -> explicit panel acceptance
```

No DWH query or panel rebuild is implicit in this contract. Execution requires an
explicitly authorized milestone and a run card.

## Current panel identity

- Relative path:
  `<MMM_WORKSPACE_ROOT>/00_Data/panels/02_2025_2026Q1_second_pass/panel_final_v3.parquet`.
- SHA-256: `9aacd3beb350725be483145bf955dbc26f9b5dd7a510708c4ae4ec700e4b4552`.
- Size: 49,864,455 bytes.
- Shape: 308,886 rows and 109 columns.
- Coverage: 220 geographies, 2025-01-01 through 2026-05-31.
- Model training window: 2025-01-01 through 2026-03-20.

The panel hash is release provenance. The full panel is not included in the Fin
transfer bundle because serving does not require it.

## Promotion rules

- `00_Data -> 01_Test` supplies immutable/versioned inputs to research.
- A new panel does not automatically replace the panel bound to an accepted model.
- Predfin receives only a reviewed model candidate bound to an exact panel hash.
- Fin records panel identity but remains panel-free unless a future serving runtime
  proves that the panel is required and a new policy explicitly approves transfer.
