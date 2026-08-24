# Native adapter contract v1

The host runner and a native adapter process communicate over one ordered,
bidirectional, line-delimited JSON channel. This document is the contract; the
WebKitGTK worker is its first implementation.

The adapter is a subordinate process, not a peer service. It binds no socket,
accepts no external connection, and holds no authority over the run. The host
owns session identity, evidence, causality, and every decision.

## Channel

| Direction | Stream | Framing |
| --- | --- | --- |
| host to adapter | adapter `stdin` | one UTF-8 JSON object per line |
| adapter to host | adapter `stdout` | one UTF-8 JSON object per line |
| adapter diagnostics | adapter `stderr` | free text, captured as raw evidence |

No frame may contain a literal newline. `stdout` carries protocol frames only;
anything a library prints to `stdout` corrupts the channel, so the adapter
redirects library chatter to `stderr`.

## Request frames

```json
{"v": 1, "seq": 1, "op": "session.open", "params": {}}
```

- `seq` starts at 1 and increases by exactly 1 per request.
- The host has at most one request in flight. There is no pipelining.
- An unknown `op` is an error reply, never a silent success.

## Response frames

Every adapter line carries `ordinal`, a single counter shared by all frame
kinds, starting at 1 and increasing by exactly 1.

```json
{"v": 1, "ordinal": 1, "type": "ready",  "identity": {}}
{"v": 1, "ordinal": 2, "type": "event",  "kind": "load-changed", "monotonic_ms": 12, "payload": {}}
{"v": 1, "ordinal": 3, "type": "reply",  "seq": 1, "ok": true, "result": {}}
```

- `ready` appears exactly once, as `ordinal` 1, before any other frame. It
  carries the engine, GTK, and adapter build identity the host records.
- `event` frames are raw engine callbacks. The adapter reports what a callback
  gave it and nothing else: it never synthesizes an event, never coalesces two
  callbacks into one, and never normalizes. Normalization is host-side.
- `reply` frames terminate exactly one request. Exactly one reply per `seq`,
  in request order.

Because events and replies share one `ordinal` sequence, the host can place
every engine observation before or after each reply without guessing. A gap in
`ordinal` is an integrity failure and terminates the run; it is never patched
over by requesting the missing range.

## Errors

```json
{"v": 1, "ordinal": 7, "type": "reply", "seq": 3, "ok": false,
 "error": {"code": "backend_rejected", "message": "bounded", "details": {}}}
```

Adapter error codes are drawn from the protocol's stable set. The adapter
never retries an effect and never converts a failure into a partial success.
An operation the pinned engine surface cannot express returns
`capability_unsupported` rather than an approximation.

## Lifecycle

1. Host spawns the adapter with a controlled environment and no inherited
   `stdout`.
2. Adapter initializes GTK, emits `ready`, and enters its main loop.
3. Host sends `handshake` and verifies the declared protocol version and
   engine identity against the pins.
4. Host issues declared operations, one at a time.
5. Host sends `shutdown`. The adapter replies, closes its windows, and exits 0.
6. If the adapter does not exit within the declared grace period the host
   terminates it and records a deviation. A killed adapter never upgrades to a
   clean teardown in the result.

An adapter that exits unexpectedly ends the run. Captured evidence is flushed
and marked incomplete. The host does not infer that an in-flight action had no
effect, because a crash after a native effect looks identical to a crash
before it.

## Slice 1 operation surface

| `op` | Purpose |
| --- | --- |
| `handshake` | version and engine identity |
| `session.open` | create the GTK window and hosted content view |
| `page.navigate` | begin a navigation; acceptance only |
| `page.observe` | read engine-owned page state |
| `shutdown` | orderly teardown |

`page.await` is deliberately absent. Waiting is a host concern evaluated over
the ordered event stream, which is why the capability matrix declares
`page.await` with `provider: host`. An adapter-side wait would hide the engine
events the evidence exists to record.

Operations outside this table are not yet implemented and return
`capability_unsupported`. That is the honest state of slice 1, and it is what
the capability report says.
