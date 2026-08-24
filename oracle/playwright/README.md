# Playwright oracle lane

This external oracle is pinned separately from WebKitGTK. It provides comparison evidence, not proof that WebKitGTK behaves identically. It executes only declared steps, launches an isolated context, records raw events, performs zero retries, and exits non-zero for unsupported or failed operations.

Install the pinned package and browser binaries on an enabled oracle host, then run:

```sh
npm ci
npx playwright install --with-deps webkit
node runner.mjs ../../examples/playwright-run.json ./evidence
```
