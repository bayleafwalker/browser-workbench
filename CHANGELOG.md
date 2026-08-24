# Changelog

## 0.2.0 — source checkpoint

- preserved hostproto 0.1.0 and its frozen 16-scenario corpus;
- added the typed workbench protocol, runner contract, schemas, and 12-scenario × 3-repetition denominator;
- implemented deterministic observation/action, lease, receipt, wait, checkpoint, export, recovery, and comparison semantics;
- added an authenticated loopback bridge and reference browser chrome;
- added pinned GTK4/WebKitGTK, ServoGTK, and Playwright source boundaries;
- added source/mock, disclosure, native prerequisite, and CI gates;
- recorded native and oracle execution as blocked when target prerequisites are absent.

## Unreleased — native slice 1 (WebKitGTK vertical proof)

- added the native adapter contract v1: one ordered, bidirectional, line-delimited JSON channel on the adapter's stdin/stdout, with ordinal continuity and reply ordering enforced host-side;
- replaced the WebKitGTK source boundary with a working adapter process that runs a real GTK application hosting a real content view;
- added a host-side WebKitGTK backend that normalizes engine callbacks while retaining the raw ones, and an event-driven host wait;
- added a deterministic loopback fixture site and server whose bytes are hashed into the evidence;
- lifted the runner's non-mock hard block for WebKitGTK only, and only after capability probing and a real adapter connection both succeed;
- unimplemented operations and projections report `capability_unsupported`; no lane falls back to the mock;
- this is one session, not corpus conformance. Wave 2 remains open.

## Unreleased — native slice 2 (engine-truth observation and action)

- added deferred adapter replies for engine-asynchronous operations, keeping events in ordinal order while an operation is in flight;
- added `page.evaluate` and `page.snapshot` adapter operations;
- wired `page.act.javascript`, and the `dom`, `console`, `network`, and `screenshot` observation projections on the native lane;
- console capture is injected through a user content bridge and is labelled `injected`, never engine truth;
- the declared viewport is now the content view's size request, with a recorded deviation if an observed snapshot is narrower than declared;
- inline snapshot evidence is bounded; an oversized capture fails explicitly rather than being downscaled.

## Unreleased — native slice 3 (the full corpus on a real engine)

- split the corpus into frozen drivers and backend `Profile` bindings, so the same twelve scenarios run on the mock and on WebKitGTK;
- every place a backend reaches a frozen assertion by other means is declared in `assertion_semantics` and travels with the corpus summary;
- wired the remaining native operations: tabs, generation-scoped target enumeration, pointer and keyboard acts, stale-target rejection, script dialogs, permission requests, file chooser uploads, quarantined downloads, checkpoint and resume, and real web-process termination;
- browser-owned requests are held open by the adapter until the host decides, with refusing defaults and single-use decision tokens;
- downloads are confined to a host-declared quarantine directory;
- `page.navigate` marks its own request as loading, so a wait for an idle page can no longer be satisfied before the navigation starts;
- added `quiesce()`: an idle load state is not a quiet engine, and actions drain their immediate effects before the receipt is sealed;
- `scripts/native_corpus.py` and `workbench corpus --backend webkitgtk` execute the denominator natively; the release gate runs it and reports `native_corpus_claim`.

## Unreleased — native slice 4 (persistent profiles, both variants green)

- implemented persistent profiles as a host-located WebKitGTK `NetworkSession`; the engine's own `is_ephemeral()` is read back and a disagreement is `integrity_mismatch`;
- declaring a persistent profile under the ephemeral variant is rejected, so the variant always describes what actually ran;
- the corpus now runs on `stable-ephemeral` and `stable-persistent`, and the release gate and CI run both;
- `native_runtime_claim` is now derived from both variants passing the whole denominator, rather than being hardcoded false.
