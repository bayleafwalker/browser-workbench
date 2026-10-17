# Browser Workbench 0.2.0 delivery

This package completes the agreed Waves 2–3 source checkpoint while preserving the original hostproto 0.1.0 artifact unchanged.

## Verified here

- frozen 16-scenario hostproto baseline retained;
- separate 12-scenario workbench corpus bound to executable drivers;
- 36/36 deterministic mock repetitions passed with zero retries;
- 15 Python unit/negative/regression tests and 3 chrome reducer tests passed;
- typed run, result, capability, event, evidence, and comparison contracts source-validated;
- authenticated loopback, redaction, content hashing, candidate mutation blocking, and disclosure scanning passed;
- WebKitGTK, ServoGTK, and Playwright identities and source boundaries pinned.

## Archived qualification and current-host limits

The committed `evidence/release-0.2.0/release-gate.json` reports a passed native
WebKitGTK vertical slice and 36/36 runs for each of the `stable-ephemeral` and
`stable-persistent` variants, plus passed differential reports. The adjacent
ServoGTK and Playwright probes are recorded as blocked, not passed. These are
repository-recorded results; package-integrity verification currently fails
with 102 SHA-256 mismatches, including this report and source files. The
committed report is therefore not authenticated by the package checksum set.

A fresh probe in the current workspace is blocked: Rust/Cargo, GTK4 and
WebKitGTK development packages, and a display are absent; the pinned ServoGTK
checkout and Playwright package are absent too. No current-host native or
oracle run was performed. The capability matrix remains the authority for
backend support, and the archived run does not upgrade unsupported ServoGTK
capabilities.

## Resume point

On a target host, follow `docs/NATIVE_BRINGUP.md`, begin with the WebKitGTK primary lane, and retain separate evidence for `stable-ephemeral`, `stable-persistent`, and Playwright/WebKit. Admit ServoGTK only within its declared public capabilities. WPE remains deferred.

The checkpoint report is `evidence/release-0.2.0/release-gate.json`. The
current `PACKAGE_MANIFEST.json` / `SHA256SUMS` pair does not verify the checkout;
regenerate a reviewed source checkpoint before claiming package integrity.
