# Evidence and findings

## Evidence bundle

One engine run produces an immutable directory:

```text
evidence/<evidence-id>/
├── manifest.json
├── build-manifest.txt
├── chrome/
│   ├── bundle.tar.zst
│   └── sha256.txt
├── fixtures/
│   ├── manifest.json
│   └── sha256.txt
├── scenarios/
│   └── HP-Sxxx/
│       ├── raw.ndjson
│       ├── normalized.ndjson
│       ├── report.json
│       └── screenshot.png
├── findings/
│   └── HP-Fxxxx.json
└── logs/
    └── harness.log
```

`manifest.json` is validated by `schemas/evidence-manifest.schema.json`. Every listed file is hashed. The manifest itself is hashed by the release record outside the bundle so it cannot solemnly attest to its own integrity.

## Raw evidence

Raw trace records are captured at the adapter boundary before semantic normalization. Each contains:

- Per-adapter ordinal.
- Wall and monotonic capture times.
- Direction.
- Backend callback or invoked operation name.
- Backend object reference suitable for correlation within that run.
- Lossless structured values where feasible.
- An explicit representation marker where a native value cannot be serialized directly.

Raw identifiers are not public protocol identifiers. They may be unstable or process-specific; that is part of why the raw layer exists.

## Normalized evidence

Normalized traces contain validated protocol envelopes and explicit suppression records. Every normalized event caused by a backend observation points to one or more raw records. Host-only events identify their host cause.

The normalizer may reshape representation and collapse duplicates under a documented rule. It may not:

- Invent an engine event that did not occur.
- Convert an unknown outcome into success.
- Remove an observable semantic difference solely to align engines.
- Attribute an ambiguous callback to the convenient navigation.
- Discard a late or duplicate callback without a suppression record.

## Finding taxonomy

### `semantic_mismatch`

Both backends expose behavior, but no one normalized meaning satisfies the frozen oracle without concealing a material difference.

Typical disposition: declare distinct capability semantics, revise a future protocol version, or record the abstraction boundary as non-portable.

### `unsupported_capability`

The backend or adapter cannot provide a required behavior under the pinned version.

Typical disposition: scenario `unsupported`, unless the capability was falsely declared supported.

### `adapter_defect`

The engine exposes sufficient behavior but the adapter maps, orders, correlates, or retains it incorrectly.

Typical disposition: fix adapter, rerun all affected scenarios, retain the superseded finding.

### `engine_defect`

The backend violates its own documented or reproducible behavior independently of hostproto.

Typical disposition: reduce to an upstream-quality reproduction.

### `fixture_defect`

The test input or oracle cannot establish the claimed result.

Typical disposition: mark affected run invalid, version the corrected corpus or fixture, and rerun. Never rewrite old evidence in place.

### `unresolved`

Evidence establishes a divergence but not its responsible layer.

Typical disposition: preserve the finding and run a bounded reduction session. `unresolved` is an honest status, not a queue where inconvenient results go to die.

## Finding lifecycle

1. **Open:** divergence or failed invariant observed.
2. **Classify:** compare raw evidence, normalized mapping, adapter code, and backend documentation.
3. **Reduce:** remove hostproto layers until the behavior either remains or disappears.
4. **Decide:** fix adapter, change a future contract, declare capability difference, invalidate fixture, or propose upstream.
5. **Supersede:** later evidence links to but never overwrites the original finding.

Findings validate against `schemas/finding.schema.json`.

## Upstream threshold

Propose a finding upstream only when:

- It reproduces outside the hostproto chrome and canonical reducer.
- The smallest known program and exact dependency revisions are included.
- Expected and observed behavior are stated without asserting ownership of upstream design.
- The issue is not merely missing production readiness already documented by the project.
- Existing upstream issues and current API direction have been checked.
- The report contains no private paths, tokens, user data, unrelated logs, or machine-specific identifiers.

An upstream proposal is a separate authorized action. Producing the reproduction does not grant permission to open an issue or submit a patch.

## Publication projection

The canonical evidence bundle may contain local paths, package inventories, driver information, or other unnecessary machine metadata. Before publication:

1. Classify the bundle for credentials, tokens, private identifiers, reachable endpoints, and unnecessary internal metadata.
2. Preserve the canonical private bundle unchanged.
3. Generate a redacted publication projection with its own manifest.
4. List every removed or generalized field and why it is non-semantic.
5. Never redact values that determine the result, such as engine revision, relevant feature flags, or trace ordering.

Local loopback fixture URLs are low consequence. Secrets and externally reachable endpoints are not. The review should preserve that distinction.
