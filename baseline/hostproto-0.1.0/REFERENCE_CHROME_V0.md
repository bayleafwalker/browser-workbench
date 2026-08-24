# Reference chrome v0

## Role

The reference chrome is the denominator for protocol sufficiency. It is deliberately small enough to specify and serious enough to exercise more than a toy `load_url()` wrapper.

It is not a prototype of the eventual browser. There is no eventual browser in this project.

## Composition

One GTK4 top-level window contains:

1. A chrome web view rendering the reference UI.
2. A native content-view region managed by the selected adapter.

For an engine run, both chrome and content views use that run's selected backend. The content view is a sibling native surface, not a webview nested inside the chrome DOM.

The adapter injects the same `window.hostproto` facade into the chrome view. The facade implementation may use different native transports, but its JavaScript surface and protocol behavior must remain identical.

## Visible controls

- Tab strip with active-tab indication.
- New-tab and close-tab controls.
- Back, forward, reload, and stop controls.
- Address field with explicit navigation submission.
- Page title and load-state indication.
- A visible protocol/backend capability status area used by the conformance driver; it may name the selected backend using host-supplied metadata, but chrome code must not branch on that value.

No styling claim is part of conformance. The UI must remain legible and operable; visual fidelity between engines is recorded but not scored in v0.

## Canonical observable state

### Session

- `session_id`
- negotiated protocol version
- declared capabilities
- ordered open-view identifiers
- active view identifier or `null`

### View

- stable host-owned `view_id`
- lifecycle: `creating`, `open`, `closing`, `closed`, or `terminated`
- visible URL
- last committed URL, if known
- title
- load state: `idle` or `loading`
- `can_go_back`
- `can_go_forward`
- last terminal navigation outcome, if any

The canonical model intentionally excludes DOM state, cookies, storage, cache, engine history objects, security indicators, and persistent profiles.

## Required interaction surface

- Create, activate, and close views.
- Navigate to an absolute HTTP(S) URL served by the fixture server.
- Reload and stop navigation.
- Traverse back and forward when the backend declares the capability.
- Observe title, visible URL, loading state, and navigation outcome.
- Receive an engine-originated request to open a new view and resolve it before a declared deadline.
- Observe unexpected backend/view termination without corrupting surviving canonical state.
- Reconcile state after the chrome bridge reconnects.

## Frozen exclusions

- Multiple top-level windows.
- Downloads, file choosers, print, dialogs, permissions, media capture, fullscreen, and notifications.
- Find-in-page, zoom, reader mode, source view, developer tools, and accessibility inspection.
- Favicons and progress percentages.
- Authentication UI and certificate handling.
- Persistent history, bookmarks, tab recovery, profiles, or cross-engine storage transfer.
- Extension installation or execution.

## Identity rule

The release evidence must contain the SHA-256 of the compiled chrome bundle. Compared engine runs are invalid if these hashes differ.

The source must contain no references to WebKit, Servo, `window.webkit`, backend-specific globals, backend-specific CSS, or user-agent-based feature branches. A textual scan is a release gate; runtime hash equality is the stronger gate.

## Completion rule

Reference chrome v0 is complete when it can drive every scenario in `SCENARIO_CORPUS_V0.yaml` through the mock adapter. Backend adapters are later evidence releases, not prerequisites for freezing the denominator.
