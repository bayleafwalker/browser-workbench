# Capability truth

Capability reporting has three independent dimensions:

- availability: `supported`, `partial`, `unsupported`, or `blocked`;
- provider: `engine`, `adapter`, `host`, `injected`, `oracle`, or `mock`;
- semantics: `exact`, `normalized`, `partial`, or `none`.

Verification is also explicit: `runtime`, `source-audit`, `declared`, or `none`. A source audit never upgrades to runtime evidence by declaration; `runtime` is earned per capability, on every backend including the mock, by an operation that completed in a passed run or scenario (`RuntimeLedger`, ADR-S6-01). A run's pre-admission report and its post-run report are both retained. Runtime verification never changes availability: a `partial` capability that ran is runtime-verified as partial. Missing prerequisites convert otherwise supported target-host expectations to `blocked`. `partial` never satisfies a required exact capability gate.

## Backend policy

WebKitGTK is the primary native engine. The pinned Rust binding exposes load lifecycle and failure signals, resource starts, permission/file/dialog hooks, process termination, snapshots, JavaScript evaluation, reload, and stop-loading. DOM, accessibility, and console projections depend partly on injected instrumentation; network semantics are therefore declared partial where WebKitGTK does not expose the same surface as the oracle.

Playwright is an external oracle. Its isolated WebKit browser is valuable for differential evidence, but it is neither WebKitGTK nor a substitute for GTK integration evidence.

ServoGTK is experimental and non-gating. The pinned public widget surface supports URL loading, reload, back, and forward. Its internal IPC contains some lifecycle concepts, but the public widget does not expose enough of them to claim lifecycle/state/DOM/JavaScript/dialog/permission/termination support. Those cells remain unsupported, not mocked.

The authoritative machine-readable matrix is `spec/CAPABILITY_MATRIX_V1.json`; upstream identities are in `native/UPSTREAM_PINS.json`.
