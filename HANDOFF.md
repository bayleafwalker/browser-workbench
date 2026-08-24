# Handoff — native slices 1 and 2 (WebKitGTK)

Date: 2026-08-24. Host: Arch Linux, kernel 7.1.9-arch1-2, x86_64.

## Repository

| Field | Value |
| --- | --- |
| Remote | https://github.com/bayleafwalker/browser-workbench |
| Branch | `native/webkitgtk-slice-1` |
| Imported checkpoint tag | `source-checkpoint-v0.2.0` (commit `6343df6`) |
| Checkpoint archive SHA-256 | `0bc2f9a12ae49b42af2165edeaa4dbba54e51708d7effbc9dde148a30f096fe2` |

## What is now true that was not

One real WebKitGTK session runs end to end through the public Browser
Workbench protocol, driven by a connected native adapter process, with raw
engine callbacks and their normalized projections both retained, and a
complete evidence manifest.

`session.create -> page.navigate -> page.await -> page.observe ->
session.export`, against a deterministic loopback fixture, on WebKitGTK 2.52.6
and GTK 4.22.4, headless under Xvfb.

## Slice 2 — engine-truth observation and action

Added on top of slice 1, all executed against the fixture:

| Capability | Provider | How |
| --- | --- | --- |
| `page.act.javascript` | engine | `evaluate_javascript_future`, deferred reply |
| `page.observe.dom` | injected | engine-serialized `outerHTML` via evaluate |
| `page.observe.screenshot` | engine | `snapshot_future`, inline bounded PNG |
| `page.observe.console` | injected | user content manager + console bridge |
| `page.observe.network` | engine (partial) | resource request/response/failure signals |

Verified content, not just green steps: the DOM comes back as the engine's
parsed tree, both console messages are captured and labelled `injected`, the
subresource fetch appears as a request/response pair with status 200, and the
snapshot is a real 1024x768 RGBA PNG.

Three consecutive runs produced byte-identical DOM digests
(`9942f784a4570720`), identical console and network counts, and identical PNG
sizes. That is determinism observed on the native lane, not asserted.

## What is still not true

- The 12-scenario corpus has not run on a native backend. Not once, let alone
  three times, let alone on both variants. The corpus drivers in `corpus.py`
  are written against `MockBackend` directly and would need a backend-neutral
  harness before any native corpus run is possible.
- `stable-persistent` is not implemented. `session.create` rejects persistent
  profiles as `capability_unsupported`.
- Still unwired on the native lane: `page.tabs`, `page.act` pointer and
  keyboard, target enumeration and stale-target rejection,
  `session.checkpoint`, `page.termination`, dialog and permission decision
  tokens, upload and download, and the `accessibility`, `dialogs`,
  `permissions`, and `downloads` projections.
- Playwright oracle and ServoGTK remain unexecuted.
- **Wave 2 is not complete.** This is one session.

## Files changed

Modified:

- `Cargo.toml` — workspace split and dependency corrections (ADR-S1-03, -04)
- `native/webkitgtk-worker/src/native_adapter.rs` — rewritten as a working adapter
- `native/servo-gtk-worker/Cargo.toml` — becomes its own workspace root
- `native/gtk-shell/src/native_shell.rs` — `cargo fmt` only, no semantic change
- `scripts/native_gate.py` — servo lane reached by `--manifest-path`
- `scripts/release_gate.py` — runs the native e2e; reports it separately from the corpus claim
- `src/workbench/runner.py` — conditional lift of the non-mock block
- `tests/test_runner.py` — native-lane guard rewritten (see below)
- `.github/workflows/native.yml` — builds the adapter and runs the e2e
- `CHANGELOG.md`

Added:

- `spec/NATIVE_ADAPTER_CONTRACT_V1.md`
- `src/workbench/native_transport.py`, `src/workbench/webkitgtk_backend.py`,
  `src/workbench/fixture_server.py`
- `scripts/native_e2e.py`, `examples/native-webkitgtk-slice1.json`
- `examples/fixtures/site/{index,next}.html`
- `tests/test_native_transport.py`
- `docs/DECISIONS_NATIVE_SLICE1.md`
- `Cargo.lock` — now meaningful, because the workspace actually builds
- `evidence/native-slice1/`, `evidence/native-webkitgtk-smoke.json`

## Architecture and contract changes

See `docs/DECISIONS_NATIVE_SLICE1.md` for the four decision records:

1. **ADR-S1-01** one ordered channel with an ordinal shared by events and replies.
2. **ADR-S1-02** waiting is host-side, over the recorded event stream.
3. **ADR-S1-03** the ServoGTK lane is excluded into its own workspace.
4. **ADR-S1-04** the pinned `gtk4` gains the `v4_10` feature `webkit6` requires.

## Three checkpoint defects a source-only gate could not see

The 0.2.0 pins had never been compiled together. All three surfaced within
minutes of a real build, and each one alone was fatal to the gating lane:

1. The pinned ServoGTK/Servo revision needs `serde ^1.0.228`; the workspace
   pinned `=1.0.219`. Cargo resolves a workspace as a unit, so a **non-gating**
   research lane made the **gating** lane unbuildable.
2. `webkit6 0.6.1` names `gtk::Accessible` unconditionally; `gtk4 0.11.4` gates
   that type behind its `v4_10` feature, which nothing enabled.
3. `gtk4 0.11.4` requires `glib`/`gio` 0.22; the workspace pinned `=0.21.3` and
   `=0.21.2`. Adapter code now reaches both through the `gtk` re-exports so the
   versions cannot drift apart again.

This is the concrete case for the handoff's own thesis: "source-verified" is a
materially weaker claim than it sounds, and a compile-only gate is not enough.

## Commands and results

Run on this host unless noted. Unabridged.

| Command | Result |
| --- | --- |
| `python3 scripts/verify_package.py` (working tree) | **failed** — 229 verified, 54 digest mismatches. Expected: the tree has moved past 0.2.0. |
| `python3 scripts/verify_package.py` (tag `source-checkpoint-v0.2.0`) | **passed** — 283 verified, 0 errors |
| `PYTHONPATH=src python3 scripts/release_gate.py` | **passed** — `native_vertical_proof: passed`, `native_runtime_claim: false`, `native_corpus_claim: false`; blocked: servo-gtk, playwright |
| `python3 -m unittest discover -s tests` | **passed** — 25 tests (was 23) |
| `cargo fmt --all --check` | **passed** after a mechanical reformat |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **passed** |
| `cargo test --workspace --all-features` | **passed** — 0 tests; the Rust crates are binaries |
| `cargo build -p browser-workbench-webkitgtk-worker --no-default-features --features native` | **passed** |
| `xvfb-run -a python3 scripts/native_gate.py webkitgtk --execute` | **passed** — `native-compile-verified` |
| `xvfb-run -a python3 scripts/native_e2e.py` | **passed** — all 5 steps, all 5 gates, zero deviations |
| `xvfb-run -a python3 scripts/native_e2e.py --spec examples/native-webkitgtk-slice2.json` | **passed** — all 6 steps, all 5 gates, zero deviations |
| slice 1 e2e repeated twice more | **passed** both times, zero deviations |
| slice 2 e2e repeated three times | **passed** all three, zero deviations, identical digests |

`cargo test --workspace --all-features` reporting zero tests is not a silent
pass: neither Rust crate defines a test. The adapter is covered by the Python
transport tests and by the e2e, not by Rust unit tests.

## Evidence

Slice 1 root: `evidence/native-slice1/`. Manifest `complete: true`, root digest
`9424ebbff624e4cef4d7c07159071ccedc9bde4f860eef4d518948baf53c3731`.

Slice 2 root: `evidence/native-slice2/`. Manifest `complete: true`, root digest
`42a2fdddd45b96ca1b87b940894345d2292faadd1c35997c243710d418654a99`, adding a
`screenshots/page-1-g2-01.png` raw artifact (16209 bytes).

Slice 1 artifacts:

| Artifact | Bytes | SHA-256 (16) | Surface |
| --- | ---: | --- | --- |
| `contract/run-spec.json` | 3259 | `e606a6ffdcc867fb` | contract |
| `result.json` | 17322 | `101b57b860cfdc45` | contract |
| `diagnostics/adapter-identity.json` | 222 | `c1da7be15b3a9974` | diagnostic |
| `diagnostics/capabilities.json` | 6404 | `20a7d247be83c208` | diagnostic |
| `traces/raw.ndjson` | 1565 | `5421b484c8168b44` | raw |
| `traces/normalized.ndjson` | 3247 | `fcf9ba5ba2793b94` | normalized |
| `traces/adapter-stderr.log` | 140 | `87d070519e61243f` | raw |
| `exports/export-0001.json` | 6217 | `80057ca4c11038fc` | redacted |

Fixture denominator: `index.html` `ee453fa8…`, `next.html` `38092564…`.

Engine identity as reported at runtime: WebKitGTK `2.52.6`, GTK `4.22.4`,
display backend `GdkX11Display` under Xvfb. WebKitGTK 2.52.6 matches
`UPSTREAM_PINS.json` exactly.

The observed raw sequence was `load-changed:started`,
`resource-load-started`, `load-changed:committed`, `load-changed:finished`,
`title-changed`. The title arrives **after** the load finishes and
`load-changed:finished` carries a null title, so a wait on title that trusted
the finish event alone would have read the wrong value. The host-side wait
sees it correctly because it consumes the same ordered stream the evidence
records.

`adapter-stderr.log` contains two MESA-EGL DRI3 warnings — software rendering
under Xvfb, expected, not a finding.

## Capability reporting deviation

`capabilities.py` marks `verification: runtime` only for the mock backend, so
every WebKitGTK capability still reports `source-audit` even for operations
this run genuinely executed. This **understates** what happened and is left
in place deliberately: a runtime verification class should be earned per
capability by execution, which is its own slice of work, not granted
wholesale because an adapter connected.

## A guard that was rewritten, not removed

`test_runner.py::test_native_lane_is_blocked_not_faked` asserted that the
native lane is *always* blocked. Slice 1 is precisely what invalidates it. It
was replaced by three tests around the invariant that actually matters and
outlives the original symptom:

- `test_native_lane_blocks_rather_than_falling_back_to_the_mock`
- `test_unprobed_native_host_is_blocked`
- `test_backends_without_an_adapter_remain_blocked`

A native lane that cannot run must block. It must never emit mock evidence
under a native backend label. That holds whether or not the host has WebKitGTK.

## Rollback

The imported checkpoint is recoverable and independently verified:

```bash
git checkout source-checkpoint-v0.2.0
# or, without touching the working tree:
git archive source-checkpoint-v0.2.0 | tar -x -C /tmp/checkpoint
python3 /tmp/checkpoint/scripts/verify_package.py /tmp/checkpoint
```

Confirmed during this work: 283 files verified, zero errors, classification
`source-and-mock-verified`, `native_runtime_claim: false`.

To discard slice 1 entirely: `git checkout main`.

Run the release gate in a disposable copy, as the 0.2.0 consolidation did —
it regenerates `evidence/release-0.2.0/`, and those files are part of the
checkpoint's integrity set.

## A fidelity bug the evidence caught

The first slice 2 run produced a 640x480 snapshot from a run spec declaring a
1024x768 viewport. Headless there is no window manager, so GTK's
`default_width`/`default_height` — hints to a WM — were ignored and the engine
laid out at its fallback size. Every snapshot would have quietly disagreed
with its own run spec.

Fixed by expressing the declared viewport as the content view's size request
(ADR-S2-02), and a `viewport-width-divergence` deviation now fires if an
observed snapshot is ever narrower than declared. Snapshots are 1024x768.

This is the kind of defect that only a real run can surface, and the reason
the evidence records observed dimensions alongside declared ones.

## Next eligible slice

Slice 3: target enumeration with generation-scoped identity, `page.act`
pointer and keyboard, and stale-target rejection — the WB-S003 group, and the
largest remaining gap between the native lane and the corpus.

Then, in order: `page.tabs`, dialog and permission decision tokens, upload and
download, `session.checkpoint` and `page.termination`. Only once those exist
does a backend-neutral corpus harness become worth building, and only then can
`stable-ephemeral` run three times per scenario. `stable-persistent` needs a
profile implementation before it can run at all.

Do not raise the release claim past `native_vertical_proof` until those runs
exist. Wave 2 means real WebKitGTK corpus evidence, and it does not exist yet.
