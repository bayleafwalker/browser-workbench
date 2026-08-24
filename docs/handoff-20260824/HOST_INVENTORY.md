# Host inventory — workstation, 2026-08-24

Recorded per `NEXT_RUN_PROMPT.md` required action 5, before any native work.

| Item | Value | Slice-1 readiness |
| --- | --- | --- |
| OS | Arch Linux, kernel 7.1.9-arch1-2, x86_64 | ready |
| Rust / Cargo | rustc 1.97.1, cargo 1.97.1 | ready |
| Python | 3.14.7 | ready |
| GTK4 | 4.22.4 (pkg-config) | ready |
| WebKitGTK 6.0 | **absent** — neither `webkitgtk-6.0` nor `webkit2gtk-6.0` in the pkg-config path | **blocking** |
| Display | Wayland (`wayland-1`), X11 `:1`, `xvfb-run` present at /usr/bin/xvfb-run | ready |
| Node | v24.15.0, npx 12.0.2 | ready |
| Playwright | **absent** — no `playwright` Python module, package not installed | blocked (oracle lane, non-gating for slice 1) |

## Consequence

The gating WebKitGTK lane cannot compile or run here until the WebKitGTK 6.0
development package is installed. That is the single blocking prerequisite for
slice 1; everything else on the native path is satisfied.

Playwright absence blocks only the external oracle lane, which follows slice 1.

## Source/mock gate on this host

`python3 scripts/verify_package.py` — passed, 283 verified files.

`PYTHONPATH=src python3 scripts/release_gate.py` — passed, run in a disposable
copy so regenerated evidence did not touch the integrity-checked import:

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

No native runtime, GTK window, adapter transport, or scenario execution was
verified on this host.
