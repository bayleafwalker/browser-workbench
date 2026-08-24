# Workbench protocol v1

## Contract

The protocol models a browser session as an append-only stream of typed
observations, actions, effects, receipts, checkpoints, and exports. The current
page object is only a projection of that stream.

All requests use:

```json
{
  "protocol": "browser-workbench/v1",
  "request_id": "opaque-client-id",
  "method": "page.observe",
  "params": {}
}
```

Every accepted request terminates exactly once. The terminal envelope is either
`ok` with `result`, or `error` with a stable `code`, bounded `message`, and
optional evidence references. A deadline does not prove an escaped native
effect did not occur.

## Identity and causality

- `run_id` identifies one immutable runner execution.
- `session_id` identifies one live browser session.
- `page_id` is stable for the life of one page object.
- `generation` increments whenever a page commits a new document or is restored
  from a checkpoint.
- `event_id` and `event_seq` address an append-only observation.
- `action_id` identifies the requested intent.
- `receipt_id` identifies the terminal action receipt.
- `artifact_ref` is content-addressed and never implies authority to retrieve
  data outside the evidence bundle.
- `lease_id` and `lease_epoch` fence the single writer.

Identifiers are opaque. Only `event_seq` has ordering semantics.

## `session.create`

Creates an isolated session and acquires its single-writer lease.

Parameters:

```json
{
  "profile": {"mode": "ephemeral", "name": "default"},
  "viewport": {"width": 1280, "height": 800, "scale": 1.0},
  "resume_checkpoint": null,
  "client": {"kind": "agent", "id": "client-a"}
}
```

Returns session/page identity, lease, backend identity, and the runtime-verified
capability report. Resuming a checkpoint increments the lease epoch and page
generation. Persistent profiles are explicit and never the default.

## `page.navigate`

Parameters: `{ "page_id": string, "url": string, "wait": "none" | "commit" }`.

Returns acceptance and `navigation_id`; success is established by later events
or `page.await`, not by the acceptance response.

## `page.observe`

Parameters:

```json
{
  "page_id": "page-1",
  "projection": ["state", "targets", "console", "network"],
  "since_event": 0,
  "max_bytes": 32768
}
```

Allowed projections are `state`, `targets`, `dom`, `accessibility`, `console`,
`network`, `dialogs`, `permissions`, `downloads`, `raw-events`, and
`screenshot`. Unsupported projections fail explicitly.

The result always reports:

- the applied byte budget;
- returned and omitted counts;
- whether it is lossy;
- the next event cursor;
- raw artifact references for omitted or binary material; and
- target generation.

Truncation occurs after redaction and structural framing. The caller can fetch a
later slice from evidence without rerunning navigation or action effects.

## `page.act`

Parameters:

```json
{
  "page_id": "page-1",
  "intent": {"kind": "click", "value": null},
  "target": {"target_id": "target-submit", "generation": 3},
  "preconditions": {
    "url": "http://127.0.0.1/form",
    "title": "Form",
    "generation": 3
  }
}
```

Supported intent families are capability-negotiated: pointer, keyboard,
selection, scroll, JavaScript, dialog decision, permission decision, upload,
download decision, and navigation stop.

The receipt distinguishes `attempted`, `accepted`, `executed`, and `verified`.
It carries causal event IDs, observed effects, before/after state digests, and
the provider class used. A stale target or failed precondition is rejected
before backend invocation.

## `page.await`

Parameters:

```json
{
  "page_id": "page-1",
  "conditions": [
    {"kind": "load_state", "equals": "idle"},
    {"kind": "url", "equals": "http://127.0.0.1/done"}
  ],
  "deadline_ms": 5000
}
```

Waits are event-driven. Polling or sleeps are adapter implementation details
that must be declared as partial semantics. A deadline result includes the last
observed event cursor and unsatisfied conditions.

## `session.checkpoint`

Captures canonical session/page state, evidence cursor, profile policy, and a
content digest. With `release_lease: true`, the checkpoint is a handover object:
the old writer becomes read-only and a successor may resume with a higher lease
epoch. It is not an approval token.

## `session.export`

Creates a bounded export from already captured evidence. Parameters select
projections, event range, redaction profile, and byte budget. Export never
reruns a browser operation. Exact local raw evidence and model-facing redacted
projections are different surfaces with different artifact identities.

## `run.compare`

Parameters:

```json
{
  "baseline": {"manifest": "sha256:..."},
  "candidate": {"manifest": "sha256:..."},
  "tolerances": {
    "ignore_fields": ["diagnostics.wall_time"],
    "event_order": "partial",
    "allow_capability_differences": true
  }
}
```

Comparison is read-only. Inputs are verified before and after execution and the
gate fails if either tree changes. Reports compare capabilities, invariants,
causal relations, terminal states, artifacts, and declared suppressions—not raw
callback cosmetics.

## Errors

Stable codes include `invalid_request`, `protocol_mismatch`,
`capability_unsupported`, `capability_blocked`, `lease_conflict`,
`lease_fenced`, `page_not_found`, `stale_target`, `precondition_failed`,
`deadline_exceeded`, `backend_rejected`, `backend_failed`,
`evidence_incomplete`, `integrity_mismatch`, `candidate_mutated`, and
`internal_invariant`.

No error authorizes an automatic retry. A planner may issue a new run spec with
a new request identity after reviewing the receipt.
