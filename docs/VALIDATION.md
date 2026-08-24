# Validation and release claims

Run the complete source checkpoint gate from the repository root:

```sh
PYTHONPATH=src python scripts/release_gate.py
```

It performs source/pin checks, Python unit and negative tests, chrome reducer tests, the 12 × 3 deterministic mock corpus, a disclosure scan, and three prerequisite probes. Native and oracle exit code 78 is accepted only as a truthful blocked observation; it never becomes a runtime pass.

Exit codes follow the runner contract:

| Code | Meaning |
|---:|---|
| 0 | requested gate passed |
| 1 | executed and failed/different |
| 2 | capability unsupported |
| 64 | invalid contract/input |
| 78 | prerequisite or adapter blocked |

## Release wording

Permitted for this checkpoint: “source and deterministic mock verified; 12 scenarios × 3 repetitions passed; native and oracle target gates blocked by missing prerequisites.”

Not permitted without target-host artifacts: “WebKitGTK passed,” “ServoGTK passed,” “Playwright matched,” or “native browser complete.” Compilation alone also does not prove runtime conformance.

The release report lives at `evidence/release-0.2.0/release-gate.json`. Each mock repetition has its own result, raw trace, normalized trace, and manifest. Native/oracle probes have separate records.
