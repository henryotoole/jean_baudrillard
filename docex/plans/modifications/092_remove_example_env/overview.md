# Mod 092 — remove `example.env` entirely

## Problem

`docex compile` emits a committed, keys-only `infra/secrets/example.env`
manifest. With the three-category configurable-value model (mods 076-084) and
the `docex secrets scaffold` / `docex config scaffold` tooling, that file is
obsolete:

- Its key set is fully derivable on demand from committed sources (`infra.yml`
  `secrets:` blocks + backing `kind: secret` vars + doctrine-injected keys) via
  `secret_manifest`. `scaffold` reconciles `<env>.env` directly from that set
  and `secrets status` lists it — nothing reads `example.env`.
- It is a **derived artifact checked into git** (stale-cache risk), and it is
  **asymmetric** with config, which never had an `example.config.env`. Removing
  it makes the two categories symmetric: both derive their key set from
  committed `infra.yml` and reconcile gitignored value files via `scaffold`.

## Change

Remove `example.env` from `docex` entirely. `docex compile` no longer writes it;
`emit_example_env` is deleted. The shared renderer `render_manifest_env` stays
(`docex secrets/config scaffold` still use it). `secret_manifest` stays — it is
the source of truth for `scaffold`, `status`, and the mod-091 required-secret
guard.

## Doctrine (already committed, doctrine-leads-code)

The doctrine half shipped first (per `docex_process.md` — doctrine changes
before code). `example.env` was removed from `cicl.md`, `inception.md`,
`infrastructure.md` (operator, by hand) and from the three specifics files
`config_and_secrets.md`, `transfer_tables.md`, `telemetry_infra.md` (design
agent). `config_and_secrets.md § Direct generation` now defines the **secret
manifest** as a computed-on-demand concept and notes config is symmetric. This
mod is the **code half** that makes the executor match.

## Scope of the code half

Delete the emit path + repoint every `example.env` reference in code/tests to
`secret_manifest` (the invariant each test checks — "config/postgres keys don't
leak", "telemetry key is present and ordered first" — is unchanged; only the
vehicle, a rendered file, is replaced by the manifest it was rendered from).

See `implementation.md` for the exact sites.

Nothing reads `example.env`, so this is behavior-removing only — no new
behavior. Unit + integration tests must stay green; no boundary changes.

## Walk-time follow-up (not in this mod)

The two smoke test projects (`docex/test_projects/{fixed,elastic}`) carry a
committed `example.env` and a `!example.env` gitignore un-ignore. Those get
cleaned when the pending 1.5.0 re-roll walk regenerates the seeds (`docex
compile` will simply stop producing the file). Not hand-edited here.

## Versioning

Folds into the open **1.5.0** re-roll alongside mod 091. No version bump.
CHANGELOG note added under `[1.5.0]`.
