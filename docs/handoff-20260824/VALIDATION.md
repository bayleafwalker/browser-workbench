# Validation record

Consolidated at `2026-08-24T17:18:28Z` (`20:18:28 EEST`).

## Source checkpoint

```text
file: browser-workbench-0.2.0-source-checkpoint.zip
size: 266387 bytes
sha256: 0bc2f9a12ae49b42af2165edeaa4dbba54e51708d7effbc9dde148a30f096fe2
classification: source-and-mock-verified
native_runtime_claim: false
```

## Commands rerun

After extracting the archive:

```bash
python3 scripts/verify_package.py
```

Result:

```json
{
  "classification": "source-and-mock-verified",
  "errors": [],
  "native_runtime_claim": false,
  "status": "passed",
  "verified_files": 283
}
```

The release gate was run in a disposable copy so its regenerated evidence did
not alter the integrity-checked extraction:

```bash
PYTHONPATH=src python3 scripts/release_gate.py
```

Result:

```json
{
  "status": "passed",
  "claim": "source-and-mock-verified",
  "native_runtime_claim": false,
  "native_or_oracle_blocked": [
    "webkitgtk-native-probe",
    "servo-gtk-native-probe",
    "playwright-oracle-probe"
  ]
}
```

Detailed counts from the rerun:

| Gate | Result |
| --- | --- |
| source validation | pass |
| Python unit/negative/regression | 15/15 pass |
| chrome reducer | 3/3 pass |
| deterministic mock corpus | 36/36 pass; 12 scenarios × 3; zero retries |
| disclosure scan | pass; zero findings |
| WebKitGTK | blocked, exit 78 |
| ServoGTK | blocked, exit 78 |
| Playwright/WebKit oracle | blocked, exit 78 |

## Why the native lanes are blocked here

The checkpoint environment lacked Rust/Cargo, GTK4 and WebKitGTK development
packages, a display/Xvfb target, the pinned ServoGTK checkout, and the installed
Playwright package/browser. A blocked prerequisite probe was accepted only as
truthful release metadata; it was not converted into a native pass.

## Not verified

- native compilation in this consolidation environment;
- a live GTK window or WebKitGTK content view;
- native adapter/host transport;
- WebKitGTK, ServoGTK, or Playwright scenario execution;
- a Git commit, branch, tag, CI run, or remote repository containing the
  checkpoint;
- any unsaved work performed after the archive was created.

## Disclosure classification

| Class | Finding |
| --- | --- |
| credentials/secrets | none found |
| customer or employer-confidential | none found |
| reachable endpoints | none; bridge is loopback-only by design |
| sensitive identifiers | none beyond intentional author attribution |
| private/internal metadata | one ephemeral Work scratch path in a preserved dependency error; low consequence |

