# Rollback and recovery

The deliverable is an additive source checkpoint. The original hostproto 0.1.0 package is copied unchanged under `baseline/hostproto-0.1.0`, so protocol work can continue even if the Wave 2–3 implementation is rejected.

## Rollback points

1. Verify the release ZIP against `SHA256SUMS` and `PACKAGE_MANIFEST.json` before extraction.
2. Keep the archive immutable; do not edit evidence in place.
3. To return to the spec-only boundary, use `baseline/hostproto-0.1.0` directly.
4. To disable one runtime lane, remove it from the selected run spec and capability gate; do not alter its historical evidence.
5. To recover a failed session, retain partial traces, resume only from a verified checkpoint, and issue a higher writer lease epoch.

Candidate evidence must never be “fixed” after a comparison begins. Produce a new candidate directory and comparison report instead. Redacted exports are derivatives; the restricted raw evidence manifest remains the integrity root.

After extraction, verification is a standard-library-only command:

```sh
python scripts/verify_package.py .
```
