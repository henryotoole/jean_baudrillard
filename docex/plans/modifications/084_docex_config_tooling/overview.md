# Mod 084 — `docex config` command group (permissions inverted)

Part of the [envmageddon campaign](../../campaigns/003_envmageddon/implementation_plan.md)
(step 2, mod 9 of 11). Adds the config-category tooling by reusing the Mod 083
engine with a `CONFIG_POLICY` — same four ops plus `get`, with the permission
asymmetry that *is* the secret/config boundary made operational.

## Why

`config_and_secrets.md § Tooling` (the config table): "config gets the same ops
with permissions inverted."

| | secret | config |
| - | ------ | ------ |
| `status` shows | SET/UNSET only | the actual values |
| `set` value channel | tty / `--from-file` only | positional arg OK |
| `get` / print value | never | fine |
| `copy` | value-blind | value-blind (lower-stakes) |

The engine is already category-parametrized (`CategoryPolicy`), so this is a
`CONFIG_POLICY` + a `config_manifest` + a `get` op + the `docex config` CLI — no
engine rewrite.

## Two fixes the engine needs first

1. **`render_manifest_env` renders the wrong category.** `scaffold` calls
   `render_manifest_env`, which today rebuilds the *secret* manifest internally.
   For config scaffold that would write **secret** keys into the config file.
   Fix: `render_manifest_env` takes the manifest entries as a parameter;
   `emit_example_env` passes the secret manifest, `scaffold` passes
   `_manifest(ctx, policy)`.
2. **`SecretEntry` is a misnomer for config.** Rename it to `ManifestEntry`
   (a declared `(key, desc, source)` entry, category-agnostic) in
   `cicl/categories.py` and update the engine's import. Small, clean.

## `docex.md § config` — a doctrine edit (orchestrator, not sub-agent)

`docex.md` documents `### secrets` but not `### config` — the flagged gap
(`implementation_plan.md` #2). `config_and_secrets.md § Tooling` already mandates
these config ops, so adding the matching `### config` section to `docex.md`
documents an existing rule, not a new one. Per the sub-agent-never-edits-doctrine
discipline, the implementer does **not** touch `docex.md`; the reviewing
orchestrator adds the section (mirroring `### secrets`).

## Scope

**In:** `config_manifest` (`cicl/categories.py`); `SecretEntry → ManifestEntry`
rename; `render_manifest_env` param fix; `CONFIG_POLICY`, `get_key`, and the
config branch of `_manifest` (`secretsmgmt/engine.py`); `docex config` nested CLI
(`__main__.py`); tests.

**Out (orchestrator does it):** the `docex.md § config` doc section. **Out
entirely:** `tte reconcile` (doctrine-deferred).

## Doctrine anchors
- `config_and_secrets.md § Tooling` (the config permission-inversion table, `get` fine for config, `set` positional OK, `status` shows values).
- `cicl.md` line 119 (config declared per service, value in non-tracked `infra/config/<env>.env`).

## Artifact alignment
doctrine (`docex.md § config` — orchestrator) ⇄ `src/docex/**` (sub-agent) ⇄
`tests/**`.
