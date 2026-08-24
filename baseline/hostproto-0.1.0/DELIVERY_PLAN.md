# Delivery plan

## Estimate

Budget **8–16 focused weekends**, roughly 2–4 months of weekend work, for contract through comparative evidence. This is a planning range, not a promise that `servo-gtk` will acquire missing semantics out of politeness.

The work stops at every release boundary unless the next wave is explicitly selected.

## Wave 0 — freeze the experiment

**Goal:** turn this package into an internally consistent repository baseline.

### Work

- Choose repository name and license.
- Import this package unchanged as the initial design baseline.
- Validate JSON schemas and YAML corpus in CI.
- Assign schema and document ownership.
- Record unresolved questions without implementing answers.
- Tag `design-v0.1.0`.

### Gate

- Denominator, protocol, scenarios, and non-goals agree.
- Every scenario cites defined capabilities, methods, events, and outcomes.
- No document implies a daily-use browser or extension runtime.
- Independent review finds no success condition that requires an unstated feature.

### Rollback

Documentation-only. Amend through a reviewed package version; retain the original tag.

**Estimate:** 1–2 weekends.

## Wave 1 — executable contract with mock backend

**Goal:** prove the protocol and harness independently of external engines.

### Work

- Rust workspace and canonical state reducer.
- Envelope and evidence validation.
- JavaScript `window.hostproto` facade with transport-neutral tests.
- Minimal reference chrome.
- Deterministic fixture server.
- Mock adapter with virtual clock and failure injection.
- Scenario runner, raw/normalized trace writers, and report generator.

### Gate

- Every scenario completes against the mock with expected pass or declared conditional outcome.
- Reducer replay is deterministic.
- Every request terminates exactly once under success, error, cancellation, and deadline paths.
- Late and duplicate callbacks appear raw and produce explicit suppression records.
- Evidence manifest hashes every artifact.
- Chrome source scan contains no backend identifiers.

### Release

`contract-v0.1.0`

### Rollback

Delete no evidence. Revert implementation to the contract tag; incompatible semantic changes require `0.2`.

**Estimate:** 2–4 weekends.

## Wave 2 — WebKitGTK evidence

**Goal:** establish the first real adapter and publish a single-engine evidence release.

### Work

- Pin WebKitGTK, GTK, Rust bindings, and environment.
- Map raw callbacks without changing protocol or scenarios.
- Implement the chrome facade transport and native content views.
- Execute every scenario three times.
- Classify all failures, suppressions, and ambiguous mappings.
- Produce one supporting screenshot and complete evidence bundle.

### Gate

- Same compiled chrome bundle is used for all repetitions.
- All supported capability declarations are justified by traces.
- No missing raw segment underlies a pass result.
- Findings distinguish adapter defects from WebKitGTK behavior.
- A reviewer can replay normalized traces to the reported final states.

### Release

`webkitgtk-evidence-v0.1.0`

### Rollback

Adapter changes may be reverted without changing the contract. Failed scenarios and evidence remain in the release candidate or are explicitly invalidated; they are not edited into passing form.

**Estimate:** 2–4 weekends.

## Wave 3 — Servo evidence

**Goal:** run the unchanged chrome and contract through a pinned servo-gtk adapter.

### Work

- Pin `servo-gtk`, Servo, GTK, graphics, and build dependencies.
- Establish whether an honest chrome bridge is possible.
- Map lifecycle and navigation observations.
- Execute every reachable scenario three times.
- Mark blocked or unsupported scenarios without compensating chrome changes.
- Produce the comparative report against WebKitGTK evidence.

### Gate

- Chrome bundle hash matches the WebKitGTK evidence release.
- Protocol and scenario versions match.
- All private patches are recorded and bounded.
- Comparative report evaluates scenario oracles and capability declarations, not trace cosmetics.
- Any impossible bridge or semantic mapping is recorded as a first-class result.

### Release

`servo-evidence-v0.1.0` and `comparison-v0.1.0`

### Rollback

Abandon private engine work if the bridge requires a long-lived fork. Preserve the blocked result and return to the released contract; do not create an engine-specific UI.

**Estimate:** 3–6 weekends.

## Wave 4 — selective upstream reductions

**Goal:** turn useful confirmed findings into minimal reproductions.

This is a per-finding wave, not a blanket commitment.

### Work

- Select one finding that meets the upstream threshold.
- Reproduce outside hostproto.
- Minimize dependencies and code.
- Verify current upstream state and existing issues.
- Prepare report or patch for user authorization.

### Gate

- Reproduction does not depend on hostproto's canonical reducer or chrome.
- Expected and observed behavior are precise.
- Disclosure review passes.
- No external issue or patch is submitted without explicit authorization.

### Release

`repro-HP-Fxxxx-v1`

### Rollback

If reduction removes the behavior, reclassify the finding as adapter or unresolved. Keep the failed reduction notes.

**Estimate:** 0.5–2 weekends per selected finding.

## Not scheduled

- Additional browser UX.
- A third rendering engine.
- Persistent sessions or profiles.
- WebExtensions.
- Distribution packaging.
- Daily-driver testing.

Any of these requires a new charter and value argument. “The code is already open” is not one.
