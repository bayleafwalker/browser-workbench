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

## ADR-S3-01: the corpus is frozen; the bindings are not

**Context.** The twelve scenarios and their assertion texts are the frozen
denominator. The drivers that reached them were written against `MockBackend`
and encoded mock-only facts: a virtual clock reading of exactly 10ms, pseudo
JavaScript like `set-title:Declared`, and `request_id` correlation that a real
engine does not use.

**Decision.** Split the corpus into frozen drivers and a `Profile` of
backend-specific bindings. Every place a backend legitimately reaches a frozen
assertion by other means is declared in `assertion_semantics`, which travels
in the corpus summary.

**Consequence.** One set of scenarios runs on both backends, and a native
corpus result can never be silently read as the mock denominator: the summary
states, per assertion, where the two differ. The mock denominator is unchanged
and still produces semantic digest
`a8d0c478fcdca32bc9167425744d3a9c54969c7d9e497fc6a48f388399b8a74f`.

**Alternative rejected.** Rewriting the assertions to suit the engine. That
edits the denominator to fit the result, which is the one thing a denominator
exists to prevent.

## ADR-S3-02: the host marks its own navigation request

**Context.** `page.await` on `load_state == idle` returned immediately, because
the page *was* idle: the engine had not yet started the navigation the host had
just requested. Four scenarios silently ran against `about:blank` while
believing they were on the fixture.

**Decision.** `page.navigate` sets `load_state` to `loading` when it issues the
request, and only the engine's own events move it back to idle.

**Consequence.** A wait for an idle page now means "the navigation I asked for
has finished" instead of "nothing has started yet". The host projects its own
request, which it knows about; it still never projects an engine outcome.

## ADR-S3-03: an idle load state is not a quiet engine

**Context.** WebKitGTK delivers `title-changed` *after* `load-changed:finished`.
Code that settled on the load state alone left that event to land during the
next operation and mutate state the caller believed was stable — which showed
up as a screenshot appearing to change page state.

**Decision.** Add `quiesce()`: consume events until the engine goes quiet, and
use it after settling a navigation. Actions likewise drain their immediate
effects before the receipt is sealed.

**Consequence.** A receipt reports the effects the action actually had — a
click that navigates names its navigation events — instead of reporting none
because the engine had not spoken yet. This observes; it never re-issues an
action, so it is not a retry.

## ADR-S3-04: permission prompts need an API that a page load can reach

**Context.** The prompts fixture used `Notification.requestPermission()`, which
requires transient user activation. A page load has none, so it resolved denied
without ever asking the browser, and no permission request reached the host.
It worked under `evaluate_javascript` only because API-evaluated script carries
a user gesture.

**Decision.** The fixture requests geolocation, which needs no activation, and
raises it in a task strictly before the one that calls `alert()`.

**Consequence.** Both browser-owned requests reach the host on every run.
`alert()` blocks the web process until the host decides, so anything requested
in the same task would never be flushed to the browser process.
