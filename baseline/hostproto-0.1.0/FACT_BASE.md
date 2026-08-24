# Fact base

This file prevents later planning sessions from reviving claims that were already stale when the project was framed. It records sources, not implementation guarantees.

## Confirmed as of 2026-08-22

### Servo embedding

- The Servo Book describes Servo's consumable WebView work as ongoing and recommends `servoshell` for trying Servo. For embedding, it points readers to `tauri-runtime-verso` and [`servo-gtk`](https://book.servo.org/).
- [`servo-gtk`](https://github.com/nacho/servo-gtk) is a GTK4 library embedding Servo with OpenGL-accelerated rendering and asynchronous event handling.
- Its author describes it as a research project built to assess whether Servo was ready to replace WebKitGTK in an Amazon product, and explicitly says Servo was not yet production-ready for that need. It was nevertheless possible to get embedded rendering working in a few days. [Author's project note](https://blogs.gnome.org/nacho/2025/10/01/servo-gtk/)
- Servo's public embedding API has been moving toward `WebView`, delegate-based callbacks, and simplified rendering contexts. The exact API and revision must be pinned per evidence run. [Servo embedding update](https://servo.org/blog/2025/03/10/this-month-in-servo/)

**Implication:** `servo-gtk` removes substantial rendering and GTK integration work. It does not prove that its host semantics match WebKitGTK or remain stable across Servo revisions. That unproven semantic boundary is the project.

### Verso

- [`versotile-org/verso`](https://github.com/versotile-org/verso) was archived on 2025-10-08. Its maintainers state that limited manpower and funding could not keep the browser aligned with significant Servo revisions.

**Implication:** adapter maintenance and upstream API churn are primary risks. This project releases version-pinned observations and minimal upstream reproductions; it does not promise a perpetually current browser fork.

### WebKitGTK and WebExtensions

- WebKitGTK 2.52 introduced an initial public API for WebExtensions. [WebKitGTK 2.52 highlights](https://webkitgtk.org/2026/03/18/webkitgtk-2.52-highlights.html)
- The 2.52 `WebExtension` class reads and exposes manifest metadata, resources, icons, localization, requested permissions, match patterns, and capability flags. It is scaffolding for an embedder-facing runtime, not evidence that WebKitGTK already executes an arbitrary Manifest V3 extension. [WebExtension class reference](https://webkitgtk.org/reference/webkitgtk/2.52.0/class.WebExtension.html)
- uBlock Origin Lite already ships for Safari from the same project, so “uBOL on WebKit” is no longer a novel claim by itself. [uBOL supported platforms](https://github.com/uBlockOrigin/uBOL-home)
- A common WebExtensions specification is being developed, but the 2026 document is a Community Group report rather than a completed W3C Recommendation. [WebExtensions draft](https://w3c.github.io/webextensions/specification/)

**Implication:** an extension runtime is a separate, open research and implementation problem. It is permanently outside hostproto. Any future extension-portability project gets its own denominator, threat model, and repository.

### WebKitGTK bridge

- WebKitGTK exposes script-message handlers through `WebKitUserContentManager`, including message delivery from JavaScript to the host. [API reference](https://webkitgtk.org/reference/webkit2gtk/stable/method.UserContentManager.register_script_message_handler.html)

**Implication:** WebKitGTK has a plausible native transport beneath the engine-neutral `window.hostproto` facade. The Servo transport remains an implementation question and must not be assumed into existence.

## Facts that must be re-established at implementation time

- Installed Arch package versions and feature flags.
- Current `webkit6-rs`, GTK, Servo, and `servo-gtk` revisions.
- Whether `servo-gtk` exposes or can support a safe host-to-JavaScript and JavaScript-to-host bridge without a private engine fork.
- Which lifecycle and navigation callbacks each pinned backend actually exposes.
- Whether both chrome and content views can be composed in the same GTK4 window under the selected revisions.
- Build reproducibility and runtime behavior under Wayland and the user's current graphics stack.

No package statement substitutes for these checks.
