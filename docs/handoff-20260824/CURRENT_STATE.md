# Current state

## 1. Chronology and authority

### Browser — 2026-08-23

The project direction was reframed as:

> A minimal, Linux-first browser workbench whose primary interface is a typed
> observation/action protocol, with humans, agents, and developer tools as
> equal clients.

The backend topology settled on:

| Lane | Role | Status |
| --- | --- | --- |
| WebKitGTK | primary production/interactivity lane | required and gating |
| WebKitGTK stable-ephemeral + stable-persistent | A/B configuration lanes | required for differential release |
| Playwright/WebKit | external reference oracle | required evidence, never product core |
| ServoGTK | independent semantic challenger | experimental and non-gating |
| WPE WebKit | later Wayland/KMS/headless adapter | deferred |

The earlier `hostproto` package remained the research denominator rather than
being rewritten to fit the broader workbench thesis.

### Summarize Browser Session Progress — 2026-08-24

At `18:23 EEST` the user asked the later session to locate the Browser session
and then “Pick up the full scoped work.” The later session produced the saved
`browser-workbench-0.2.0-source-checkpoint.zip` at `19:05 EEST`.

Subsequent transcript state is unavailable because the Work sessions repeatedly
terminated with `Too many requests`. No later durable browser-workbench file was
found, so work after the saved checkpoint is **unconfirmed**, not implicitly
complete.

## 2. Product and research thesis

The stable boundary is the typed protocol and evidence model, not a rendering
engine. The host owns canonical session/page state; engine adapters expose only
what their public APIs can honestly observe or execute.

Key semantics:

- a single-writer lease fences mutation while other clients may observe;
- pages have stable IDs and monotonically increasing generations;
- targets are generation-scoped, so stale actions fail before backend use;
- every accepted action has a causal receipt;
- waits are event/deadline based rather than arbitrary sleeps;
- bounded projections point to addressable raw evidence when data is omitted;
- raw and normalized traces remain separate;
- capability truth records availability, provider, semantic strength, and
  verification source independently;
- comparison refuses mutated candidate inputs and tolerates only declared
  partial-order differences.

The public v1 operation set is:

1. `session.create`
2. `page.navigate`
3. `page.observe`
4. `page.act`
5. `page.await`
6. `session.checkpoint`
7. `session.export`
8. `run.compare`

Permanent exclusions in `0.2.0` include a new renderer, daily-driver claims,
WebExtension compatibility, DRM, sync/password/profile portability,
anti-detection behaviour, silent retries, and WPE implementation.

## 3. What is delivered

### Frozen baseline

`baseline/hostproto-0.1.0/` preserves the earlier pre-implementation research
package and 16-scenario denominator byte-for-byte. Its original charter is an
engine-neutral conformance study, explicitly not a browser product.

### Executable source/mock layer

The new workbench source includes:

- versioned JSON Schemas for run specifications, results, capabilities, events,
  evidence manifests, and comparisons;
- a Python runner, artifact store, comparison logic, capability reporting,
  redaction, evidence manifests, and deterministic mock backend;
- a 12-scenario corpus executed three times per release gate;
- a loopback-only authenticated JSON bridge with a 1 MiB request bound;
- an engine-neutral chrome reducer and static UI;
- GTK shell, WebKitGTK worker, ServoGTK worker, and Playwright oracle source
  boundaries with exact upstream pins;
- source/mock and prerequisite-probe CI workflows;
- release, package-integrity, native-prerequisite, and disclosure gates.

### Pinned implementation identities

- Python `>=3.11` with no runtime third-party package dependency for the
  source/mock layer;
- Rust `1.85`, edition `2024`;
- GTK crate `0.11.4`;
- WebKitGTK Rust binding `webkit6 0.6.1` with `v2_52`;
- ServoGTK revision `d366e11a41e042cc08f94004f28dba67f83b11a5`;
- Playwright `1.62.1` and Node 24 for the oracle lane.

## 4. Exact implementation boundary

The source is more than prose, but materially less than a connected browser:

- `Runner` instantiates only `MockBackend`; every non-mock backend is
  deliberately rejected as `capability_blocked`.
- the GTK shell builds navigation/status/takeover/evidence controls, but the
  buttons are not wired and the content stack contains a placeholder label;
- the WebKitGTK worker installs a useful subset of callbacks and declares
  reload/stop/JavaScript/snapshot calls, but it creates an `about:blank`
  `WebView`, does not join a long-running GTK host lifecycle, and is not
  connected to the Python host or loopback bridge;
- the ServoGTK worker exercises only public URL load/reload/back/forward calls
  and explicitly lacks lifecycle, observation, JavaScript, popup, permission,
  dialog, stop, and termination semantics;
- the Playwright runner can navigate, await, observe, execute JavaScript, and
  record selected events, but it is not installed in the checkpoint
  environment and is not wired into the main Python runner;
- native CI primarily proves prerequisite/compile boundaries. It does not yet
  execute the workbench corpus against WebKitGTK or ServoGTK.

Therefore `0.2.0` is correctly classified as
`source-and-mock-verified`, with `native_runtime_claim: false`.

## 5. Last verified state

Archive integrity:

- archive SHA-256: `0bc2f9a12ae49b42af2165edeaa4dbba54e51708d7effbc9dde148a30f096fe2`;
- ZIP integrity: passed;
- internal package verification: 283 files verified, zero errors.

Independent release-gate rerun:

- source validation: passed;
- Python tests: 15/15 passed;
- chrome reducer tests: 3/3 passed;
- mock corpus: 12 scenarios × 3 repetitions = 36/36 passed, zero retries;
- disclosure scan: passed with zero findings;
- WebKitGTK native probe: blocked, exit 78;
- ServoGTK native probe: blocked, exit 78;
- Playwright oracle probe: blocked, exit 78.

The deterministic corpus semantic digest is
`a8d0c478fcdca32bc9167425744d3a9c54969c7d9e497fc6a48f388399b8a74f`.

## 6. Work that remains

### Required to complete native Wave 2

1. Create a real Git repository and import/tag this checkpoint.
2. Establish a reproducible GTK4/WebKitGTK/Rust target environment.
3. Make the GTK shell own a real `WebView` lifecycle and wire the visible
   controls.
4. Connect the native adapter to the host runner and authenticated bridge.
5. Remove the runner's non-mock hard block only for actually connected,
   capability-probed adapters.
6. Run one small end-to-end WebKitGTK proof through the public protocol.
7. Run both `stable-ephemeral` and `stable-persistent` variants through the
   12-scenario corpus three times, retaining raw/normalized evidence.
8. Review and classify every unsupported, failed, suppressed, or ambiguous
   observation.

### Required before comparative claims

1. Install and pin the Playwright/WebKit oracle; emit compatible evidence.
2. Compare WebKitGTK variants and oracle using immutable inputs and explicit
   tolerances.
3. Attempt ServoGTK only within its public supported surface.
4. Record unreachable scenarios as unsupported rather than adding host-shaped
   success events.

WPE remains deferred.

