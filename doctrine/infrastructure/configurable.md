---
stratum: resident
---
# Configurable Values Overview

The name of this document is used in the 12-factor sense to mean "values likely to vary between deploys" - this includes both secrets and config. They all ultimately get injected as env vars.

Secrets are distinct from config because their values must be protected. Secrets can not be loaded directly into LLM context or ever exposed publicly.

## Environment and Foundation

The actual storage locations and handling differs depending on both environment and foundation. There are three different distinct circumstances when it comes to configurable values:

| Circumstance | Infrastructure Side | Foundation | Envs |
| ------------ | ------------------- | ---------- | ---- |
| *development* | development | both | `dev`, `test` |
| *production, fixed* | production | fixed | `stage`, `prod` |
| *production, elastic* | production | elastic | `stage`, `prod` |

**Slots share an env's configurable values.** A [slot](./infrastructure.md#the-slot-axis) is an isolated stack of a fixed env, not a new environment, so all three configurable-value sources are looked up **per env, not per slot**: every slot of `test` reads the same `infra/config/test.env`, `infra/secrets/test.env`, and `infra/tte/test.env`. The slot number scopes physical resource names only; it never fans out the configurable-value namespace.

## Sources

There are three standard sources of configurable values in a doctrine-based project:
1. Transfer-table Engine Environment Variables (TTE vars)
2. Secrets
3. Config

### TTE Vars

TTE vars are mechanical necessities that originate in different roles' engines in the transfer tables. They usually exist to authenticate inter-service communication.

The classic example is the `postgres` engine's `POSTGRES_PASSWORD` variable. This must be set for the `relational_db` backing service when it launches for the first time. Afterwards, the backing service itself remembers it. However, the project must still keep a record of the values so that core services can construct database URIs to query the `relational_db` backing service.

TTE vars are handled almost entirely automatically by `docex`. During [aggregation](#aggregation), any TTE vars which are absent will be automatically generated. Intervention from the developer is only required if the doctrine-recorded values somehow get out of sync with the container-volume-recorded ones. [config_and_secrets.md](./specifics/config_and_secrets.md#recovery--divergence-not-invalidity)

| Circumstance | Storage Location |
| ------------ | ---------------- |
| *development* | `$pr/infra/tte/${env}.env` |
| *production, fixed* | host `/opt/${project}/${env}/tte.env` | 
| *production, elastic* | SSM `/${project}/${env}` | 

### Secrets

Secrets are any per-deploy variables which cannot be published. They tend to be things like API keys or passwords. They must be kept secret and safe. This also means that they cannot enter LLM contexts. Secrets are stored in a `.env` file that LLMs should never read. Special `docex` tooling is provided to interact with this file (details below).

The keys which compose the secrets `.env` file (that is, the schema) are derived from two sources:
1. The `secrets` block in `infra.yml` - see [cicl.md](./cicl.md#service-fields).
2. Certain doctrine-mandated secret values like `TELEMETRY_API_KEY` - see [telemetry.md](./telemetry.md#authentication).

This makes the `.env` file's structure and keys deterministically driven from project infra config.

| Circumstance | Storage Location |
| ------------ | ---------------- |
| *all* | `$pr/infra/secrets/${env}.env` |

`docex` tooling generates these files and keeps them from drifting. The keys, order, and comment cadence are all managed by `docex` machinery. Only the values themselves - the secrets - are added by hand. This can be done either via a direct edit of the relevant `.env` file by the human operator, or by the LLM using the `./bin/docex secrets ...` command.

The `./bin/docex secrets ...` command gives the agent tooling to work with secret *values* without loading them into context. See below for a brief overview. The [docex.md](./docex.md#secrets) overview has deeper info on this command.

| Op | What it does | Who runs it | 
| -- | ------------ | ----------- |
| `docex secrets scaffold <env>` | reconcile key set into `<env>.env`, preserve values | agent freely |
| `docex secrets status <env> [--format json] [--fingerprint]` | **redacted read** — per key: `SET`/`UNSET`, declaring codebase, description; **never the value**. `--fingerprint` adds a non-revealing value fingerprint column | agent freely |
| `docex secrets set <env> <KEY>` | **write-only set** — set one key, read/emit nothing else | agent *invokes*, human *supplies* |
| `docex secrets copy <src_env> <tgt_env> <KEY>` | **value-blind copy** — set `tgt.KEY` = `src.KEY` without exposing the value | agent freely |
| `docex secrets fingerprints [--format json]` | **cross-env fingerprint matrix** — one row per key, one column per env; each cell a salted, non-revealing fingerprint of the value (or unset). Compares propagation/drift across envs | agent freely |

In the case of secrets, a fingerprint is `hex(sha256(SALT || value))[:8]` under a fixed, project-local, **non-secret** salt derived from the project name. It is stable within a project and comparable across envs. This lets two secret values be compared without literally reading them.

### Config

Config is the most free-form of all configurable var sources. The config keys which are *required* for a project's function are defined in `infra.yml`. However, unlike with secrets, the config `.env` files are not managed by the doctrine directly. Validation will fail if the required keys are not present; however, the structure of the config `.env` files is free-form. Values are not secure, so they can be loaded into LLM context at will and edited freely by agents and humans alike.

| Circumstance | Storage Location |
| ------------ | ---------------- |
| *all* | `$pr/infra/config/${env}.env` |

## Validation

At the `docex` compile step, validation is performed to ensure that:
1. All needed keys for the project are present in the various source `.env` files.
2. Source `.env` files don't contain overlapping keys.

If validation fails, compile will also fail.

## Aggregation

Aggregation is performed "automatically" as a step of certain `docex` CI/CD steps - usually just before `compose up` for `fixed` or ECS task start for `elastic`. This step merges the keys from each source into one aggregate (stored in differing places depending on circumstance). Then, each service's container will have the relevant key/value pairs injected as environment variables on startup.

The developer should not need the details of aggregation unless something is broken. In that case, see specifics at [config_and_secrets.md](./specifics/config_and_secrets.md).