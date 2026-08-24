# Differential runner

The runner compares evidence, not engine branding. Baseline and candidate directories must each contain an immutable `result.json`; their full tree digests are checked before and after comparison. An expected digest mismatch returns `candidate_mutated` or `integrity_mismatch` and emits no equivalent report.

The three declared comparison lanes are:

1. `examples/variants/webkitgtk-stable-ephemeral.json` — primary baseline;
2. `examples/variants/webkitgtk-stable-persistent.json` — configuration candidate;
3. `examples/variants/playwright-webkit-oracle.json` — external semantic oracle.

ServoGTK’s `examples/variants/servo-gtk-experimental.json` is a research candidate, never a release baseline. Its unsupported capabilities must remain visible in the capability diff.

Run comparison only after each lane has completed the same frozen denominator:

```sh
PYTHONPATH=src python -m workbench.cli compare \
  evidence/webkitgtk-stable-ephemeral \
  evidence/webkitgtk-stable-persistent \
  --tolerances examples/tolerances.json
```

`step_order: by_step_id` permits independent steps to arrive in a different order while retaining step identity. Wall-clock and raw callback cosmetics are outside the semantic projection. Status, step outcome/error/receipt verification, gates, terminal code, and capability declarations remain compared unless an explicit versioned tolerance says otherwise.
