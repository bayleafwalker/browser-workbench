# Runner contract v1

The runner is a release-validation executor. It is not a planner and not a
generic browser agent.

## Ownership split

The planner owns what to test, hypotheses, interpretation, retry decisions, and
whether the plan should change. The runner owns browser lifecycle, declared
action execution, observation capture, evidence production, deterministic gate
evaluation, and truthful capability reporting.

## Inputs

A run spec declares:

- immutable run and protocol versions;
- backend and variant identity;
- required capabilities and allowed provider classes;
- ordered workflow steps with per-step deadlines;
- mutation and profile policy;
- evidence projections and budgets;
- deterministic gates; and
- expected fixture/chrome/source digests where applicable.

Undeclared operations are rejected. The runner cannot append a convenient
diagnostic action to a release run.

## Capability truth

Each capability result has four independent axes:

1. `availability`: `supported`, `partial`, `unsupported`, or `blocked`.
2. `provider`: `engine`, `adapter`, `host`, `injected`, `oracle`, or `mock`.
3. `semantics`: `exact`, `normalized`, `partial`, or `none`.
4. `verification`: `runtime`, `source-audit`, `declared`, or `none`.

`native_required` gates accept only `provider: engine` with runtime evidence.
Host composition or injected JavaScript may be useful, but does not graduate to
native by repeated assertion.

## Result envelope

Top-level status is one of:

- `passed`: every required step and gate passed.
- `failed`: execution completed and a declared invariant failed.
- `unsupported`: backend truthfully lacks a required capability.
- `blocked`: environment or build prevented a valid execution.
- `invalid`: the denominator, fixture, evidence, or integrity boundary failed.

The result contains step receipts, capability report, raw and normalized
artifact references, gate outcomes, environment identity, deviations, and one
terminal reason. A successful browser exit is not sufficient for `passed`.

## Gate classes

- Contract: schemas, versions, frozen corpus and source scans.
- Capability: required operation, provider, semantics and verification class.
- Execution: exactly-once terminal receipts and no undeclared retries.
- Evidence: raw/normalized completeness, hashes, budgets and redaction records.
- Determinism: repeated outcome and invariant set stability.
- Comparison: identical denominator and immutable inputs.
- Recovery: checkpoint replay and single-writer fencing.
- Native: build, runtime identity, display stack and three repetitions.

Release profiles may select different gates, but cannot silently waive one. A
waiver is a versioned deviation and changes the release classification.

## Failure and recovery

- The runner never retries an effect automatically.
- An adapter crash terminates active steps, flushes captured evidence, and
  attempts checkpoint reconciliation without claiming action failure implies
  no effect.
- Hash mismatch never regenerates an artifact in place.
- Partial output is retained and marked incomplete.
- Source validation can pass while native validation is blocked; those are
  separate release claims.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Requested profile passed |
| 1 | Executed and failed |
| 2 | Required capability unsupported |
| 64 | Invalid spec or evidence |
| 78 | Environment/toolchain blocked execution |

Machine-readable output is authoritative; exit codes are a shell convenience.
