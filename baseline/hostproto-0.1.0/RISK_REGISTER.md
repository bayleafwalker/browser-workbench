# Risk register

| ID | Risk | Signal | Control | Stop or recovery action |
| --- | --- | --- | --- | --- |
| R-01 | Denominator creep | A failing backend causes scenario or UI edits. | Freeze corpus per evidence version; independent diff review. | Revert edits; propose a later corpus version separately. |
| R-02 | WebKit-shaped protocol | Public types mirror WebKit callbacks or objects. | Mock first; require semantic names and cross-engine review. | Reject mapping and reopen protocol decision. |
| R-03 | Over-normalization | Traces align only after callbacks disappear. | Raw retention; explicit suppression records and counts. | Mark comparison invalid until each suppression is justified. |
| R-04 | Weak oracle | Failure cannot be assigned to fixture, adapter, or engine. | Deterministic fixtures; layered reduction and result taxonomy. | Mark run invalid or finding unresolved; do not claim divergence. |
| R-05 | Servo bridge absent | Chrome cannot receive an identical facade without engine changes. | Investigate bridge first in Wave 3; allow unsupported result. | Ship blocked/unsupported finding; reject engine-specific chrome. |
| R-06 | API churn | Pinned adapter stops building against current Servo. | Lock revisions; version evidence; avoid continuous-current promise. | Retain old result; update only through a new evidence release. |
| R-07 | Private fork gravity | Local patches accumulate faster than upstream acceptance. | Patch ledger and explicit private-fork budget. | Stop after minimal repro; do not maintain a browser fork. |
| R-08 | Timing flakiness | Sleeps, races, or callback timing change outcomes. | Virtual clock in mock; monotonic deadlines; event predicates; three repetitions. | Classify unstable run; fix harness before semantic analysis. |
| R-09 | Re-entrancy mismatch | Engine requires synchronous host decisions. | Queue boundary; deadline/default model; raw callback capture. | Record semantic mismatch if honest async bridge is impossible. |
| R-10 | False exactly-once claim | Timeout hides an effect that later commits. | Unknown-outcome state and reconciliation after deadlines. | Open finding; never retry effect under same logical intent automatically. |
| R-11 | UI identity weakened | Engine-specific bundles or runtime branches enter chrome. | Bundle hash gate, source scan, no engine global access. | Invalidate comparison. |
| R-12 | Environment masquerades as semantics | Driver, Wayland, package, or profile issue appears engine-specific. | Full environment manifest and clean ephemeral profiles. | Outcome `blocked`; reproduce under controlled environment. |
| R-13 | Evidence contains sensitive metadata | Paths, host data, or reachable endpoints enter logs. | Pre-publication classification and redacted projection. | Keep canonical bundle private; publish only manifested projection. |
| R-14 | Browser product returns by stealth | Work items add bookmarks, tiling, extensions, packaging, or daily-use fixes. | Permanent non-goals and scope-sentinel review. | Move proposal to a separate downstream charter or reject it. |
| R-15 | Career/portfolio rationalization | More months are justified by “signal” after evidence already exists. | Treat first comparative release as signal-complete. | Continue only for intrinsic interest or a selected upstream finding. |

## Highest-risk assumptions

1. The unchanged chrome can receive a semantically identical host facade in both engines.
2. `servo-gtk` exposes enough lifecycle behavior without a private Servo fork.
3. A minimal canonical navigation model can be defended across both backends.
4. The harness can distinguish transport timing from engine semantics.

These assumptions are investigated, not asserted. Their failure leaves useful findings if the evidence is complete.
