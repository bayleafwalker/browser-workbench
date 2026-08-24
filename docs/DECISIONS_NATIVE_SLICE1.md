# Decision records — native slice 1

## ADR-S1-01: one ordered channel, shared ordinal

**Context.** The host must know whether an engine event happened before or
after the reply to a request. Two independent sequences (one for events, one
for replies) cannot answer that without a clock both sides trust.

**Decision.** Events and replies share a single `ordinal` counter on one
stdout stream. The host verifies contiguity on every frame.

**Consequence.** Interleaving is total and checkable. A dropped or reordered
frame is detected immediately instead of producing evidence that looks
complete. The cost is that the adapter must serialize all output through one
writer, which it does on the GTK main thread.

**Alternative rejected.** A second channel or a socket. Both reintroduce the
ordering question and give the adapter a listening surface it must not have.

## ADR-S1-02: waiting is host-side

**Context.** `page.await` could be implemented in the adapter, where the
engine's own callbacks are closest.

**Decision.** The host waits, by consuming the ordered event stream.

**Consequence.** Every event a wait decision rests on is, by construction, in
the evidence. The capability matrix already declared `page.await` with
`provider: host`, and this keeps that declaration true. An adapter-side wait
would let a condition be satisfied by an event the trace never recorded.

## ADR-S1-03: the ServoGTK lane is its own workspace

**Context.** The pinned ServoGTK revision depends on a Servo revision that
requires `serde ^1.0.228`. The workspace pins `serde =1.0.219`. Cargo resolves
a workspace as a unit, so this made the **gating** WebKitGTK lane unbuildable —
`cargo build -p browser-workbench-webkitgtk-worker` failed on a dependency of a
package it does not use.

**Decision.** `native/servo-gtk-worker` is excluded from the root workspace and
carries its own. `scripts/native_gate.py` reaches it by `--manifest-path`.

**Consequence.** An experimental, explicitly non-gating research lane can no
longer block the primary lane through shared dependency resolution. The two
lanes may now resolve different versions of shared crates, which is correct:
they are separately pinned experiments, not one program.

**Alternative rejected.** Relaxing the `serde` pin to satisfy Servo. That
inverts the declared priority — it would let a non-gating lane dictate the
gating lane's dependency graph.

## ADR-S1-04: gtk4 `v4_10` feature enabled

**Context.** `webkit6 0.6.1` names `gtk::Accessible` unconditionally.
`gtk4 0.11.4` gates that type behind its `v4_10` feature. The checkpoint
enabled neither, so the pinned pair could not compile together.

**Decision.** Enable `features = ["v4_10"]` on the pinned `gtk4` dependency.

**Consequence.** The pinned crate versions are unchanged; only the feature the
pinned WebKitGTK binding already requires is turned on. `v4_10` rather than a
higher level keeps the build usable on GTK older than this host's 4.22.

**Note.** This and ADR-S1-03 are both defects that a source-audit gate cannot
see. They are the first concrete evidence for the handoff's central claim: a
compile-only gate is not sufficient, and "source-verified" is a genuinely
weaker statement than it sounds.

## ADR-S2-01: console capture is injected, and says so

**Context.** WebKitGTK 6 exposes no console signal. Console messages can only
be captured by injecting a script that wraps `console.*` and posts through a
user content handler.

**Decision.** Inject the bridge, and normalize its messages with
`source: injected` rather than `engine`.

**Consequence.** The capability matrix already declared this lane
`provider: injected, semantics: normalized`, and the evidence now matches that
declaration event by event. A page can observe, wrap, or defeat this bridge —
which is exactly why it must never be reported as engine truth.

## ADR-S2-02: the declared viewport is a size request, not a window hint

**Context.** The first observation run produced a 640x480 snapshot from a run
spec declaring a 1024x768 viewport. Headless there is no window manager, so
`default_width`/`default_height` — which are hints to a WM — were ignored and
the engine laid out at GTK's fallback size.

**Decision.** Express the declared viewport as the content view's own size
request, and record a `viewport-width-divergence` deviation whenever an
observed snapshot is narrower than declared.

**Consequence.** Snapshots now match the declared viewport, and if they ever
stop matching the evidence says so instead of quietly disagreeing with the run
spec. A full-document snapshot may still be taller than the viewport; that is
legitimate and is not flagged.
