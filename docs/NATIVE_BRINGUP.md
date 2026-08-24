# Native and oracle bring-up

The current package is source/mock verified. Run the following only on a disposable target host whose package installation and display access are under your control.

## WebKitGTK primary lane

Prerequisites are Rust 1.85+, GTK4 development headers, WebKitGTK 6.0 development headers, `pkg-config`, and a Wayland/X11 display (or Xvfb for headless gates). Verify the probe before compilation:

```sh
python scripts/native_gate.py webkitgtk
xvfb-run -a python scripts/native_gate.py webkitgtk --execute --output evidence/native-webkitgtk.json
```

A passing compile is still not the three-repetition corpus. Connect the worker to the authenticated host bridge, run both `stable-ephemeral` and `stable-persistent` variants, retain raw and normalized evidence, and execute the 12 scenarios three times per variant before making an engine conformance claim.

## Playwright oracle

From `oracle/playwright`, install exactly the lock/pin declared in `package.json`, then install the matching WebKit binary. The oracle should run in an isolated context with retries disabled and its result compared through `browser-workbench compare`.

```sh
npm install --package-lock-only --ignore-scripts
npm ci
npx playwright install --with-deps webkit
python ../../scripts/native_gate.py playwright --execute
```

## ServoGTK experimental lane

Check out `native/UPSTREAM_PINS.json`’s exact ServoGTK revision and export `SERVO_GTK_SOURCE` to that checkout before probing. The source lane must remain non-gating until its public surface supports the required lifecycle and observation contract.

```sh
SERVO_GTK_SOURCE=/path/to/pinned/servo-gtk python scripts/native_gate.py servo-gtk
```

Unsupported ServoGTK capabilities are expected outcomes. Do not patch around them with success-shaped host events.
