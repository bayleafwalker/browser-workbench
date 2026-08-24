# Host protocol v0

## Status

This document defines protocol version `0.1`. It is frozen for mock-adapter implementation once Wave 0 gates pass. Pre-1.0 versions may change incompatibly, but every evidence bundle pins the exact version used.

## JavaScript surface

The adapter injects one facade into the reference chrome:

```ts
interface HostprotoFacade {
  connect(hello: Hello): Promise<Welcome>;
  request<T = unknown>(method: string, params?: object, options?: RequestOptions): Promise<T>;
  cancel(requestId: string, reason?: string): void;
  subscribe(handler: (event: HostEvent) => void): () => void;
}

declare global {
  interface Window {
    hostproto: HostprotoFacade;
  }
}
```

The facade is a logical contract. WebKit script-message handlers, Servo delegates, loopback transports, or other native mechanisms are not visible to chrome code. A transport that cannot preserve the contract produces a finding; it does not justify an engine-specific facade.

## Envelope model

The native boundary carries UTF-8 JSON objects validated by `schemas/protocol-envelope.schema.json`.

Kinds:

- `hello`: chrome proposes protocol versions and required capabilities.
- `welcome`: host selects a version, assigns a bridge session, and declares capabilities.
- `request`: either side invokes a method with a correlation identifier.
- `response`: exactly one terminal success or error for a request.
- `event`: ordered host observation that does not require a direct response.
- `cancel`: best-effort request cancellation.

All post-handshake envelopes contain `protocol_version`. Envelope identifiers are opaque strings; consumers must not infer ordering from them.

## Handshake

Chrome sends:

```json
{
  "kind": "hello",
  "supported_versions": ["0.1"],
  "required_capabilities": ["host.handshake", "session.snapshot"]
}
```

Host replies:

```json
{
  "kind": "welcome",
  "protocol_version": "0.1",
  "session_id": "opaque-session-id",
  "capabilities": {
    "host.handshake": {
      "status": "supported",
      "semantics": "exact",
      "source": "host",
      "notes": []
    }
  }
}
```

If no version overlaps, the bridge returns `protocol_version_mismatch` and refuses operational messages. A missing required capability returns `required_capability_missing`.

## Methods

### `session.get_state`

Parameters: none.

Returns the authoritative canonical snapshot:

```json
{
  "session_id": "...",
  "protocol_version": "0.1",
  "view_order": ["view-1"],
  "active_view_id": "view-1",
  "views": {
    "view-1": {
      "lifecycle": "open",
      "visible_url": "http://127.0.0.1:8000/title-a",
      "committed_url": "http://127.0.0.1:8000/title-a",
      "title": "Title A",
      "load_state": "idle",
      "can_go_back": false,
      "can_go_forward": false,
      "last_navigation_outcome": "success"
    }
  }
}
```

### `view.create`

Parameters:

- `initial_url`: absolute HTTP(S) URL or `null`.
- `activate`: boolean, default `true`.
- `cause`: `user`, `content_request`, or `test`.

Returns `{ "view_id": string }` after host identity allocation and backend-view creation are both successful. Failure must not leave an open canonical view.

### `view.activate`

Parameters: `{ "view_id": string }`.

Returns `{ "active_view_id": string }` after canonical state changes.

### `view.close`

Parameters: `{ "view_id": string }`.

Returns `{ "view_id": string, "closed": true }`. Calling close again returns `view_not_open`; idempotent-looking success would hide a lifecycle error.

### `navigation.navigate`

Parameters: `{ "view_id": string, "url": string }`.

Only absolute `http` and `https` URLs are valid in v0. Returns `{ "navigation_id": string }` when the backend accepts the request, not when loading succeeds.

### `navigation.reload`

Parameters: `{ "view_id": string }`.

Returns `{ "navigation_id": string }` when accepted.

### `navigation.stop`

Parameters: `{ "view_id": string, "navigation_id": string | null }`.

Returns `{ "accepted": boolean }`. `accepted: true` means a cancellation request reached the backend; the terminal navigation event remains the outcome oracle.

### `navigation.back` and `navigation.forward`

Parameters: `{ "view_id": string }`.

Returns `{ "navigation_id": string }` when accepted. If history traversal is unavailable, the host returns `capability_unsupported` before invoking the adapter.

### `view.resolve_open_request`

Parameters:

- `decision_id`: opaque identifier from `view.open_requested`.
- `decision`: `allow` or `deny`.
- `activate`: boolean used only for `allow`.

Returns either `{ "decision": "deny" }` or `{ "decision": "allow", "view_id": string }`.

Late, unknown, or duplicate decisions return `decision_expired` or `decision_already_resolved`.

## Events

Every event includes monotonically increasing host-assigned `seq`, an event `name`, a `payload`, and optional `cause_id` linking it to a request or prior event.

### Session and backend

- `session.ready`: handshake completed.
- `backend.degraded`: a declared capability became unreliable; affected scenarios become invalid.

### View lifecycle

- `view.created`: `{ view_id, cause }`.
- `view.activation_changed`: `{ previous_view_id, active_view_id }`.
- `view.closing`: `{ view_id }`.
- `view.closed`: `{ view_id }`.
- `view.terminated`: `{ view_id, reason, recoverable }`.
- `view.state_changed`: `{ view_id, changed, state }`, where `changed` lists canonical fields.

### Navigation

- `navigation.started`: `{ view_id, navigation_id, requested_url, kind }`.
- `navigation.committed`: `{ view_id, navigation_id, committed_url }` when the backend exposes a defensible commit boundary.
- `navigation.finished`: `{ view_id, navigation_id, final_url }`.
- `navigation.failed`: `{ view_id, navigation_id, stage, error_class, backend_detail_ref }`.
- `navigation.stopped`: `{ view_id, navigation_id, backend_detail_ref }` when an accepted host stop can be causally attributed to the terminal backend observation. If that attribution cannot be defended, the capability is partial or the run opens a finding; an unrelated failure must not be relabeled as a stop.

If a backend cannot expose a commit boundary, it omits `navigation.committed`; v0 scenarios do not require this event. The final canonical committed URL must still be defensible and its derivation documented by the adapter.

### Host decision

- `view.open_requested`: `{ decision_id, source_view_id, requested_url, disposition, deadline_ms, default_decision }`.
- `view.open_request_expired`: `{ decision_id, applied_default }`.

## Error codes

| Code | Meaning |
| --- | --- |
| `protocol_version_mismatch` | No mutually supported protocol version. |
| `required_capability_missing` | Handshake cannot satisfy chrome requirements. |
| `invalid_envelope` | Envelope fails schema or handshake-state validation. |
| `invalid_params` | Method parameters are malformed or outside v0 constraints. |
| `unknown_method` | Method is not defined by the selected protocol version. |
| `capability_unsupported` | Method is known but unavailable in this run. |
| `view_not_found` | Host has no record of the view identifier. |
| `view_not_open` | View exists but cannot accept operational commands. |
| `navigation_not_active` | Referenced navigation is not cancellable. |
| `decision_expired` | Decision deadline has passed or default was applied. |
| `decision_already_resolved` | A terminal decision already exists. |
| `request_cancelled` | Request terminated due to accepted cancellation. |
| `deadline_exceeded` | Request did not reach a terminal response by its deadline. |
| `backend_rejected` | Backend synchronously rejected an otherwise valid operation. |
| `backend_failed` | Backend operation failed without a more precise normalized class. |
| `internal_error` | Host invariant failed; run requires investigation. |

Errors may include a human-readable `message`, structured `data`, and `backend_detail_ref` pointing into the raw trace. Raw backend messages do not become stable protocol text.

## Versioning

- `0.1` identifies the complete semantic contract, not merely the JSON envelope.
- Adding optional fields or events may increment the minor version if older consumers can ignore them safely.
- Changing lifecycle, ordering, terminality, or error meaning requires an incompatible version.
- Capability identifiers are versioned through the enclosing protocol; they do not develop independent folklore.
- Evidence from different protocol versions may be compared only after an explicit semantic migration or at the raw-trace layer.
