# Mod 078 — `config:` block + `classify_source_keys` backbone

Part of the [envmageddon campaign](../../campaigns/003_envmageddon/implementation_plan.md)
(step 2, mod 3 of 11). Adds the third value category — **config** — as a core-
service declaration block, and introduces the campaign's central abstraction:
the pure **source-key classifier** every later mod calls.

## Why

`config_and_secrets.md § The Three Categories`: every env-tier key belongs to
exactly one of **TTE** (engine `kind: minted`), **secret** (core `secrets:` +
backing `kind: secret` + doctrine-injected), or **config** (core `config:`).
Config is the doctrine's escape valve for per-env, non-secret values CICL can't
otherwise express (`cicl.md` line 119).

Two deliverables:

1. **`config:` block** — a core service declares `config:` like `secrets:`; each
   key is auto-injected into the container as an env var of the same name,
   sourced (like a secret) from the aggregate. Declaration is committed in
   `infra.yml`; the *value* floats per-env in the non-tracked
   `infra/config/<env>.env` (materialized by the aggregation mods 080-082).

2. **`classify_source_keys`** — a pure function of `(CICLDocument,
   TransferTables)` returning which category every **source key** belongs to
   (the `POSTGRES_PASSWORD` / `TELEMETRY_API_KEY` / `PROJECT_B_URL` namespace,
   *not* the container-env `DATABASE_PASSWORD` namespace). Pure and cheap, so
   every downstream site calls it directly — disjointness validation (Mod 079),
   the elastic SSM push routing (Mod 082), and the `secrets`/`config` tooling
   (Mods 083-084). Single source of truth for the category model.

## Key design finding — the emitter does NOT change

A `config:` key is wired at compile exactly like a `secrets:` key: the compiler
sets `env_block[key] = "$[key]"` (a self-referential runtime ref). That bare
`$[REF]` then flows through the **existing** emit paths unchanged:

- **fixed**: compose `environment: { KEY: "${KEY}" }`, read from the aggregate
  env-file (Mod 080/081).
- **elastic**: an ECS `secrets[]` entry `valueFrom` the SSM path — and ECS
  `secrets[]` `valueFrom` works for a plain SSM `String` param just as well as a
  `SecureString`. The value is delivered as a normal container env var either
  way.

This **resolves flagged item #1** (`implementation_plan.md`): the doctrine's
"`environment[]` (config)" wording is imprecise — ECS `environment[]` entries
are static inline values and cannot source SSM, whereas `secrets[]` `valueFrom`
can and does not require the param be secret. So config is delivered via the
same `secrets[]`-`valueFrom` mechanism, against an SSM `String` param. The
`String`-vs-`SecureString` distinction is about how the value is *stored/pushed*
to SSM — that lives entirely in **Mod 082** (the push), not in emit. Therefore
this mod touches no emitter and adds nothing to `CompiledEnv`.

## Scope

**In:** `CoreService.config: dict[str, str]` (declaration); `cicl/categories.py`
(`Category`, `SourceKeyCategories`, `classify_source_keys`,
`DOCTRINE_INJECTED_SECRETS`); compile wiring of config keys as self-ref runtime
refs (mirror the `secrets:` loop); tests for the classifier and config-key
compilation on both foundations.

**Out:** disjointness/reserved-key *validation* (Mod 079 — this mod only builds
the classifier it will use); aggregation / value materialization (Mods 080-082);
`config:` tooling (Mod 084); any emitter change.

## Doctrine anchors
- `cicl.md` lines 93-94, 118-121 — the `secrets:`/`config:` fields; the three categories disjoint by key.
- `config_and_secrets.md § The Three Categories`, `§ How Values Reach Application Code` (the container env shape is identical across foundations; only delivery differs).
- `plan.md §3.1` — `config:` declaration block, auto-injected as `env_block[key]="$[key]"`, `String` on elastic.

## Artifact alignment
doctrine (committed) ⇄ `src/docex/**` (this mod) ⇄ `tests/**` (this mod). No
`tables/` change. Core-doc narrative batched to Mod 086.
