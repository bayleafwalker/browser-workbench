# Playwright oracle lane

This external oracle is pinned separately from WebKitGTK. It provides comparison evidence, not proof that WebKitGTK behaves identically. It executes only declared steps, launches an isolated context, records raw events, performs zero retries, and exits non-zero for unsupported or failed operations.

## Running it

The oracle needs a host that can actually launch the pinned WebKit build. Installing the npm package is not sufficient: the bundled browser links against Debian-era sonames (`libicu*.so.74`, `libflite.so.1`, `libbacktrace.so.0`), so on a distribution shipping a newer ICU it downloads successfully and then cannot start. `scripts/native_gate.py playwright` reports that as **blocked**, naming the libraries.

On a Debian/Ubuntu host:

```sh
npm ci
npx playwright install --with-deps webkit
```

Anywhere else, the pinned container image is the enabled oracle host, and it is what `scripts/oracle_differential.py` uses automatically:

```sh
podman run --rm --network=host -v "$PWD/../..":/work -w /work \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  mcr.microsoft.com/playwright:v1.62.1-noble \
  node oracle/playwright/runner.mjs RUN_SPEC OUTPUT_DIR
```

Host networking is required so the oracle can reach the loopback fixture server.

## Differential

`scripts/oracle_differential.py` runs one declared workflow on both lanes and compares them under `examples/tolerances-oracle.json`. That file declares the three surfaces an external oracle structurally lacks — gates, a capability report, and receipts — and the comparison report states every suppression it applied. Step identity, method, per-step status, and the terminal code are compared strictly.

A difference is a finding to investigate. It is never evidence that WebKitGTK is wrong, and the oracle never gates the native lane.

## The whole denominator

`scripts/oracle_corpus_differential.py` poses the frozen twelve-scenario corpus to both lanes, as classified by `spec/ORACLE_CORPUS_V1.json`:

- **applicable** scenarios (`WB-S003` to `WB-S008`) have a declared workflow in `examples/oracle-corpus/` that both lanes execute. Each declares which frozen assertions it covers and which it omits, with the reason, so the oracle's reach is stated rather than implied. Two of them are supposed to end in an error on both lanes and declare that terminal code.
- **inapplicable** scenarios name the host mechanism the oracle structurally lacks: leases, byte-bounded observation, checkpoints, web-process termination, the comparison engine, input integrity. They are neither passed nor failed.

The runner mirrors the workbench result shape far enough that the same `$step` references and `expect` clauses resolve on both lanes, and enumerates targets with the same script so `data.targets.N` is the same element. It then acts through Playwright's own pointer, file chooser, and download APIs — that independence is the point. Script dialogs are held open until a declared decision, as the engine does for the host. What Playwright cannot express — a permission request event, terminating a WebKit web process — is refused as `capability_unsupported`, never simulated.

The report always lists twelve scenarios, each as exactly one of `equivalent`, `different`, `blocked`, or `inapplicable`.
