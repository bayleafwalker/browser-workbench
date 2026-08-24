# Decision records

## ADR-0001 — Research artifact, not browser

**Status:** accepted  
**Decision:** hostproto ends at versioned protocol, adapters, conformance traces, findings, and selected upstream reproductions.  
**Reason:** browser usefulness is not required for the research value and would make value concentrate in distant product milestones.  
**Consequence:** any browser becomes a separate downstream consumer.

## ADR-0002 — Protocol over Rust trait

**Status:** accepted  
**Decision:** the normative boundary is the versioned envelope and semantic contract visible to chrome.  
**Reason:** a Rust trait is language- and process-local and can accidentally encode one backend's object model.  
**Consequence:** internal traits may change without changing the protocol; wire or semantic changes require versioning.

## ADR-0003 — Frozen scenario corpus is the denominator

**Status:** accepted  
**Decision:** sufficiency and minimality are evaluated only against `SCENARIO_CORPUS_V0.yaml`.  
**Reason:** “serious browser chrome” is otherwise an invitation to permanent scope negotiation.  
**Consequence:** scenario changes create a new corpus version and cannot repair an in-progress engine run.

## ADR-0004 — Raw and normalized traces ship together

**Status:** accepted  
**Decision:** no normalized evidence release is valid without the causative raw adapter trace.  
**Reason:** normalization can otherwise conceal semantic differences and adapter defects.  
**Consequence:** trace storage is larger and backend details remain available for independent review.

## ADR-0005 — Partial-order conformance

**Status:** accepted  
**Decision:** compare invariants, causal relations, and terminal state rather than demanding identical callback order.  
**Reason:** engines may express the same observable semantics through different incidental sequences.  
**Consequence:** the harness needs explicit ordering constraints instead of golden full-trace equality.

## ADR-0006 — Capability differences remain visible

**Status:** accepted  
**Decision:** capabilities declare support source and semantic strength; unsupported or partial behavior does not receive success-shaped shims.  
**Reason:** engine neutrality is not sameness manufactured by the adapter.  
**Consequence:** compared runs may legitimately have different supported scenario sets.

## ADR-0007 — WebExtensions excluded

**Status:** accepted  
**Decision:** extension parsing, execution, permissions, isolated worlds, background workers, and API compatibility are outside hostproto.  
**Reason:** extension runtime semantics form a separate platform and would reintroduce the original distant milestone.  
**Consequence:** WebKitGTK's emerging WebExtension API is fact-base context only.

## ADR-0008 — Version-pinned observations

**Status:** accepted  
**Decision:** evidence claims apply only to exact protocol, corpus, chrome, fixture, adapter, engine, and environment identities.  
**Reason:** Servo and embedding APIs change; perpetual-current conformance would inherit Verso's maintenance failure mode.  
**Consequence:** later runs supersede but do not rewrite earlier findings.

## ADR-0009 — Sibling native content view

**Status:** accepted for v0  
**Decision:** chrome and content are separate native views composed by GTK, not a content view nested inside the chrome DOM.  
**Reason:** nested self-embedding introduces compositor and custom-element work unrelated to the host protocol question.  
**Consequence:** v0 does not test arbitrary DOM placement or overlapping chrome/content composition.

## ADR-0010 — Default deny for unanswered engine requests

**Status:** accepted  
**Decision:** a new-view request not resolved by its deadline is denied and traced.  
**Reason:** async chrome cannot hold native callbacks indefinitely, and silent allow creates effects after authority is lost.  
**Consequence:** adapters must expose or implement a bounded holding mechanism; impossible synchronous semantics become a finding.
