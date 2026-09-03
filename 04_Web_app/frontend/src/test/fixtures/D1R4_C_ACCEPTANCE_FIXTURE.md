# D1R4-C acceptance fixture

The D1R4-C regression reuses the already tracked and reviewed D1R2 federal
fixture and replaces only its opaque `validation_id` with the exact D1R4-C id.
No new production response body is copied into Git.

- validation: `validation_1f1be143ce746638c5da`;
- source evidence: local immutable D1R4-C deployment evidence;
- tracked semantic control:
  `d1r2-production-validation_b30b5467e757248ef0b1.json`;
- expected contract: parser PASS, projection PASS, `211 / 175 / 36`,
  `100,000,000 RUB`, 175 map points and `job_creation_allowed=true`.

D1R4-C proved semantic equality after removal of the opaque id. The only other
textual JSON differences were integer versus `.0` spellings, which both parse to
the same JavaScript `number`. The regression therefore locks the exact runtime
object seen by the parser without publishing a duplicate production-derived
payload. It is test-only and is not imported by the production application
bundle.
