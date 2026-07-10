# Mod 077 — Compiler inlines `kind: fixed` `$[VAR]` refs

Part of the [envmageddon campaign](../../campaigns/003_envmageddon/implementation_plan.md)
(step 2, mod 2 of 11). Makes the compiler *resolve* the `kind` schema Mod 076
introduced: a `$[VAR]` naming a `kind: fixed` engine env var is replaced by its
literal `value:` at compile time; `minted` and `secret` vars stay as `$[VAR]`
runtime pass-through refs (unchanged behavior).

## Why

`transfer_tables.md § Anatomy` (and its postgres walking example): *"Every
`$[POSTGRES_USER]` reference in `defaults`, the `healthcheck`, and
`provides.user` is left unchanged — because `POSTGRES_USER` is `kind: fixed`, the
compiler inlines `appuser` at each site, so the username leaves the store
entirely and only `POSTGRES_PASSWORD` is minted."*

Mod 076 changed the table but not the compiler, so today `$[POSTGRES_USER]` still
emits verbatim (compose `${POSTGRES_USER}` / an elastic SSM data source). This
mod makes the compiler honor `kind: fixed`.

## The rule

> A `$[VAR]` token is inlined to a literal **iff the engine that *declares* that
> env var marks it `kind: fixed`** — using that engine's `value:`. Otherwise the
> token is left untouched (minted/secret → runtime ref).

`$[VAR]` tokens originate from exactly two places, and in both the "declaring
engine" is well-defined:

| Site | Where `$[VAR]` lives | Declaring engine |
| ---- | -------------------- | ---------------- |
| Backing body | `defaults` (env, healthcheck), elastic `username`/`password` | the backing service's own engine (`engines[consumer]`) |
| `provides:` template | `provides.user`, `provides.password` | the provider engine (the `engine` in `_resolve_part`) |

A core service never authors `$[VAR]` for a fixed var directly — it references
`${backing_services.db.user}`, which resolves through the provider's `provides`
template (site 2). So inlining at these two sites is complete.

## Payoff (no emitter change needed)

Because a `fixed` var is inlined to a literal before emit, the existing elastic
emitter machinery — `_translate_ssm_refs` (backing body `$[VAR]` → `data
"aws_ssm_parameter"`) and `_partition_env` (core bare-`$[REF]` → ECS
`secrets[]`) — simply no longer *sees* `POSTGRES_USER` (it's already `appuser`),
so it fires only for `POSTGRES_PASSWORD`. This is the doctrine's stated payoff #3
(`plan.md §1.1`). `emit/hcl.py` needs no change.

## Scope

**In:** `$[VAR]` fixed-inlining at the two resolution sites (in
`cicl/magic_refs.py`), trimming inlined vars from `RenderedValue.runtime_refs`;
tests proving fixed→literal on both foundations and both sites.

**Out:** everything else. `minted`/`secret` behavior is byte-identical to today.

## Doctrine anchors
- `transfer_tables.md § Anatomy of a Role Definition` (the inline rule + postgres example).
- `transfer_tables.md § Substitution Grammar` — line 34: *"a `fixed` var is instead resolved to its literal `value:` at compile time and inlined, so it never reaches the runtime layer."*
- `config_and_secrets.md § How Values Reach Application Code` — the `kind: fixed` var appears as a plain literal, never in any store.

## Artifact alignment
doctrine (committed) ⇄ `src/docex/**` (this mod) ⇄ `tests/**` (this mod). No
`tables/` change (Mod 076 did it). Core-doc narrative alignment batched to Mod 086.
