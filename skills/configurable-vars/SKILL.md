---
name: configurable-vars
description: Doctrine for working with a project's configurable values — the secrets, config, and TTE env files and the `docex secrets` / `docex config` tooling that populates them. Use this whenever you are setting, scaffolding, or checking configurable vars — filling in a secret or config value, creating an environment's `.env` files for the first time, resolving a "required secret unset" release failure, or getting an environment's values populated — even if you never say "configurable", "config", or "secret".
metadata:
  type: thread
---

# configurable-vars

Configurable values — secrets, config, and TTE vars — are the per-deploy key/value pairs injected into services as environment variables. The resident [`configurable.md`](../../doctrine/infrastructure/configurable.md) is already in context and is the source map: it names the three categories and the file location for each. This skill routes to the *tooling* that populates those files and to the deep reference for when that tooling misbehaves. The job is done when every required configurable var for an environment has a value.

## General Information

The command surface for working with the `<env>.env` files. **Read this now.**

[`docex.md`](../../doctrine/infrastructure/docex.md#secrets) — the [`secrets`](../../doctrine/infrastructure/docex.md#secrets) and [`config`](../../doctrine/infrastructure/docex.md#config) command families: `scaffold` to create/reconcile a file's key set, `status` to see which keys are `SET`/`UNSET`, `set` to fill one key, `copy` to move a value between environments. Start here — if an environment's `<env>.env` files do not exist yet, the first move is `docex secrets scaffold <env>` and `docex config scaffold <env>`.

## Specific Information

The full mechanism behind the commands. **Read on demand — only if the normal loop misbehaves.**

[`config_and_secrets.md`](../../doctrine/infrastructure/specifics/config_and_secrets.md) — the three-category model, standard file form, aggregation, materialization, the required-secret guard, and TTE authoritative-store recovery. Reach for it when values are not reaching containers, a release rejects a secret you believe is set, or a TTE store has diverged (lockout) — not for the routine scaffold→set→status loop.

## Thread

- **The loop.** If the `<env>.env` files don't exist, `scaffold` creates them from the deterministic key set (also re-run `scaffold` whenever the declared schema changes — it preserves existing values). Then `status <env>` to find `UNSET` keys, `set` each one, and `status` again to confirm none remain. Use `copy <src_env> <tgt_env> <KEY>` to seed one env's value from another (same-side — `dev`↔`test`, `stage`↔`prod` — is the blessed case).
- **The secret/config asymmetry.** Secret *values* must never enter your context: you *invoke* `secrets set` and the human supplies the value at a no-echo prompt. Config is non-secret, so `config set` takes the value positionally and `config get`/`status` print it — you may read and write config files with ordinary tools. That asymmetry *is* the category boundary, made operational.
- **Where the schema comes from.** The *keys* a project requires are declared in the `secrets:` / `config:` blocks of `infra.yml` (plus doctrine-injected keys like `TELEMETRY_API_KEY`). Authoring those declarations is `infra-compile`, not this skill — this skill fills in the *values* those declarations demand. TTE vars need no hand-population; `docex` mints them during aggregation.
- **Where "unset" bites.** `docex compile` fails if a required key is missing from any source file, and a stage/prod `docex release` refuses before any side effect if a required *secret* is unset. Both surface while running the pipeline (`cicd-pipeline`), but the remediation — `scaffold` then `set` — lives here.
