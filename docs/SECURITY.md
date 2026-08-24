# Security boundary

- The built-in bridge binds only to `127.0.0.1`, requires an unguessable bearer value, accepts only `POST /v1/dispatch`, limits request bodies, disables caching, and suppresses token-bearing access logs.
- A single-writer lease fences state mutation. Observer access does not grant mutation, and handover does not grant approval.
- Uploads are limited to declared fixture roots. Downloads are quarantined and content-addressed before further handling.
- Dialogs, permissions, popups, downloads, and file choosers are browser-owned decisions with explicit tokens and deny defaults.
- URLs are limited to absolute HTTP(S) or `about:` values in the deterministic backend. Production policy may narrow this further.
- Secrets are redacted before export. Release packaging performs an additional disclosure scan.
- Adapter crashes create terminal page events and retain partial evidence. Recovery requires a verified checkpoint and a new lease epoch.

The source package contains no credentials and does not accept credentials through the protocol examples. Native package installation, signing, sandboxing, and distribution hardening remain target-host responsibilities.
