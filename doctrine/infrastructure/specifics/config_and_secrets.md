---
stratum: conditional
---

# Config & Secret Handling

This file describes how every environment-tier value — secrets, generated engine
credentials, and non-secret config — flows from its source on the operator's
machine into running services across both foundations. The source is split by
**category**; a single aggregation step re-merges the categories into the
container-facing env the services already consume. The materialization mechanism
is foundation-aware; the category model and file form are uniform.

This is documentation for the implementer of `docex` and the curious developer;
it is not meant to be force-loaded as general doctrine context. The shorter
resident-stratum overview is in [configurable.md](../configurable.md).

## The Three Categories

Every env-tier key/value pair belongs to exactly one category, defined by its
**provenance**:

| Category | Provenance | Handling | Home |
| -------- | ---------- | -------- | ---- |
| **TTE** (Transfer-Table-Engine) | an engine `env:` var declared `kind: minted` (e.g. `POSTGRES_PASSWORD`) | generated once by `docex`, never hand-edited, never git-tracked | the TTE store (see [§ TTE Vars](#tte-vars)) |
| **Secret** | a codebase's `secrets:` block, a backing engine's `kind: secret` env var, or a doctrine-injected key (`TELEMETRY_API_KEY`) | operator-supplied, never in LLM context, never git-tracked | `infra/secrets/<env>.env` |
| **Config** | a codebase's `config:` block | operator-supplied, non-secret, freely LLM-readable, non-git-tracked | `infra/config/<env>.env` |

Because provenance is single-valued, the categories are **disjoint by key**. An
overlap is a compile error, and doctrine-injected keys are reserved (see
[cicl.md § Validation Rules](../cicl.md#validation-rules), rules 16 and 20). This
disjointness is what lets aggregation be a plain union with no precedence.

The old model mixed all three in one `<env>.env` file, which made config
un-editable by an LLM, made read-only engine artifacts look editable, and made
the file impossible to auto-reconcile because it merged sources. Splitting the
source fixes all three while leaving the container-facing surface unchanged.

## Layout

Subdir-per-category — the same *scheme* everywhere, only the *root* differs
(local tree / remote host / SSM prefix are inherently different roots):

```
infra/
  secrets/            # gitignored — operator-supplied secret values
    <env>.env
  tte/                # gitignored — generated engine credentials
    <env>.env
  config/             # gitignored — non-secret per-env config values
    <env>.env
```

On the fixed prod host the parallel structure lives under
`/opt/<project>/<env>/`; on elastic it is the SSM path prefix `/<project>/<env>/`.

`.gitignore` (added by project inception) ignores the value files in all three
directories; nothing under them is committed. The key set a project requires is
not committed as a file either — it is derived on demand from its committed
sources (the `secrets:` / `config:` declarations in `infra.yml`, the transfer
tables, and doctrine-injected keys).

### Direct generation, not copy-and-fill

The **secret manifest** — the set of secrets a project requires — is fully
deterministic from `infra.yml` + doctrine (codebase `secrets:` blocks + backing
engines' `kind: secret` env vars + doctrine-injected keys). It is never
committed as a file; it is computed on demand from those committed sources.

Rather than copy a manifest to `<env>.env` and fill it by hand, the operator
runs **`docex secrets scaffold <env>`**, which *reconciles* the real
`<env>.env` against the manifest: it adds every required key (empty),
flags/removes keys no longer required, and **preserves all existing values**. It
is idempotent — reconciliation, never regeneration (regenerating would wipe
values). `docex secrets status <env>` lists the manifest with per-key
`SET`/`UNSET`. Config is symmetric: its key set derives from `infra.yml`
`config:` blocks and is reconciled by `docex config scaffold <env>`; neither
category keeps a committed manifest file.

## Standard Form

> **A secret or TTE value is a flat, single-line scalar. Anything structured,
> multiline, or messy is config (or base64'd), never a secret.**

Strict flatness is what makes the [tooling](#tooling)'s safety *guaranteeable*
(redaction is a total function; a single-key write is a safe line-replace) rather
than best-effort.

All three sources — `secrets/<env>.env`, `tte/<env>.env`, and `config/<env>.env`
— use the same flat form:

- One `KEY=value` per line; split on the **first** `=` only (values may contain `=`).
- `KEY`: `[A-Z][A-Z0-9_]*`.
- `value`: the **literal bytes** after the first `=` to end-of-line — no quote
  processing, no escapes, no interpolation, no trailing-whitespace trimming.
  ("Raw literal" is the one interpretation portable across compose `env_file`,
  `--env-file`, and SSM; env-file quoting has drifted across docker/compose
  versions.)
- `#`-lines are full-line comments only (a `#` inside a value is literal).
- **Multiline / binary secrets** (PEM keys, service-account JSON) → **base64 to
  a single line**; the app decodes at startup. This keeps the strict form intact
  instead of letting one PEM break compose parsing, SSM, and redaction at once.
  (A base64 PEM fits SSM's 4 KB SecureString limit.)

**No source is YAML.** All three categories use flat `KEY=value` `<env>.env`
files. YAML on an opaque value is dangerous (a password `yes` → boolean, `0123`
→ number, colons mis-typed), and a uniform flat form keeps parsing, redaction,
and tooling identical across categories — the simplicity is the point.

## TTE Vars

A TTE var is an engine `env:` var declared `kind: minted` (see
[transfer_tables.md § Anatomy](./transfer_tables.md#anatomy-of-a-role-definition)).
It is generated by `docex`, not supplied by anyone.

The canonical example is postgres. Its `POSTGRES_USER` is `kind: fixed` (a
doctrine-fixed literal, `appuser`, inlined at compile and stored nowhere), so the
**only** minted value is `POSTGRES_PASSWORD`, generated per the `password`
[generation policy](./transfer_tables.md#generation-policies) (url-safe, 32 chars,
CSPRNG).

### Generation runs inside aggregation, never in `compile`

Generation is non-deterministic and stateful, so it never runs at `compile`
(which is offline-pure). It is the first sub-step of [aggregation](#aggregation):
`ensure_tte → merge → materialize`, on both the `up` path (dev/test) and the
`release` path (stage/prod).

### The authoritative-store rule (generate-if-absent)

`ensure_tte` generates a minted value only if it is **absent** — and the
existence check must read the *authoritative* store:

> **Authoritative store = the store the target env's containers actually read at
> runtime.**

- **dev/test:** local `infra/tte/<env>.env` (compose reads it directly).
- **elastic stage/prod:** **SSM** (`/<project>/<env>/`) — ECS reads it.
- **fixed stage/prod:** the host `/opt/<project>/<env>/tte.env` — read over the
  SSH `release` already uses.

Checking anything else (e.g. blindly the local file for a prod env) risks a
lost/absent local copy triggering a fresh mint that clobbers the live store while
the database still holds the old credential — a lockout. Reading the
runtime-read store reuses the existing value and never clobbers.

### Recovery — divergence, not invalidity

Losing or diverging a TTE store is **inconvenient, not destructive**: the value
can be re-applied to the live instance out-of-band. TTE values are write-once
against a live instance; if the authoritative store ever diverges from that
instance (store lost then re-minted, an out-of-band credential change, a restored
snapshot), the stored credential must be **re-applied to the instance** — a
control-plane password reset on elastic, an in-place credential reset on fixed.
`docex` does not yet automate this; **`tte reconcile` is the planned command and
will subsume TTE rotation** (rotation is the same operation: push a value onto
the live instance). Until then, divergence is an operational incident. This
mirrors the doctrine's existing deferral of secret [rotation](#caveats).

## Required-Secret Guard

A stage/prod `docex release` **refuses to proceed if any required secret is
unset**, and it checks this *before any side effect* — before aggregation, the
SSM push, or the ansible/tofu apply. A **required secret** is any key in the
[secret manifest](#direct-generation-not-copy-and-fill) (codebase `secrets:`
blocks + backing engines' `kind: secret` vars + doctrine-injected secrets); **unset**
means absent from `infra/secrets/<env>.env` or present with an empty value. The
release aborts with a message naming every unset key and its
`docex secrets set <env> <KEY>` remediation.

The guard is scoped deliberately:

- **Secrets only.** TTE values are docex-minted (put-if-absent during
  [aggregation](#aggregation)), so they are never operator-unset; config is
  non-secret and may legitimately be empty. Neither category gates a release.
- **stage/prod only.** dev/test bring-up (`docex up`) tolerates incomplete
  secrets so local iteration is never blocked. [Rollback](../cicd.md#rollback)
  is emergency and code-only, and is likewise not gated.

Without the guard an unset required secret is caught nowhere: aggregation is a
plain union of whatever sits on disk, so the empty value flows into the
container and surfaces only as a runtime failure — or, worse, a silently-broken
prod. The guard converts that late, opaque failure into an early, explicit one.

## Aggregation

A single **internal** step (not a top-level verb — a shared `aggregate(env, ctx)`
helper, foundation-dispatched like migration) merges the three categories into
the container-facing surface, just before the containers first read it: before
`docker compose up` (dev/test), before the host compose-up (fixed stage/prod), or
as the SSM push (elastic stage/prod).

Because the categories are disjoint by key, the merge is a **plain union** — no
precedence, no layering. The aggregate is a gitignored, derived, ephemeral,
secret-bearing artifact = `(authoritative TTE store) ∪ secrets ∪ config`,
regenerated every run and distinct from the persistent TTE store:

| Circumstance | Persistent TTE store | Secrets / Config source | Aggregate (derived) |
| ------------ | -------------------- | ----------------------- | ------------------- |
| dev/test | `infra/tte/<env>.env` | `infra/{secrets,config}/…` | `.docex/agg/<env>.env` |
| fixed stage/prod | host `/opt/<project>/<env>/tte.env` | control-node `infra/{secrets,config}/…` | host `/opt/<project>/<env>/.env` |
| elastic stage/prod | SSM `/<project>/<env>/…` | control-node `infra/{secrets,config}/…` | SSM `/<project>/<env>/…` (same prefix) |

On fixed, `docex` hands the aggregate to compose via `--env-file`. On elastic
there is no file: aggregation *is* the push of all three categories to the flat
SSM prefix, with **TTE keys put-if-absent** (preserving the write-once authority)
and **secrets/config overwritten** (`Overwrite=True`, clobber-downstream). A
name collision across categories cannot occur — it is a compile error.

## Materialization at Release

The category sources are canonical; the deployment target is overwritten *from*
them on every release, with the one TTE exception above.

- **Fixed (Ansible):** the playbook renders the aggregate onto the host as
  `/opt/<project>/<env>/.env`; Docker Compose reads it when starting containers.
- **Elastic (OpenTofu):** before `tofu apply`, `docex release` pushes each
  aggregate entry to SSM at `/<project>/<env>/KEY` — secrets and TTE as
  `SecureString` (default `aws/ssm` KMS key), config as plain `String`. The
  emitted HCL provisions ECS task definitions whose `secrets[]` blocks
  `valueFrom` those SSM paths — config rides `secrets[]` too, not
  `environment[]`, because an ECS `environment[]` entry is a static inline
  `name`/`value` pair and cannot source from SSM. `secrets[]` `valueFrom`
  resolves a plain `String` (config) exactly as it does a `SecureString`
  (secret/TTE).

Manual edits to the host `.env` (fixed) or SSM parameters (elastic) are
overwritten on the next deploy — by design, to preserve the deterministic
doctrine.

## How Values Reach Application Code

A core service's container environment is *identical in shape* across both
foundations. Each declared secret/config key, and each backing part a service
binds, is delivered under the consumer's own key:

| Foundation | Mechanism | Effective container env |
| ---------- | --------- | ----------------------- |
| Fixed | Compose `environment:` line `DATABASE_PASSWORD: ${POSTGRES_PASSWORD}` reading from the host `.env` | `DATABASE_PASSWORD=<value>` |
| Elastic | ECS `secrets[]` entry whose `valueFrom` sources `/<project>/<env>/POSTGRES_PASSWORD` (SSM `SecureString` for secret/TTE, plain `String` for config — the ECS delivery verb is `secrets[]` either way) | `DATABASE_PASSWORD=<value>` |

The container sees the same key and value on both foundations; only the delivery
mechanism differs. The compiler binds these end-to-end: a core service's
`env: DATABASE_PASSWORD: ${backing_services.appdb.password}` resolves (per the
engine's `provides:` block) to the runtime ref `$[POSTGRES_PASSWORD]`, which the
compiler emits as the compose line or ECS entry above. A `kind: fixed` var (e.g.
`POSTGRES_USER` → `appuser`) is instead inlined at compile and appears as a plain
literal, never in any store. See
[transfer_tables.md § env](./transfer_tables.md#anatomy-of-a-role-definition).

## Parts-Only Rule

Engines never expose a pre-composed string for a secret-containing value (e.g.,
no `appdb.url` part that includes the password inline). The application
composes its own connection string from the discrete parts (`host`, `port`,
`db`, `user`, `password`) at startup.

This rule keeps the secret-flow surface clean across both foundations. ECS
`secrets[]` can only deliver each secret as a whole standalone env var; it cannot
embed one inside a larger value without materializing that value as plaintext in
the task definition and Tofu state. Parts-only is the single model that keeps
`provides:` identical across foundations.

As a consequence, secrets like `$[POSTGRES_PASSWORD]` never appear as inline
values in compiled artifacts — they flow through compose's runtime substitution
(fixed) or the ECS `secrets[]` block (elastic), staying out of any persisted task
definition or compose snapshot. The compiler enforces this at compile time: a
magic ref that would embed a secret inside a larger value fails compile with a
clear error. The guard scopes to *secrets and minted TTE values only*: a
`kind: fixed` engine var is inlined to its plain literal before the guard runs
(Mod 077), so composing a non-secret fixed literal (e.g. `POSTGRES_USER` →
`appuser`) into a larger value is permitted — it is the password, not the
username, that may never be embedded. It is also what makes a minted password's **url-safe alphabet**
load-bearing — the app builds `scheme://user:pass@host/db` itself, so a password
with URI-reserved characters would break that build (see
[transfer_tables.md § Generation Policies](./transfer_tables.md#generation-policies)).

## Doctrine-Injected Secrets

A small set of secrets is added by the doctrine itself rather than by project
services. These are part of the secret manifest for the envs that need them (so
`docex secrets scaffold`/`status` surface them), are reserved (a project may not
redeclare them), and the operator fills them like any other secret:

| Secret | Required envs | Source | Consumer |
| ------ | ------------- | ------ | -------- |
| `TELEMETRY_API_KEY` | stage, prod | The project's observability backend (HyperDX or equivalent) | The OTel sidecar paired with each core service. See [telemetry_infra.md](./telemetry_infra.md). |

Any secret introduced by `docex`'s own machinery (not by a project-declared
service) is documented as a doctrine-injected entry, with its purpose in the
section comment.

## Tooling

Deterministic action → executor stratum → `docex` subcommands (not loose
scripts). The tooling lets an LLM agent *drive* secret handling without secret
**values** ever entering its context.

| Op | What it does | Values in LLM context? |
| -- | ------------ | ---------------------- |
| `docex secrets scaffold <env>` | reconcile the key set into `<env>.env`, preserving values | no |
| `docex secrets status <env> [--format json] [--fingerprint]` | **redacted read** — per key: `SET`/`UNSET`, source, description; **never the value**. `--fingerprint` adds a non-revealing value fingerprint column | no |
| `docex secrets set <env> <KEY>` | **write-only set** of one key | **no** |
| `docex secrets copy <src_env> <tgt_env> <KEY>` | **value-blind copy** of one key between envs | **no** |
| `docex secrets fingerprints [--format json]` | **value-blind cross-env matrix** — one row per key, one column per env; each cell a salted, non-revealing fingerprint of the value (or unset). Compares propagation/drift across envs | no |

Two properties make this secure rather than theatrical:

1. **`set`'s value channel is the tty (no-echo prompt) or `--from-file`, never a
   positional argument.** A positional value would force the agent to hold the
   secret in context. Instead the agent drives ("run this to set
   `STRIPE_API_KEY`") while being structurally unable to see the value; the human
   types it into the running command. `copy` needs no value channel at all — it
   moves a value env→env without ever surfacing it.
2. **There is intentionally no `secrets get` / value-printing command.** Values
   leave the file only at materialization, never to stdout.

`status` redaction is binary `SET`/`UNSET` by default — no length, and no hash
unless one is explicitly requested. `--fingerprint` (and the `fingerprints`
matrix) opts into a salted, project-local `sha256[:8]` fingerprint whose purpose
is a cross-env **equality/drift** check, not a confidentiality guarantee: it
reveals no value directly, but a low-entropy or placeholder secret is inherently
guessable from any hash of it, so the fingerprint is safe to display precisely
because a real high-entropy secret cannot be recovered from it. `copy` applies to secrets and config **only, never TTE** (TTE
is minted per env and write-once against a live instance); a **same-side** copy
(`dev`↔`test`, `stage`↔`prod`) is the blessed case, a **cross-side** copy warns
(seeding production with development-side values), an unset source errors, and it
overwrites the target by default.

**Config needs no such tooling.** The entire reason the `secrets` family exists
is to touch values *without exposing them*; config values are non-secret, so
agents and humans simply edit `infra/config/<env>.env` directly with ordinary
file tools. That difference — value-hiding tooling for secrets, direct editing
for config — is the category boundary made operational.

## Caveats

- **No externally-rotated secrets.** All secrets are project-controlled and
  clobbered on each release; AWS-managed RDS rotation, third-party-issued tokens,
  or anything that updates outside the source files would be clobbered. A future
  extension may mark certain keys externally-managed.
- **No secret / TTE rotation.** Changing a value and running `release` swaps it,
  but coordinated rotation across multiple secrets, with a window where both old
  and new are accepted, is not modeled. TTE reconcile/rotation (`tte reconcile`)
  is [deferred](#recovery--divergence-not-invalidity).
- **Trust model.** Real production secret values sit on every operator's laptop.
  The doctrine assumes the operator's machine is trusted.
- **Synchronization across operators.** Operators sharing a project must keep
  their `secrets/<env>.env` and `config/<env>.env` files in sync out-of-band. The TTE store for
  stage/prod is the shared runtime store (SSM / host), so it does not suffer this
  — but dev/test TTE stores are per-machine (each has its own volume).
