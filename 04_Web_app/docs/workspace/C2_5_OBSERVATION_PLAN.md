# C2.5 Observation Plan

## Purpose

The four-contour workspace is operationally adopted, but destructive cleanup must
wait until the workflow proves itself on a real next milestone. Observation is not
passive waiting: it records whether each handoff remains reproducible without the
legacy workspace.

## Observation period

Minimum duration: through one complete real milestone and its next Fin release.
The selected proof milestone is B1/B2 Federal Geo Allocation.

Required route:

```text
00_Data
  -> 01_Test B1 audit and B2 implementation/research
  -> reviewed application/data/model candidate
  -> 02_Predfin acceptance
  -> new immutable 03_Fin release
```

No step may use the old workspace as a fallback.

## Evidence to collect

### Data

- raw/source manifest and immutable input hashes;
- B1 evidence for the existing federal-to-geo transformation;
- B2 code/config identity and spend/date/geo reconciliation;
- versioned panel identity if the panel changes.

### Development

- Test branch/PR identity;
- tests and reproducible commands using only canonical paths;
- path scan showing no new user-specific hardcoded roots;
- explicit separation of observed transformation evidence from new assumptions.

### Predfin

- exact approved application commit/tree;
- complete model/extension closure if changed;
- regression, security, path-independence and runtime acceptance;
- machine-readable Fin handoff.

### Fin

- new deterministic release ID;
- immutable release and complete checksums;
- independently verified transfer artifact;
- unchanged model production status unless a separate gate milestone approves a
  change.

## Observation outcomes

Observation passes only if:

- the complete route runs without legacy fallback;
- no accepted source is overwritten;
- GitHub main remains the application approval boundary;
- Predfin rejects unreviewed experiment output;
- the new Fin release is created rather than modifying the current release;
- deployment, if later authorized, uses Fin only;
- newly introduced hardcoded absolute paths equal zero.

Any fallback to the old workspace, manual in-place Fin repair, hidden artifact copy
or unrecorded identity breaks the observation period and requires remediation plus a
new full proof cycle.

## C3 gate

C3 cleanup is not authorized during observation. After a successful B1/B2 release,
a separate review may classify retained material into `SAFE_GENERATED`, `ARCHIVE`,
`LEGACY_REFERENCE`, `DELETE_CANDIDATE` and `MANUAL_DECISION`. Classification is not
deletion; destructive action still requires explicit approval and an exact target
list.
