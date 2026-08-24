# Architecture

Browser Workbench is a Linux-first browser shell whose stable product boundary is the typed workbench protocol, not any one rendering engine. Humans, agents, and tools are clients of the same session model. A single-writer lease fences mutation while observation and redacted evidence remain shareable.

## Components

| Component | Responsibility | Trust boundary |
|---|---|---|
| GTK4 shell | tabs, location, status, manual takeover, evidence access | never fabricates engine state |
| loopback bridge | authenticated JSON dispatch on `127.0.0.1` | bearer required; bounded requests; no public bind |
| host runner | declared lifecycle, action execution, waits, gates, evidence | no planning, retries, or intent changes |
| WebKitGTK worker | primary engine hooks and engine-owned interactions | pinned WebKitGTK 6.0 API |
| ServoGTK worker | experimental navigation-only surface | non-gating; unsupported operations stay unsupported |
| Playwright oracle | independent comparison lane | oracle evidence is not native WebKitGTK evidence |
| differential runner | immutable input checks and semantic comparison | refuses mutated candidates |

The host owns canonical session/page state, target generations, causal event identity, lease epochs, checkpoints, redaction, and evidence manifests. Adapters own only what their public backend surfaces can actually observe or execute.

## State and authority

Each page has a stable `page_id` and monotonically increasing `generation`. Observation targets carry that generation. An action referencing an older target fails with `stale_target` before the backend is invoked. A checkpoint may release the writer lease; the successor receives a higher epoch, while the former writer is fenced. Handover never implies user approval.

## Event flow

Raw backend callbacks are captured first. Normalized events reference those raw identities, and action receipts reference normalized causal events. `page.await` consumes the event stream and a monotonic deadline; the runner does not use arbitrary sleeps. Bounded projections point to content-addressed raw artifacts whenever data is omitted.

## Deployment lanes

Two WebKitGTK variants are expected on target hosts: `stable-ephemeral` and `stable-persistent`. Playwright/WebKit runs as an external oracle. ServoGTK is admitted only after its prerequisite probe and only for capabilities marked supported or partial. WPE is intentionally deferred until the protocol, corpus, and native WebKitGTK evidence stabilize.
