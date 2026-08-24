# Capability model

## Purpose

Capability negotiation prevents the protocol from turning every difference into either a lie or a fatal incompatibility. It is not permission to advertise half-working behavior as support.

The host selects one protocol version during handshake and returns a capability map before accepting operational requests.

## Declaration shape

Each capability declaration contains:

| Field | Values | Meaning |
| --- | --- | --- |
| `status` | `supported`, `unsupported`, `experimental` | Whether the operation may be invoked in this run. |
| `semantics` | `exact`, `normalized`, `partial`, `none` | Relationship between backend behavior and hostproto semantics. |
| `source` | `engine`, `adapter`, `host` | Layer providing the behavior. |
| `notes` | string array | Bounded qualifications; not a substitute for `partial`. |

Rules:

- `unsupported` requires `semantics: none`.
- A capability required by the frozen corpus cannot be `partial` and still produce a scenario `pass` unless the scenario explicitly admits that partial profile.
- `normalized` means mechanical translation preserves the declared observable semantics while changing representation or incidental ordering.
- `partial` means at least one declared semantic is absent or observably different. A scenario using it must return `unsupported` or `fail`, not a generously interpreted `pass`.
- `experimental` describes stability, not correctness. Evidence may still show `exact` semantics for the pinned version.
- Adapter-provided behavior must be visible as `source: adapter`; the engine does not receive credit for work it did not do.

## Required v0 capabilities

| Identifier | Required semantics |
| --- | --- |
| `host.handshake` | Version selection and capability declaration before operational calls. |
| `session.snapshot` | Authoritative full state snapshot after handshake or reconnect. |
| `view.create` | Host-owned stable view identifier and exactly-once terminal response. |
| `view.activate` | Exactly one active open view or none. |
| `view.close` | Terminal lifecycle and rejection of later commands. |
| `view.observe` | Visible URL, title, loading state, and terminal navigation outcome. |
| `navigation.navigate` | Absolute HTTP(S) navigation request. |
| `navigation.reload` | New load attempt for the current committed page. |
| `navigation.stop` | Best-effort cancellation with an observable terminal outcome. |
| `view.open_request` | Engine-originated new-view request, decision token, deadline, and default. |
| `view.termination` | Unexpected view loss isolated from surviving canonical state. |

## Conditionally required capability

`navigation.history` may be declared `unsupported`. Scenario HP-S024 then produces `unsupported`, not project failure. If declared supported, the entire scenario oracle applies.

This is the only v0 conditional capability. Adding another requires a corpus revision.

## Explicitly absent from v0

The host must not advertise identifiers for downloads, permissions, dialogs, extension execution, persistent profiles, DRM, DevTools, printing, media capture, or multiple windows. Their absence is by design rather than a backend deficit.

## Capability changes during a run

Capabilities are immutable after `welcome` in v0. A backend degradation that invalidates a capability emits `backend.degraded` and makes the run invalid for affected scenarios. Dynamic renegotiation belongs to a later protocol version.

## Comparison rule

Cross-engine reports compare both declarations and observed behavior:

- Same declaration and same conformance result: aligned for the pinned versions.
- Same declaration and different result: finding required.
- Different declaration: capability divergence, not automatically a protocol failure.
- Supported declaration with missing behavior: adapter or engine defect until classified.
- Undeclared behavior observed raw: record it; do not surface it through the protocol without a versioned contract change.
