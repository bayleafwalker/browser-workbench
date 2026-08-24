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

## Not claimed here

This host has no Rust/Cargo, GTK4/WebKitGTK development stack, graphical display, pinned ServoGTK checkout, or installed Playwright package/browser. Their prerequisite probes are retained as `blocked`, exit code 78. There is no native compilation or three-repetition engine evidence in this archive, and the package does not imply either.

## Resume point

On a target host, follow `docs/NATIVE_BRINGUP.md`, begin with the WebKitGTK primary lane, and retain separate evidence for `stable-ephemeral`, `stable-persistent`, and Playwright/WebKit. Admit ServoGTK only within its declared public capabilities. WPE remains deferred.

The authoritative checkpoint outcome is `evidence/release-0.2.0/release-gate.json`; integrity is rooted in `PACKAGE_MANIFEST.json` and `SHA256SUMS`.
