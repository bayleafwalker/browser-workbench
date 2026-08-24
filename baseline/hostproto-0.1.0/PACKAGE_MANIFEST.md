# Package manifest

## Core

| File | Purpose |
| --- | --- |
| `README.md` | Project thesis, stopping boundaries, and permanent exclusions. |
| `CHARTER.md` | Authority, success conditions, value model, and change control. |
| `FACT_BASE.md` | Current external facts and primary sources as of 2026-08-22. |
| `package.yaml` | Machine-readable package metadata and invariants. |
| `CHANGELOG.md` | Package-level change history. |
| `SHA256SUMS` | Integrity hashes for every other file in this package. |

## Denominator and contract

| File | Purpose |
| --- | --- |
| `REFERENCE_CHROME_V0.md` | Frozen UI, composition, observable state, and excluded surface. |
| `SCENARIO_CORPUS_V0.yaml` | Machine-readable denominator and scenario-level oracles. |
| `CAPABILITY_MODEL.md` | Capability negotiation and semantic support declarations. |
| `HOST_PROTOCOL_V0.md` | Envelope, methods, events, errors, and versioning rules. |
| `TEMPORAL_AND_STATE_SEMANTICS.md` | Ordering, deadlines, cancellation, re-entrancy, and canonical reducer rules. |

## Evidence and implementation

| File | Purpose |
| --- | --- |
| `CONFORMANCE_PLAN.md` | Harness, fixtures, equivalence rules, and execution procedure. |
| `EVIDENCE_AND_FINDINGS.md` | Evidence bundle, classification taxonomy, and upstreaming criteria. |
| `ADAPTER_NOTES.md` | WebKitGTK, servo-gtk, and mock-adapter boundaries and unknowns. |
| `DELIVERY_PLAN.md` | Work waves, gates, rollback boundaries, and release outputs. |
| `RISK_REGISTER.md` | Project-specific risks, controls, and stop signals. |
| `DECISION_RECORDS.md` | Architectural decisions fixed before implementation. |
| `AGENT_PROMPTS.md` | Ready-to-use worker, assessor, backlog, and upstream-repro prompts. |

## Schemas and examples

| File | Purpose |
| --- | --- |
| `schemas/protocol-envelope.schema.json` | Wire-envelope validation. |
| `schemas/trace-record.schema.json` | Raw and normalized trace-record validation. |
| `schemas/evidence-manifest.schema.json` | Evidence provenance and file-integrity validation. |
| `schemas/finding.schema.json` | Structured finding validation. |
| `examples/evidence-manifest.example.json` | Illustrative, explicitly non-evidentiary manifest. |
| `examples/finding.example.json` | Illustrative classified finding. |
| `examples/normalized-trace.example.ndjson` | Illustrative handshake and lifecycle trace. |

## Intended consumers

- A planner generating the implementation backlog.
- A Rust worker implementing one bounded wave.
- An assessor independently checking protocol and evidence claims.
- A maintainer deciding whether a divergence belongs upstream.
- A future reader reconstructing what was actually tested against which versions.
