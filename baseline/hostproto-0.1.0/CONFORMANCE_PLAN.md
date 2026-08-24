# Conformance plan

## Objective

Determine whether each pinned backend satisfies the frozen scenario corpus through the same chrome and protocol, while retaining enough native evidence to distinguish honest normalization from papering over differences.

## Test layers

### 1. Schema conformance

- Validate package JSON schemas.
- Validate every normalized envelope and trace record.
- Validate evidence manifests and findings.
- Reject unknown required fields and malformed correlation identifiers.

### 2. Mock semantic conformance

The mock adapter provides deterministic success, failure, delay, stale-event, and termination behaviors. It validates the protocol, reducer, harness, and scenario oracles before an external engine becomes involved.

The mock is not evidence about WebKitGTK or Servo.

### 3. Backend conformance

Run the unchanged harness separately against pinned WebKitGTK and servo-gtk revisions. Each run is independent and produces its own evidence bundle.

### 4. Comparative analysis

Compare declarations, normalized outcomes, partial-order constraints, raw-to-normalized mappings, suppressions, and unresolved observations. Do not compare incidental callback counts or timestamps as if equality were inherently virtuous.

## Deterministic fixture server

Fixtures are served over a loopback HTTP origin on an allocated port. Routes include:

- `/title-a`, `/title-b`: static pages with deterministic titles and links.
- `/counter`: increments a server-side run-local counter on each document request.
- `/history-a`, `/history-b`: linked pages for traversal.
- `/opens-view`: triggers one declared new-context request after explicit user action.
- `/slow`: streams headers and waits for the harness cancellation signal.
- `/close-without-response`: accepts then closes the connection.
- `/chrome/*`: immutable compiled reference-chrome assets.

Fixtures contain no third-party resources, DNS dependencies, analytics, randomized content, service workers, or external clocks. Their complete manifest and SHA-256 are stored in evidence.

## Run preparation

1. Record operating system, architecture, display protocol, graphics driver, GTK, Rust, engine, binding, and adapter versions.
2. Build once from a clean checkout with a retained lockfile.
3. Build chrome assets once and compute their SHA-256.
4. Start the fixture server and record its manifest hash.
5. Start one engine run with an empty ephemeral engine profile.
6. Confirm no previous run data is reused.

## Scenario execution

For each scenario:

1. Reset fixture and canonical session state unless the scenario declares continuity.
2. Begin raw capture before adapter initialization.
3. Complete handshake and record capability declarations.
4. Drive actions through `window.hostproto`; direct native test calls are forbidden except declared adapter test hooks.
5. Await declared terminal conditions using events and monotonic deadlines, not arbitrary sleeps.
6. Record scenario outcome and violated or satisfied invariants.
7. Flush raw and normalized traces before teardown.
8. Hash artifacts and add them to the evidence manifest.

## Oracle model

Conformance uses invariants and partial order:

- State invariants: exactly one active view, terminal lifecycle enforcement, stable identifiers.
- Request invariants: schema validity, exactly-one terminal response, explicit errors.
- Event invariants: required causal and per-object ordering.
- Scenario terminal state: expected URLs, titles, outcomes, and open-view set.
- Evidence invariants: complete provenance, raw references for normalized engine events, no missing files.

Byte-identical normalized traces are neither expected nor required. Two runs conform when both satisfy the same scenario oracle under compatible capability declarations.

## Outcome rules

| Outcome | Rule |
| --- | --- |
| `pass` | All required invariants hold under a supported capability declaration. |
| `fail` | A required invariant is violated or a supported declaration is not delivered. |
| `unsupported` | Scenario depends on a capability declared unsupported before execution. |
| `blocked` | Environment or build prevents a valid run; no engine-semantic claim follows. |
| `invalid` | Fixture, harness, changed denominator, degraded capability, or incomplete evidence defeats the oracle. |

## Repetition

- Mock scenarios run in CI on every contract change.
- Backend release evidence runs each scenario at least three times to expose non-deterministic ordering and timing defects.
- A result is stable only if outcome and invariant set agree across repetitions.
- Different raw callback counts are permitted if normalized semantics and suppression explanations remain valid.

## Visual check

One screenshot per backend demonstrates that the same chrome renders and controls a content view. Screenshots are supporting material only. The chrome bundle hash, source scan, and trace evidence prove the unmodified-UI claim.

## Invalid comparison conditions

Do not compare runs when:

- Protocol or scenario versions differ.
- Chrome or fixture hashes differ.
- One run used a private engine patch not recorded in its manifest.
- Profiles were not reset as required.
- Required raw trace segments are missing.
- An adapter changed between repeated runs without a new evidence identity.

The harness should refuse to generate a green comparative report under these conditions. Computers are quite capable of producing confident nonsense without assistance.
