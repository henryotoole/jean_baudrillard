# Mod 083 — `docex secrets` command group

Part of the [envmageddon advance](../../advances/003_envmageddon/implementation_plan.md)
(step 2, mod 8 of 11). The value-blind secrets tooling — the advance deliverable
a downstream project is waiting on. `scaffold` / `status` / `set` / `copy` let an
LLM agent *drive* secret handling while being structurally unable to *see* a
secret value.

## Why

`config_and_secrets.md § Tooling` + `docex.md § secrets`: deterministic secret
handling is executor-stratum, so it is `docex` subcommands, not loose scripts.
Two properties make it secure rather than theatrical:

1. **`set`'s value channel is a no-echo tty prompt or `--from-file`, never a
   positional argument** — the agent invokes; the human supplies; the value
   never transits the agent's context.
2. **There is no value-printing command** (`status` is redacted `SET`/`UNSET`
   only; there is no `get` for secrets). Values leave the file only at
   materialization (aggregation, Mods 080-082).

`copy` is the purest form: it moves a value env→env with **no value channel at
all**, so the agent can fully drive it blind.

## The four ops (`config_and_secrets.md § Tooling`)

| Op | Behavior | Value in agent context? |
| -- | -------- | ----------------------- |
| `scaffold <env>` | reconcile `infra/secrets/<env>.env` against the deterministic required key set — add missing (empty), remove stale, **preserve existing values**; idempotent | no |
| `status <env> [--format json]` | redacted read: per key `SET`/`UNSET`, source, description — **never the value**; binary only (no length/hash) | no |
| `set <env> <KEY>` | write one key; value via **no-echo tty prompt** or `--from-file`, never positional | **no** |
| `copy <src_env> <tgt_env> <KEY>` | value-blind env→env copy; secrets/config only (**never TTE**); same-side blessed, cross-side warns, unset source errors, overwrites | **no** |

## Design: category-parametrized engine (reused by Mod 084)

`config_and_secrets.md § Tooling`: config gets "the same ops with permissions
inverted." So the file engine is parametrized by a `CategoryPolicy`
(subdir, whether `status` shows values, whether `set` allows a positional value,
whether `get` exists). This mod builds the engine + the **secret** policy + wires
`docex secrets`. Mod 084 adds the **config** policy, `get`, and `docex config` —
no engine rewrite.

## Single source of truth: `secret_manifest`

`scaffold`/`status` need each required secret's key + description + declaring
source. Add `secret_manifest(doc, tables) -> list[SecretEntry(key, desc, source)]`
to `cicl/categories.py` — derived from core `secrets:` (source = the service) +
backing `kind: secret` engine env vars (source = the backing service) +
doctrine-injected (`TELEMETRY_API_KEY`, source = "doctrine"). `emit_example_env`
is refactored to render its key set **from this manifest**, so the manifest and
`example.env` can't drift — and this folds in the deferred `DOCTRINE_INJECTED_SECRETS`
dedup (Mod 078 flag #1). `example.env`'s grouped-by-source format is preserved.

## The shim tty change

Interactive `set` prompts with no echo (`getpass`), which needs a tty inside the
docex container. The shim (`bin/docex`) currently runs `docker run` without
`-it`. Add `-t -i` **only when the caller has an interactive terminal**
(`[[ -t 0 && -t 1 ]]`); non-interactive/piped invocations are unchanged (and
must use `--from-file`). Additive + backward-compatible per the version-
independent-shim rule (an older image tolerates an extra `-it`).

## Scope

**In:** `secretsmgmt/` engine (`CategoryPolicy` + `scaffold`/`status`/`set`/`copy`),
secret policy; `secret_manifest` + `emit_example_env` refactor; `envfile.set_env_key`
(single-line preserve); `docex secrets` nested CLI (`__main__.py`); the shim tty
change; tests.

**Out:** `docex config` + `get` + config policy (Mod 084 — but build the engine so
it slots in). TTE tooling (`tte reconcile`) is doctrine-deferred.

## Doctrine anchors
- `config_and_secrets.md § Tooling` (the ops table, the two cruxes, `copy` rules, the secret/config permission asymmetry).
- `docex.md § secrets` (the command surface, `set`'s tty/`--from-file`-only channel, no `get`).
- `config_and_secrets.md § Direct generation, not copy-and-fill` (`scaffold` reconciles, preserves values).

## Artifact alignment
doctrine (committed) ⇄ `src/docex/**` + `bin/docex` (this mod) ⇄ `tests/**`.
`docex config` doc/`### config` section is Mod 084; `docex.md § secrets` already
documents this surface.
