# Project charter

## Decision

Build an executable conformance study for an engine-neutral browser-host contract. Do not build a browser product.

## Purpose

Browser chrome is commonly coupled to one engine's embedding and extension semantics. hostproto asks whether the chrome-facing boundary can be made explicit, versioned, and honest across WebKitGTK and Servo.

The output is not merely a successful abstraction. The output is the evidence describing which semantics normalize cleanly, which require declared capability differences, and which cannot be normalized without lying.

## Owned state and responsibilities

### Reference chrome

- Renders the declared controls and canonical state.
- Calls only `window.hostproto`.
- Contains no engine identification or conditional behavior.
- Is built once; its content hash must match across evidence runs.

### Host core

- Owns canonical session and view state for the duration of a run.
- Validates envelopes, correlates requests, and enforces temporal rules.
- Applies normalized events to a deterministic reducer.
- Records normalized traces and explicit suppression decisions.
- Does not contain WebKitGTK- or Servo-specific types.

### Engine adapter

- Owns engine handles and engine-specific callbacks.
- Converts host commands into backend operations.
- Emits raw observations before normalization.
- Maps supported semantics into the protocol.
- Declares missing or partial capabilities rather than inventing success.

### Conformance harness

- Serves deterministic local fixtures.
- Drives the frozen scenario corpus.
- Captures raw traces, normalized traces, artifacts, and version metadata.
- Evaluates invariants and partial-order constraints.
- Produces findings without deciding them away.

## Value model

Value must accumulate at valid stopping boundaries:

- A frozen scenario and protocol release is a complete design artifact.
- A single-engine trace release is a complete empirical result.
- A cross-engine comparison is a complete conformance result.
- A semantic mismatch is a publishable finding.
- A reduced upstream report is a complete external contribution.

The project must not require a later consumer application to make earlier work worthwhile.

## Success conditions

The project succeeds when all of the following hold for a release boundary:

1. The denominator is versioned and unchanged during the run.
2. The protocol and schemas validate.
3. Chrome assets are byte-identical across compared runs.
4. Raw and normalized traces are retained with complete provenance.
5. Every scenario has a declared result: pass, fail, unsupported, blocked, or invalid.
6. Every divergence is classified or explicitly left unresolved.
7. Claims are limited to pinned engine, adapter, fixture, and protocol versions.

Cross-engine behavioral equality is not required for project success.

## Change control

- Changing a scenario oracle increments the corpus version.
- Adding a required capability increments the protocol minor version before 1.0.
- Changing normalized semantics requires a decision record and invalidates direct comparison with earlier traces unless a migration is supplied.
- Adding a browser-product requirement is rejected here. It may be proposed as a separate downstream project.
- Adding extension execution is rejected here. It may be proposed as a separate research package.

## Stop conditions

Stop the current wave when any of these occurs:

- The next action requires renderer implementation rather than embedding work.
- A backend requires a long-lived private fork merely to satisfy the reference corpus.
- The same chrome assets cannot run without engine-specific branches.
- A normalized event would conceal a material semantic difference.
- The fixture or oracle cannot distinguish an adapter defect from an engine behavior.
- The work has crossed its release boundary and no explicit next wave was authorized.

Stopping produces a finding and a release candidate, not an apology.
