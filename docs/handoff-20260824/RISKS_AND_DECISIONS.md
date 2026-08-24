# Risks and decisions for continuation

## 1. Wave naming currently overstates progress

The `0.2.0` delivery says it completes a “Waves 2–3 source checkpoint.” The
preserved baseline defines Wave 2 as actual WebKitGTK evidence and Wave 3 as
actual Servo/comparative evidence. Both statements can coexist only if
“source checkpoint” remains explicit.

**Recommendation:** call this release `0.2.0 source/mock checkpoint` or
`native-preparation checkpoint`. Do not tag it as `webkitgtk-evidence` or
`servo-evidence`.

## 2. The project has two charters

The frozen baseline says “build an executable conformance study; do not build a
browser product.” The newer top-level README says “minimal Linux-first browser
workbench” and includes a GTK shell, human takeover, evidence access, profiles,
and broad observation/action semantics.

This is not fatal. The clean interpretation is:

- `hostproto` remains a frozen research denominator;
- Browser Workbench is a downstream product/research harness consuming and
  extending those lessons;
- native evidence remains valuable even if the downstream shell never becomes
  a daily browser.

**Recommendation:** record that relationship as an ADR before expanding scope.
Do not rewrite the baseline.

## 3. Native source is currently a boundary sketch

The GTK shell, WebKitGTK worker, and ServoGTK worker are small source probes,
not connected runtime implementations. A successful `cargo check` will prove
API compatibility, not protocol conformance.

**Recommendation:** make the first native milestone one end-to-end navigation
through the public protocol with retained raw and normalized evidence. UI
polish and corpus breadth follow that proof.

## 4. The control-plane boundary is unresolved in executable form

The source implies Python owns runner/evidence state while Rust owns GTK/native
objects. The bridge is an authenticated loopback HTTP dispatcher, but the
native worker currently prints JSON to stdout and does not use that bridge.

**Recommendation:** keep Python as the evidence/control plane for the proof,
but choose and document one bidirectional adapter transport. Avoid maintaining
HTTP commands in one direction and ad-hoc stdout events in the other unless
both are wrapped by one ordered protocol with lifecycle and backpressure
semantics.

## 5. The main runner cannot execute an oracle or native adapter

All non-mock backends are rejected by design. The Playwright runner is a
separate program with only a subset of operations and a different result
shape.

**Recommendation:** introduce an adapter process contract before implementing
more engine operations. The same runner must be able to start/attach, inspect
capabilities, execute a declared run once, collect artifacts, and terminate it.

## 6. Evidence gates are stronger than runtime coverage

The package has sound evidence principles, but the current mock corpus mostly
tests the model of the system. It cannot validate GTK thread affinity,
WebProcess failure ordering, actual navigation cancellation, user-content
injection, popup decision timing, download lifecycle, or profile persistence.

**Recommendation:** retain the mock corpus as a contract regression suite, not
as a proxy for native confidence.

## 7. ServoGTK can consume the project if admitted too early

The package correctly marks ServoGTK experimental and non-gating. Its public
widget surface lacks most required semantic hooks.

**Recommendation:** do not work around those gaps in the host. Finish
WebKitGTK plus the oracle first. Then treat Servo as a bounded capability and
finding exercise with an explicit stop condition.

## 8. Repository provenance is missing

The durable artifact is a ZIP with internal hashes but no Git metadata. There
is no confirmed branch, commit, tag, remote, issue tracker, or CI history.

**Recommendation:** import the archive unchanged as the first repository
commit, record the archive hash in the commit message, and tag it
`source-checkpoint-v0.2.0`. Begin native work on a new branch.

## 9. Work-mode completion is not a reliable recovery mechanism here

The failed chats repeatedly attempted to carry a large conversation plus a
source/evidence tree. Resuming the same cloud context risks paying repeatedly
for the same payload without improving the durable state.

**Recommendation:** use this package as the new denominator in a local
repository-native session. Keep each implementation slice independently
committable and ask for a handoff file at each gate. The evidence repository,
not the chat transcript, should own progress.

