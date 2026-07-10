# Secrets

Per-environment `.env` files holding **operator-supplied secrets only** — the
project's own API keys/tokens (declared in a core service's `secrets:` block)
plus the doctrine-injected `TELEMETRY_API_KEY`. `example.env` is a committed,
keys-only manifest emitted by `docex compile`; reconcile a real `<env>.env`
from it with `docex secrets scaffold <env>` (never copy by hand).

`dev.env`, `test.env`, `stage.env`, `prod.env` are gitignored and must never be
committed.

This is one of three configurable-value categories (see
`config_and_secrets.md`):
- **secrets** (here) — operator-supplied, value-blind tooling.
- **TTE** (`../tte/`) — engine credentials `docex` mints (e.g. `POSTGRES_PASSWORD`);
  no longer listed here.
- **config** (`../config/`) — non-secret per-env values.

For the smoke-test walkthrough, see `../../../PRE_CUT_CHECKLIST.md`.
