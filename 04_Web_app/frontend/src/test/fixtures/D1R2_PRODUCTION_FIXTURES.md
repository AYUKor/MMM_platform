# D1R2 production validation fixtures

These fixtures preserve the sanitized `validation_result_v2` objects used in
the D1R2 production acceptance investigation:

- `d1r2-production-validation_38fc0ce73e4be020fc18.json`: mixed `РФ + Москва`;
- `d1r2-production-validation_b30b5467e757248ef0b1.json`: federal-only control.

The objects were reconstructed read-only from the corresponding production
validation state with the preserved D1R2 target release implementation of the
`view-v2` projection. Authentication data, cookies, secrets and uploaded source
files were not copied. The historical raw HTTP response bytes were not retained;
the checked-in files are pretty-serialized representations of the exact
response objects.

SHA-256 of the checked-in files:

- mixed: `0324d0def1406ecdd27bc51a82a5121028103f3ee02c5e0aa6dd86122eb8fd0a`;
- federal-only: `be991061f4ec15b6f0f5e63c2719efc3fa381519bbbdcd5c231b385f0b9ab2f5`.
