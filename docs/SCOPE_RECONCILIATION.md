# Scope reconciliation

This checkpoint layers Waves 2–3 on top of the unchanged hostproto 0.1.0 artifact.

| Surface | Preserved baseline | Added in 0.2.0 |
|---|---|---|
| denominator | frozen 16 hostproto scenarios | separate frozen 12-scenario workbench corpus, three repetitions |
| contract | host envelopes, state, temporal semantics | typed observation/action operations and runner contract |
| implementation | none by design | Python host/mock runner, authenticated loopback bridge, GTK chrome, native source boundaries |
| engines | adapter notes | WebKitGTK primary source lane, ServoGTK experimental lane |
| oracle | recommendation | pinned Playwright/WebKit executor source |
| evidence | schemas and examples | raw/normalized traces, receipts, manifests, comparisons, redacted exports |
| release truth | spec-only | source + deterministic mock verified; native/oracle probes separately reported |

No file under `baseline/hostproto-0.1.0` is rewritten. The 12-scenario corpus is not substituted for the original 16 scenarios; the two denominators test different layers.

## Delivered Wave 2 boundary

- GTK4 shell source for navigation, tabs, adapter status, takeover, and evidence access.
- authenticated loopback-only bridge with a one-megabyte request limit.
- WebKitGTK worker source for navigation lifecycle/failure, resources, dialogs, permissions, file chooser, process termination, title, popup policy, JavaScript, snapshot, reload, and stop.
- deterministic mock implementations of bounded observations, generated targets, causal receipts, event-driven waits, single-writer leases, checkpoint/handover, redacted export, console/network evidence, uploads/downloads, and crash recovery.

## Delivered Wave 3 boundary

- explicit backend variants and capability/provider/semantics declarations.
- immutable-input differential comparison with declared partial-order normalization.
- pinned Playwright oracle source and independent evidence path.
- bounded ServoGTK source lane with unsupported public-surface gaps made explicit.
- source/mock release gate plus target-host native gates.

WPE remains out of scope. Native runtime and three-repetition engine claims require a suitable GTK/WebKitGTK/Servo/Playwright host and are not inferred from source inspection.
