# Adapter notes

## Boundary

Adapters are replaceable implementation modules. They own native handles and translate operations; they do not own the protocol, scenario oracles, canonical state, or release claims.

A likely internal Rust surface is deliberately small:

```rust
trait EngineAdapter {
    fn describe_capabilities(&self) -> CapabilityMap;
    fn create_view(&mut self, spec: CreateView) -> AdapterResult<NativeView>;
    fn destroy_view(&mut self, view: NativeViewRef) -> AdapterResult<()>;
    fn set_active(&mut self, view: Option<NativeViewRef>) -> AdapterResult<()>;
    fn navigate(&mut self, view: NativeViewRef, op: NavigationOp) -> AdapterResult<()>;
    fn resolve_open_request(&mut self, decision: OpenDecision) -> AdapterResult<()>;
    fn snapshot_native_state(&self) -> AdapterSnapshot;
    fn poll_raw_observations(&mut self) -> Vec<RawObservation>;
}
```

This sketch is not normative. Split or reshape it when Rust ownership and GTK thread rules demand it. Do not export its types to chrome code or treat method count as architectural progress.

## Common adapter obligations

- Capture raw observations before mapping or dropping them.
- Maintain explicit native-handle to host-identifier correlation.
- Never reuse a native view handle after host lifecycle termination.
- Queue callbacks across the host boundary to prevent re-entrancy.
- Declare backend thread-affinity and shutdown ordering.
- Surface ambiguity rather than selecting a convenient navigation or view.
- Support deterministic test hooks only behind a non-release harness feature.
- Keep engine-specific transport beneath the identical `window.hostproto` facade.

## Mock adapter

The mock adapter is implemented first. It must support:

- Deterministic successful lifecycle and navigation.
- Configurable asynchronous delay without wall-clock sleeps in tests.
- Navigation failure and stop outcomes.
- Duplicate and late raw callbacks.
- Unexpected view termination.
- New-view request allow, deny, duplicate, late, and expiry paths.
- Snapshot/reconnect.

Its purpose is to validate the contract and harness. It must not mimic WebKit or Servo callback names; doing so would smuggle backend assumptions into the oracle.

## WebKitGTK adapter

### Plausible primitives to verify

- GTK4 `WebKitWebView` creation and composition through the `webkit6` bindings.
- `WebKitUserContentManager` script-message handling beneath the chrome facade.
- Load lifecycle signals and property notifications for URL, title, and loading state.
- Back/forward availability through WebKit history APIs.
- Policy or create callbacks for requested new views.
- Web-process termination notification.

These are research leads, not accepted mappings. Each selected API must be pinned to the installed library and binding version and linked in the adapter mapping document.

### Setup inventory

Record before implementation:

```bash
pacman -Qi gtk4 webkitgtk-6.0
pkg-config --modversion gtk4 webkitgtk-6.0
rustc --version --verbose
cargo --version --verbose
```

If a package or `pkg-config` name differs, record the actual resolved name. Do not modify the system package set merely to make this document look prescient.

### Main semantic questions

- Which load callbacks define a defensible start, commit, finish, stop, and fail sequence?
- What visible URL should chrome show during provisional navigation?
- Can stop be distinguished from failure in all relevant stages?
- Does a requested new view require a synchronous native decision?
- Which callbacks arrive after a view is destroyed or a process terminates?
- Can the chrome bridge reconnect without reloading content views?

## servo-gtk adapter

### Baseline

Use a pinned `servo-gtk` revision and its resolved Servo lockfile. Treat the library as research-grade and changing. A successful example browser proves embedded rendering, not the hostproto semantics.

### First evidence questions

1. Can a GTK4 Servo view be created, resized, focused, and destroyed repeatedly in one process?
2. Can the same window compose a Servo chrome view and Servo content view?
3. Is there a bidirectional host/JavaScript bridge sufficient for `window.hostproto` without a private Servo fork?
4. Which delegate callbacks expose URL, title, navigation lifecycle, new-view requests, and termination?
5. Which operations must run on the GTK thread, Servo event loop, or rendering thread?
6. Can raw callbacks be retained before higher-level `servo-gtk` logic discards them?

If question 3 fails, stop the Servo wave and ship the result. A temporary engine-specific chrome branch would falsify the demonstration rather efficiently.

### Patch policy

- Small adapter-local changes are normal.
- A minimal generally useful `servo-gtk` or Servo patch may be prepared as a separate upstream candidate.
- A long-lived private fork is a stop condition.
- Evidence using any patch records its commit, diff hash, and upstream status.

## Transport options

Preferred order:

1. Native script-message/delegate transport.
2. Adapter-injected facade over a local in-process or loopback transport, if origins, authentication, lifecycle, and ordering can be specified identically.
3. No transport: declare the bridge capability unsupported and ship the finding.

Do not use page titles, custom navigation URLs, clipboard state, console scraping, or JavaScript dialogs as a covert RPC channel. The project is allowed to discover that an interface is missing.

## Rollback boundary

Every adapter wave begins from the last released contract tag. Backend experiments occur on isolated branches or worktrees. If an approach requires changing the denominator, revert the experiment and open a proposed contract revision; do not silently mutate the scenario until the engine passes.
