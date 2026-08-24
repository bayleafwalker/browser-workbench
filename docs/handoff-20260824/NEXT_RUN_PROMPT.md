# Resume prompt

Use the following as the initial task in local Codex, Claude Code, or another
repository-native agent. Point the agent at this handoff directory.

---

You are resuming Browser Workbench from the durable
`browser-workbench-0.2.0-source-checkpoint.zip`.

## Authoritative state

- The archive SHA-256 must equal
  `0bc2f9a12ae49b42af2165edeaa4dbba54e51708d7effbc9dde148a30f096fe2`.
- `0.2.0` is source-and-deterministic-mock verified, not native verified.
- Preserve `baseline/hostproto-0.1.0/` unchanged.
- The 12-scenario workbench corpus is a separate denominator; do not substitute
  it for the frozen 16-scenario hostproto corpus.
- WebKitGTK is the primary gating backend.
- Playwright/WebKit is an external oracle, never product core.
- ServoGTK is experimental and non-gating.
- WPE remains deferred.
- Do not add a renderer, WebExtensions, DRM, sync/password management,
  anti-detection behaviour, silent retries, or a planner.

## Goal

Turn the source/mock checkpoint into the smallest honest WebKitGTK native
evidence slice. The first completion boundary is one real WebKitGTK session
executed through the public Browser Workbench protocol with raw and normalized
evidence. Do not claim Wave 2 complete until both WebKitGTK variants have run
the full 12-scenario corpus three times.

## Required first actions

1. Verify the archive hash and run `python3 scripts/verify_package.py`.
2. Extract into a new Git repository without editing the imported files.
3. Commit the exact checkpoint and tag it `source-checkpoint-v0.2.0`.
4. Create a native WebKitGTK work branch.
5. Record the actual host inventory: OS, Rust/Cargo, GTK4, WebKitGTK 6.0,
   display protocol/Xvfb, Node, and Playwright availability.
6. Run the existing source/mock release gate before changing code.

## Implementation slice 1 — native vertical proof

Implement only what is required for:

```text
session.create
  -> real WebKitGTK page lifecycle
  -> page.navigate to a deterministic loopback fixture
  -> page.await on engine events
  -> page.observe state/title/URL
  -> causal receipt + raw/normalized trace + manifest
  -> clean teardown
```

The proof must:

- run inside a real GTK application lifecycle;
- connect the native adapter to the host runner through one documented,
  ordered bidirectional process contract;
- make the GTK shell host the actual content view;
- wire only the controls required for the proof;
- remove the runner's non-mock hard block only after capability probing and a
  real adapter connection succeed;
- preserve generation-scoped targets, single-writer fencing, bounded evidence,
  no retries, and explicit unsupported outcomes;
- retain raw engine callbacks before normalization;
- fail or block honestly when prerequisites are absent.

Do not broaden the UI, add more backends, or change the corpus in this slice.

## Verification for slice 1

Run and report exact results for the repository-equivalent of:

```bash
python3 scripts/verify_package.py
PYTHONPATH=src python3 scripts/release_gate.py
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-features
cargo check -p browser-workbench-webkitgtk-worker --no-default-features --features native
xvfb-run -a python3 scripts/native_gate.py webkitgtk --execute --output evidence/native-webkitgtk-smoke.json
```

Add an end-to-end native test command that executes the vertical proof and
produces an evidence directory. A compile-only gate is insufficient.

## Expansion after slice 1 passes

1. Complete remaining WebKitGTK operations required by the 12-scenario corpus.
2. Execute `stable-ephemeral` three times per scenario.
3. Execute `stable-persistent` three times per scenario.
4. Install and execute the pinned Playwright/WebKit oracle with retries off.
5. Produce differential reports against declared partial-order tolerances.
6. Attempt ServoGTK only for its declared supported surface; record gaps as
   unsupported or findings.

## Completion report

Return a durable `HANDOFF.md` containing:

- repository, branch, HEAD, and imported checkpoint tag;
- exact files changed;
- architecture/contract changes and their ADRs;
- commands and unabridged pass/fail/blocked summaries;
- evidence artifact paths and hashes;
- capability changes and verification source;
- known deviations and unresolved findings;
- rollback command and confirmation that the source checkpoint remains
  recoverable;
- next eligible slice.

Do not report native completion when execution was skipped, replaced by a
mock, or inferred from source inspection.

---

