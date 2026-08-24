# Agent prompts

These prompts are generation kernels, not substitute specifications. Every session must cite the exact package version and wave it is executing.

## 1. Orientation and backlog generation

```text
Orient on the hostproto repository before proposing work.

Authority order:
1. CHARTER.md and DECISION_RECORDS.md
2. REFERENCE_CHROME_V0.md and SCENARIO_CORPUS_V0.yaml
3. HOST_PROTOCOL_V0.md, CAPABILITY_MODEL.md, and TEMPORAL_AND_STATE_SEMANTICS.md
4. Current DELIVERY_PLAN.md wave
5. Implementation and evidence already present in the repository

Task: generate the smallest dependency-ordered backlog for Wave <WAVE> only.

For each item provide:
- owned files and responsibility boundary;
- input and output artifacts;
- scenario IDs enabled or tested;
- targeted validation;
- failure/rollback boundary;
- whether the item changes contract, implementation, fixture, harness, or evidence.

Reject backlog items for browser UX, persistence, extensions, distribution, performance competition, or a third engine. Do not carry work into the next wave.

Finish with:
- critical path;
- work that can run independently;
- unresolved decisions that genuinely block implementation;
- explicit confirmation that the frozen denominator was not changed.
```

## 2. Bounded implementation worker

```text
Implement backlog item <ITEM_ID> in hostproto Wave <WAVE>.

Read the authoritative project documents first. Do not infer browser-product requirements from generic browser APIs or upstream examples.

Constraints:
- The reference chrome calls only window.hostproto.
- Protocol and scenario changes are forbidden unless this task explicitly authorizes a new version.
- Capture raw adapter observations before normalization.
- Unsupported operations fail explicitly; do not add a compatibility shim.
- Preserve exact request terminality, lifecycle, cancellation, deadline, and re-entrancy rules.
- Do not perform external writes, open upstream issues, or modify system packages.

Required output:
1. Changed files and responsibility of each change.
2. Scenarios and invariants covered.
3. Commands/tests run with results.
4. New raw or normalized evidence, clearly marked mock or backend-derived.
5. Deviations, ambiguous semantics, and finding candidates.
6. Rollback instructions.
7. Stop at this item boundary; do not begin adjacent backlog work.
```

## 3. Independent conformance assessor

```text
Assess hostproto evidence bundle <EVIDENCE_ID> independently.

Do not trust the generated scenario report before inspecting:
- evidence manifest and hashes;
- protocol, corpus, chrome, fixture, adapter, and engine identities;
- raw records underlying normalized engine events;
- suppression records;
- request terminality and partial-order constraints;
- repeated-run stability.

For every scenario return exactly one outcome: pass, fail, unsupported, blocked, or invalid.

Open a finding when:
- a supported capability fails its oracle;
- raw and normalized semantics diverge materially;
- callback attribution is ambiguous;
- a suppression lacks a defensible rule;
- an environmental or fixture fault defeats the claim.

Classify findings only when evidence supports the responsible layer. Prefer unresolved over confident invention.

End with:
- release recommendation: accept, accept with declared unsupported scenarios, or reject;
- findings blocking release;
- claims the evidence does and does not support.
```

## 4. Cross-engine comparison assessor

```text
Compare hostproto evidence bundles <WEBKIT_EVIDENCE_ID> and <SERVO_EVIDENCE_ID>.

First verify comparison validity:
- same protocol and corpus versions;
- same chrome and fixture hashes;
- recorded adapter/engine/environment identities;
- complete raw and normalized evidence;
- stable repeated outcomes.

Compare:
- capability declarations;
- scenario outcomes;
- canonical terminal state;
- required causal and partial-order relations;
- raw-to-normalized mapping rules;
- suppression categories;
- unresolved observations.

Do not require identical callback counts, timestamps, incidental ordering, rendering pixels, or native error messages.

Separate conclusions into:
1. portable semantics demonstrated;
2. capability differences honestly represented;
3. semantic mismatches resisting normalization;
4. adapter or harness defects preventing a conclusion;
5. evidence invalidities.

State the narrowest defensible cross-engine claim. Do not upgrade a demo into a browser-platform claim.
```

## 5. Finding reduction and upstream candidate

```text
Reduce hostproto finding <FINDING_ID>.

Goal: determine whether the behavior survives after removing the reference chrome, host reducer, normalized protocol, and unrelated adapter code.

Procedure:
1. Reproduce from the pinned evidence identity.
2. Remove hostproto layers one at a time.
3. Retain exact engine/binding revisions and environment facts.
4. Produce the smallest deterministic program and fixture that still exhibits the behavior.
5. Search current upstream documentation and issues before recommending submission.

Return:
- reproduced/not reproduced;
- smallest responsible layer established;
- revised finding classification and confidence;
- minimal repro files and exact run command;
- expected versus observed behavior;
- disclosure review;
- whether an upstream report is useful, redundant, or premature.

Do not submit anything externally. Stop at a reviewable candidate.
```

## 6. Scope sentinel

```text
Review proposed hostproto change <CHANGE> solely for scope integrity.

Reject or redirect changes that:
- add daily-use browser value as a success criterion;
- add bookmarks, history persistence, sync, profiles, tiling, extensions, packaging, DRM, or performance competition;
- add engine-specific chrome branches;
- hide capability differences behind success-shaped shims;
- change the frozen corpus to accommodate a backend result;
- create a long-lived private engine fork;
- require later milestones to make the current output valuable.

Allow changes that improve protocol precision, oracle quality, evidence provenance, adapter correctness, minimal reproduction, or explicit capability declaration.

Return: accept, revise, or move to separate project. Cite the governing charter or decision record.
```

## 7. Release-note generator

```text
Generate hostproto release notes from evidence and merged changes only.

Include:
- release boundary and exact versions;
- scenario outcome matrix;
- supported and unsupported capability declarations;
- confirmed findings and unresolved questions;
- changes since the prior release;
- comparison limits;
- reproducibility instructions;
- rollback or supersession relationship.

Exclude aspirational browser features, virality claims, and general statements about engine quality. A release says what this evidence established, no more.
```

## Prompt-level guardrail

If an agent concludes that a missing capability should be shimmed, ask it to identify which frozen scenario requires the behavior, which raw evidence supports the proposed semantics, and why declaring the capability unsupported is insufficient. If it cannot answer all three, the shim has not earned its keep.
