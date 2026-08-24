# browser-workbench

A minimal, Linux-first browser workbench whose primary interface is a typed
observation/action protocol. Humans, agents, command-line tools, and developer
integrations are equal clients of the same runner.

This repository preserves the frozen `hostproto` 0.1.0 research denominator
under `baseline/hostproto-0.1.0/` and adds the separate executable workbench
corpus. The old 16 scenarios are not rewritten to make the new product thesis
fit; the new 12 scenarios test the runner, evidence, authority, and comparison
surface.

## Status

**Source release:** `0.2.0`

- Core runner, deterministic mock backend, comparison logic, redaction,
  evidence manifests, release gates, reference bridge, and 12-scenario corpus
  are executable without third-party Python packages.
- WebKitGTK, GTK shell, ServoGTK, and Playwright boundaries are versioned and
  capability-honest.
- Native evidence is not claimed unless it was produced on a host with the
  pinned toolchain and display stack. A missing toolchain yields `blocked`, not
  an attractively coloured approximation of success.

## Backend lanes

| Lane | Role | Release effect |
| --- | --- | --- |
| WebKitGTK | Primary interactive backend | Required for a native evidence release |
| Two WebKitGTK variants | A/B configuration validation | Required for differential release |
| Playwright | Chromium/WebKit/Firefox oracle | Reference evidence, never product core |
| ServoGTK | Independent semantic challenger | Experimental and non-gating |
| WPE WebKit | Later deployment adapter | Not implemented in 0.2.0 |

ServoGTK is intentionally bounded to the public surface of the pinned
`nacho/servo-gtk` revision. Lifecycle, semantic observation, JavaScript,
stop-loading, popup, and termination semantics remain `unsupported` until the
public embedding surface actually supplies them.

## Quick start

```bash
PYTHONPATH=src python3 scripts/validate_source.py
PYTHONPATH=src python3 -m workbench.cli corpus --output evidence/mock
PYTHONPATH=src python3 -m workbench.cli run examples/mock-run.json --output evidence/example
PYTHONPATH=src python3 scripts/release_gate.py
```

Run with the repository root on `PYTHONPATH` (the scripts do this themselves),
or install locally:

```bash
python3 -m pip install -e .
```

Native and oracle gates are deliberately separate:

```bash
PYTHONPATH=src python3 scripts/native_gate.py webkitgtk --output evidence/native-webkitgtk.json
PYTHONPATH=src python3 scripts/native_gate.py servo-gtk --output evidence/native-servo-gtk.json
PYTHONPATH=src python3 scripts/native_gate.py playwright --output evidence/oracle-playwright.json
```

On a non-native container this returns exit code `78` and a machine-readable
blocked result. See `docs/NATIVE_BRINGUP.md` for the target-host path.

## Protocol

The public v1 operations are:

- `session.create`
- `page.navigate`
- `page.observe { projection, since_event, max_bytes }`
- `page.act { intent, target, preconditions }`
- `page.await { conditions, deadline_ms }`
- `session.checkpoint`
- `session.export`
- `run.compare { baseline, candidate, tolerances }`

Every accepted action returns a causal receipt. Observations are bounded and
loss-explicit, raw evidence remains addressable without rerunning the action,
targets are scoped to a page generation, and comparisons refuse candidate-side
mutation.

## Repository map

- `spec/` — workbench protocol, runner contract, capability matrix, and frozen
  12-scenario corpus.
- `schemas/` — versioned JSON Schemas for run specs, results, capabilities,
  events, evidence, and comparisons.
- `src/workbench/` — executable control plane and deterministic mock backend.
- `chrome/` — engine-neutral minimal UI and state reducer; the authenticated
  bridge lives in `src/workbench/bridge.py`.
- `native/` — pinned GTK/WebKitGTK/Servo source boundaries and capability
  manifests.
- `tests/` — unit, negative, regression, corpus, and release-validation tests.
- `evidence/` — generated mock and environment evidence; native evidence is
  never prefilled.
- `baseline/hostproto-0.1.0/` — byte-preserved design baseline and rollback
  denominator.

## Permanent exclusions

- A new rendering engine.
- Daily-driver browser claims.
- Chrome/Firefox extension compatibility.
- DRM, sync, password management, or profile portability.
- Anti-detection or anti-bot behaviour.
- A planner that decides what should be tested.
- Silent retries, hidden capability emulation, or edited evidence.
- WPE implementation in this release.

The runner executes a declared validation plan. It does not become a planner
because someone gave the loop a confident name.
