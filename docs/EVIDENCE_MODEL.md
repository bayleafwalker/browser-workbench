# Evidence model

Every run writes a content-addressed manifest over its artifacts. Artifacts carry a surface class:

| Surface | Meaning |
|---|---|
| raw | backend callback or binary capture before normalization |
| normalized | protocol event or checkpoint derived from raw/host state |
| redacted | export safe for a wider audience under the declared profile |
| diagnostic | capability and prerequisite observations |
| contract | run spec, result, gate, or comparison record |

Normalized events carry raw references when an adapter callback caused them. Receipts separately record attempted, accepted, executed, and verified state, plus causal event IDs and before/after state digests. A successful transport call is not sufficient evidence of execution.

`page.observe` and `session.export` are byte-bounded. If a projection cannot fit, loss is explicit and the full recoverable projection is placed in a content-addressed raw artifact. If even the mandatory envelope cannot fit, the request is invalid rather than silently truncated.

Redaction occurs before export persistence. Sensitive key names, bearer values, and common credential patterns are replaced, with rule IDs and counts recorded. Disclosure scanning additionally rejects local workspace paths and recognizable production credential forms from the release source package.

Comparison reads immutable evidence inputs, hashes before and after, and blocks when a declared digest differs or an input changes during the read. The semantic projection ignores data only when the comparison contract declares the tolerance.
