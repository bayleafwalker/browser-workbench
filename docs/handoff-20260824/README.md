# Browser Workbench handoff — 2026-08-24

This package is the durable continuation point for the ChatGPT conversations
named **Browser** and **Summarize Browser Session Progress**.

The later conversation did create one durable artifact before repeated
`Too many requests` failures:

- `source/browser-workbench-0.2.0-source-checkpoint.zip`
- created `2026-08-24T16:05:10Z` (`19:05:10 EEST`)
- SHA-256 `0bc2f9a12ae49b42af2165edeaa4dbba54e51708d7effbc9dde148a30f096fe2`
- size `266387` bytes

That archive, rather than the incomplete chat transcript, is the authoritative
checkpoint. It is intact and independently revalidated during consolidation.

## Bottom line

Version `0.2.0` is a coherent **source-and-deterministic-mock checkpoint**. It
is not yet a working WebKitGTK browser, a native evidence release, or a
WebKitGTK-versus-Servo comparison.

What exists:

- the frozen `hostproto` `0.1.0` research baseline and its 16 scenarios;
- a new typed Browser Workbench v1 protocol and 12-scenario corpus;
- Python control/evidence logic and deterministic mock backend;
- reference chrome reducer and minimal GTK/WebKitGTK/Servo/Playwright source
  boundaries;
- 36/36 mock repetitions, 15 Python tests, 3 chrome reducer tests, package
  integrity checks, and disclosure scanning passing.

What does not exist yet:

- a connected native adapter process;
- a GTK shell that hosts a live content view and routes its controls;
- WebKitGTK runtime or 12-by-3 evidence;
- Playwright oracle runtime evidence;
- ServoGTK runtime or comparative evidence;
- a confirmed Git repository, branch, commit, or remote for the checkpoint.

The phrase “Waves 2–3 source checkpoint” in the source archive must not be
shortened to “Waves 2–3 complete.” Under the preserved baseline plan, Wave 2
means real WebKitGTK evidence and Wave 3 means real Servo/comparative evidence.

## Package contents

- `CURRENT_STATE.md` — architecture, chronology, delivered surface, and precise
  completion boundary.
- `VALIDATION.md` — commands and results independently rerun during this
  consolidation.
- `RISKS_AND_DECISIONS.md` — the important scope and implementation tensions.
- `NEXT_RUN_PROMPT.md` — a self-contained prompt for resuming in local Codex,
  Claude Code, or another repository-native agent.
- `STATE.json` — machine-readable checkpoint state.
- `source/browser-workbench-0.2.0-source-checkpoint.zip` — the unchanged source
  checkpoint.

## Recommended continuation

Move the archive into a real Git repository and continue on an Arch or NixOS
host with GTK4/WebKitGTK development packages and a display/Xvfb. Keep
WebKitGTK as the only gating native lane until one end-to-end real session and
then the 12-scenario corpus are evidenced. Playwright follows as oracle;
ServoGTK remains non-gating.

Do not start by expanding the protocol or UI. The current missing object is a
real adapter path, not another architecture document.

## Disclosure note

No credentials, tokens, customer data, employer-confidential material, or
reachable private endpoints were found. The unchanged source checkpoint does
contain one low-consequence ephemeral ChatGPT Work scratch path inside a
Playwright missing-dependency error record. It is retained to preserve archive
integrity. The package intentionally contains the author's name and pinned
dependency identities.

