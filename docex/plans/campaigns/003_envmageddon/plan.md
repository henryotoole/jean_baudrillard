# Plan for "Envmageddon"

A plan to break out our current env / secret handling into a more robust and
well-considered system. The goal is to add as little complexity as possible
while making the flows more sensible and usable.

> **Status.** **Implemented — ready to cut (1.5.0).** Design settled (all
> sections). Step-2 implementation complete: mods 076-086 (see
> [`implementation_plan.md`](./implementation_plan.md)) landed the `kind` schema,
> generation policies, `config:` block, the source-key classifier, cross-category
> validation, aggregation across all three circumstances, the `docex secrets` /
> `docex config` tooling, the smoke-project layout migration, and doc alignment +
> the `upgrade_1.5.0.md` guide. Full unit suite green. **Remaining (operator, at
> cut):** the real-infra smoke walk (both foundations) + the `RELEASING.md` cut
> (version-artifact bump, `v1.5.0` tag, image build). Legacy-username hatch
> stayed deferred.

## Current State

Currently, three categories of key/value pair wind up in the `<env>.env` files:

1. **Transfer-table-driven engine env's** — env-vars certain transfer-table
   roles require to function, needed at first container launch to set up the
   container's credentials. `POSTGRES_USER` / `POSTGRES_PASSWORD` (from
   `relational_db.yml`'s postgres `env:` block) are the example.
2. **Genuine secrets** — actual secrets (API keys). They must never be read
   into LLM context or git-tracked. They originate from `infra.yml`'s
   per-core-service `secrets:` block or from doctrine-driven needs (currently
   just `TELEMETRY_API_KEY`).
3. **Config** — deployment-specific, non-secret information. LLM-readable,
   no special handling. Example: the API URL for a 3rd-party service.
   Inter-core-service config (e.g. postgres port) is already handled by docex
   machinery.

The single `<env>.env` file holds all three, which causes problems:

1. Genuine config can't easily be edited or read by the LLM — a sticking point
   requiring manual human intervention.
2. Transfer-table engine env's *look* editable but are really read-only
   artifacts. Confusing.
3. Drift is possible: because the file merges different sources, it can't be
   auto-regenerated, so a secret key removed from the codebase must be removed
   from the file by hand.

## Proposed New System

Split all three categories at the **source**, then re-merge them at deploy time
via an aggregation step. The container-facing injection flow is unchanged; only
the source is split.

### Category taxonomy

The three categories map onto sources that already exist and are already
separable in `emit_example_env`:

| Category | Origin today | New home |
| -------- | ------------ | -------- |
| **TTE vars** (Transfer-Table-Engine) | backing-service engine `env:` blocks | minted + stored in a TTE store; see below |
| **Secrets** | core-service `secrets:` blocks + doctrine-injected (`TELEMETRY_API_KEY`) | `infra/secrets/<env>.env` (operator-supplied) |
| **Config** | *nothing clean today* | `infra/config/<env>.env` (declared, per-env, LLM-readable) |

---

## 1. TTE Vars

"TTE var" = Transfer-Table-Engine var. These are a distinct object class: they
don't need hand-editing by human or LLM. They can be generated in adherence to
naming/charset rules and recorded for use by other core services.

### 1.1 Username becomes a fixed literal — the surface collapses to one minted value

`$[POSTGRES_USER]` currently appears in **four** sites in the postgres engine
block (fixed `environment`, the `healthcheck` `pg_isready -U`, elastic
`username`, and `provides.user`). Rather than hardcode a literal into each (drift
risk), we change the *kind* of the `env:` declaration and leave every `$[…]`
reference untouched.

The engine `env:` block gains a **`kind`** per variable that tells the compiler
how to resolve that variable's `$[…]` references:

```yaml
env:
  POSTGRES_USER:
    kind: fixed          # doctrine-fixed literal, not a secret, not stored
    value: appuser
    desc: "Postgres role name (doctrine-fixed)."
  POSTGRES_PASSWORD:
    kind: minted         # generated once per env, stored in the TTE store
    policy: password
    desc: "Postgres role password (generated)."
```

| kind | Compiler resolution of `$[VAR]` | Lands in |
| ---- | ------------------------------- | -------- |
| `fixed` | inline the literal `value` at compile time | nowhere (baked into compose/HCL) |
| `minted` | emit a runtime ref (compose `${VAR}` / ECS `secrets[]` / SSM data-source) **and** register the var for TTE generation | TTE store |
| `secret` | emit a runtime ref, include the key in `<env>.env`/`example.env` | secrets file / SSM |

Payoffs:

1. **Zero duplication, zero drift** — the literal `appuser` has one home; the
   four `$[POSTGRES_USER]` sites are unchanged and now resolve to a literal.
2. **The three kinds *are* the three campaign categories, at the engine level**
   (`minted` = TTE, `secret` = secret, `fixed` = config-ish/constant).
3. It drives the **elastic HCL emitter**: today it detects `$[…]` tokens and
   makes `data "aws_ssm_parameter"` blocks for *all* of them
   (`relational_db.yml` lines 8–14). Under the kind schema it **inlines**
   `fixed`, and SSM-sources `minted` / `secret`.

The username constant must clear RDS master-username rules (starts with a
letter, alphanumeric/underscore, ≤ 63, non-reserved) and dodge the engine's own
reserved words — `appuser` works; `postgres` / `admin` / `user` / `root` do
not. Same value on both foundations (each DB instance is its own isolation
boundary, so no cross-env/cross-project collision). Derivation-per-project was
considered and **rejected** — it buys nothing here and a vetted constant is
simpler.

Net: the only value docex mints and stores is **`POSTGRES_PASSWORD`**.

### 1.2 Password minting — `generation_policies`, url-safe alphabet

Mint rules live in a **new sibling section** `generation_policies:` (NOT inside
`naming_policies:`). Naming policies are consumed by `apply_policy(name,
policy)` — a *formatter* (separator/case/max_len/overflow) reshaping an existing
identifier. A mint rule is consumed by a *generator* — it needs `length` and
`alphabet`, ignores the naming fields, and mixing the two would pollute the
loader's `_ALLOWED_*` allowlists. Same reusable-data pattern, different section:

```yaml
generation_policies:
  password:
    length: 32
    alphabet: url_safe
```

One general `password` policy covers every foreseeable TTE password across
engines; an engine references it via `policy: password`.

**`alphabet: url_safe` is non-negotiable.** `config_and_secrets.md § Parts-Only` has the
*application* compose its own connection string from parts at startup. If a
minted password contains `@ : / # ? % & +`, a naive `postgresql://user:pass@host/db`
build breaks unless the app percent-encodes (most don't). Independently **RDS
forbids `/ @ "` and spaces** in the master password. The safe intersection is a
URL-safe alphanumeric set (`[A-Za-z0-9]`, optionally `-_`); 32 chars of that is
~190 bits — massive overkill for this formality-tier credential, and it dodges
every connection-string parser and the RDS constraint at once. RNG can be
modest, but use the stdlib CSPRNG (`secrets` module) since it is free.

### 1.3 Generation runs inside aggregation, never in `compile`

Generation is non-deterministic and stateful, so it must **not** live in
`compile` (which `compiler.md` promises is offline-pure). It folds in as the
**first sub-step of aggregation**: `ensure_tte() → merge → materialize`. This
gives one code path spanning all three circumstances instead of scattering
generation across `up` and `release`. It dispatches dev/test (in the `up` path)
vs stage/prod (in the `release` path) the same way the migrate step already
does.

### 1.4 The authoritative-store rule (generate-**if-absent**)

> **Authoritative store = the store the target env's containers actually read at
> runtime.**

- **dev/test:** local `infra/tte/<env>.env` (compose reads it directly).
- **elastic stage/prod:** **SSM** (ECS reads it) — the existence check queries SSM.
- **fixed stage/prod:** the **host** `/opt/<project>/<env>/tte.env` (host compose
  reads it) — read over the SSH `release` already uses.

Why not "just check the local file": a fresh clone / new operator / lost
gitignored local file → local absent → a naive scheme would **mint a new
password → clobber SSM/host → but the live DB still has the old password →
lockout**. Checking the *runtime-read* store finds the existing value and
reuses it, so a lost local copy never triggers a spurious re-mint. (This is
`config_and_secrets.md`'s multi-operator hazard, sharpened into a lockout.)

### 1.5 Recovery — defer-with-caveat (no per-engine prose)

Losing the store is **inconvenient, not destructive**: the value is recoverable
out-of-band on both foundations (elastic: `aws rds modify-db-instance
--master-user-password`; fixed: `docker exec` + local-socket `ALTER ROLE
appuser WITH PASSWORD …`). But a *per-engine* recovery runbook in prose is
exactly what the transfer tables / executor stratum exist to obviate, so we do
**not** write one. Instead:

- Document a single **foundation-general caveat** (a clean home: `config_and_secrets.md`
  caveats, beside rotation, which the doctrine already defers). Shape: "TTE
  values are write-once against a live instance; if the authoritative store
  diverges from a live instance, the stored credential must be re-applied — a
  control-plane password reset on elastic, an in-place reset on fixed. docex
  does not yet automate this; `tte reconcile` is the planned command and will
  subsume TTE rotation. Until then, divergence is an operational incident."
- The failure is **divergence** (store ≠ what the DB was initialized against),
  not *invalidity* (mint rules guarantee validity). Recovery always =
  push the store's value onto the live instance.
- `tte reconcile` **==** TTE rotation (same op: push a store value onto the
  live instance). Filed as a future command; when built, its per-engine
  credential-apply logic should be declared in the transfer table (a
  `reconcile:` engine capability), not hardcoded in Python.

**Deferred detail (for versioning):** a legacy-username override hatch — a
project pinning a pre-existing RDS master username that can't be renamed.

---

## 2. Secrets

### 2.1 Deterministic keys → direct generation via reconciliation

The secret **key set** is fully deterministic from `infra.yml` + doctrine
(confirmed: `emit_example_env` = `TELEMETRY_API_KEY` + core `secrets:` keys +
backing engine `env:` keys of `kind: secret`). So we drop the `example.env →
copy → fill` dance and have docex own the key set directly.

"Direct generation" means **reconciliation, not regeneration**: ensure every
required key is present, flag/remove keys no longer required, and **preserve all
existing values**. Idempotent. (Regenerating from scratch would wipe values —
that is *not* what this means.)

`example.env` is **kept** as a git-tracked, **keys-only** manifest emitted at
compile (values never present) — so a PR reviewer / fresh clone sees what
secrets the project needs without running docex. It is no longer a copy-source;
it is documentation.

Secrets remain **`<env>.env`-canonical on all envs** (clobber-downstream per
`config_and_secrets.md`), unlike TTE. All secrets tooling therefore operates on the local
`infra/secrets/<env>.env` only — no SSH/SSM reads.

### 2.2 Standard form — the load-bearing invariant

> **A secret value is a flat, single-line scalar. Anything structured,
> multiline, or messy is config (or base64'd), never a secret.**

Strict flatness is what makes the tooling's safety *guaranteeable* (redaction is
a total function; `set` is a safe single-line replace) rather than best-effort.

Form spec:

- One `KEY=value` per line; split on the **first** `=` only (values may contain `=`).
- `KEY`: `[A-Z][A-Z0-9_]*`.
- `value`: the **literal bytes** after the first `=` to end-of-line. No quote
  processing, no escapes, no interpolation, no trailing-whitespace trimming.
  ("Raw literal" is the one interpretation portable across compose `env_file`,
  `--env-file`, and SSM — env-file quoting has drifted across docker/compose
  versions.)
- `#`-lines are full-line comments only (a `#` inside a value is literal).
- **Multiline / binary secrets** (PEM keys, service-account JSON) → **base64 to
  a single line**; the app decodes at startup. Keeps the strict form intact
  instead of letting one PEM break compose parsing, SSM, and redaction at once.
  (Base64 PEM fits SSM's 4 KB SecureString limit.)

**Not YAML.** All three categories stay flat `KEY=value` `.env` files. YAML on
an opaque value is dangerous (a password `yes` → boolean, `0123` → number, colons
mis-typed), and a uniform flat form keeps parsing, redaction, and tooling
identical across categories.

### 2.3 Tooling — docex subcommands (in scope for this campaign)

Deterministic action → executor stratum → **docex subcommands**, not loose
scripts.

| Op | What it does | Who runs it | Values in LLM context? |
| -- | ------------ | ----------- | ---------------------- |
| `docex secrets scaffold <env>` | reconcile key set into `<env>.env`, preserve values | agent freely | no |
| `docex secrets status <env> [--format json]` | **redacted read** — per key: `SET`/`UNSET`, source service, description; **never the value** | agent freely | no |
| `docex secrets set <env> <KEY>` | **write-only set** — set one key, read/emit nothing else | agent *invokes*, human *supplies* | **no** |
| `docex secrets copy <src_env> <tgt_env> <KEY>` | **value-blind copy** — set `tgt.KEY` = `src.KEY` without exposing the value | agent freely | **no** |

Two cruxes make this secure rather than theater:

1. **`set`'s value channel is the tty (no-echo prompt) or `--from-file`, never a
   positional arg.** A positional value would force the agent to hold the secret
   in context. Instead the agent *drives* ("run this to set `STRIPE_API_KEY`")
   while being structurally unable to *see* the value — the human types it
   straight into the running command; it never transits chat or context.
   (Container plumbing: interactive `set` needs the shim to allocate a tty;
   `--from-file` is the non-interactive fallback.)
2. **There is intentionally no `secrets get` / no value-printing command.**
   Values leave the file only at materialization (compose/SSM/host), never to
   stdout. Pit-of-success: every easy path is safe; there is no easy unsafe path.

Consequences:

- **No ACL machinery** — write-only is *intrinsic* to `set` (it writes one key,
  reads nothing). Granularity = the invocation.
- `status --format json` gives the agent a machine-readable shape
  (`{key, state, source, desc}`) to detect "required but never set" and prompt
  the human. Redaction is binary `SET`/`UNSET` only — **no** length or hash
  (those leak information).

`copy` is the *purest* form of the value-blind principle — it moves a value
env→env with **no value channel at all** (not even a tty), so the agent can fully
drive it. Its rules:

- **Applies to secrets and config, never TTE.** TTE is minted per-env and
  write-once against a live instance; copying it would neither match the target's
  instance nor respect per-env generation, and copying across the prod boundary
  would regress security. `copy` refuses a TTE key.
- **Same-side is blessed; cross-side warns.** Within a side (`dev`↔`test`,
  `stage`↔`prod`) is the intended use. A cross-side copy (esp. `dev`/`test` →
  `stage`/`prod`) seeds production with development-side values — allowed for
  fix-forward flexibility, but **emits a warning** so a blind `dev`→`prod` can't
  happen silently.
- **Unset source = error** (`KEY is unset in <src>`); **overwrites the target by
  default** (that is what copy means — e.g. refreshing `test` from `dev`) and
  reports `set`/`overwrote` in redacted terms, never the value.

---

## 3. Config

The one category with the least constraint — a deliberate **flexibility valve**
(on-doctrine: `doctrine.md` splits deterministic "doctrine" from project-specific
"design", and keeps `util` as a documented-but-discouraged escape hatch). The
real driver is **per-env, non-secret values** that CICL cannot express today
(one `infra.yml`, no per-env override) — e.g. Project A pointing at either the
dev or prod version of Project B.

### 3.1 Shape

- A new **`config:` declaration block** on core services in `infra.yml`, mirroring
  `secrets:`. Each declared key is **auto-injected** into the container as an env
  var of the same name (exactly as `secrets:` does — the compiler emits a
  self-referential runtime ref `env_block[key] = "$[key]"`); no `${config.KEY}`
  reference is needed. The value is sourced from `infra/config/<env>.env`.
- The **declaration** stays in `infra.yml` (git-tracked, LLM-readable); the
  **value** floats per-env in a non-tracked `infra/config/<env>.env`.
- **Keep the declaration requirement** — no undeclared keys. This preserves the
  no-drift / deterministic-key-set win for config too, and kills the "mystery
  env var from nowhere" failure mode. The flexibility is in the *values*
  (unconstrained, per-env, freely editable), not in the keys.
- Same rails as secrets; on elastic use a plain **`String`** SSM param, **not**
  `SecureString` (config is not secret). It is fine for config to appear in task
  defs / logs.
- Config is flat `KEY=value` like the rest — **not** YAML (uniform `.env` across all three categories).

### 3.2 Tooling — same ops, permissions inverted

The permission asymmetry *is* the category boundary, made operational:

| | secrets | config |
| - | ------- | ------ |
| `status` shows | SET/UNSET only | the **actual values** |
| `set` value channel | tty / `--from-file` only | **positional arg OK** (agent may write from context) |
| `copy` | ✅ (value-blind) | ✅ |
| `get` / print value | ❌ never | ✅ fine |

(`copy` behaves identically for config — same-side blessed, cross-side warns,
unset-source errors — it is simply lower-stakes since config values are
non-secret.)

So "secret vs config" stops being a vibe and becomes "which tooling permissions
apply."

---

## 4. Aggregation / Injection

*(Full walk is the next design session — this section captures only what is
already decided.)*

The old flow still works; it has been split at the source and re-merged.

Three circumstances:

| Circumstance | Merge happens just before… | Aggregate takes the form of… |
| ------------ | -------------------------- | ---------------------------- |
| **development** (dev/test, fixed) | `docker compose up` | `.docex/agg/<env>.env` (see §4.2) |
| **production, fixed** (stage/prod) | host `docker compose up` | host `/opt/<project>/<env>/.env` |
| **production, elastic** (stage/prod) | ECS task start / SSM push | SSM `/<project>/<env>/…` (no file) |

Decided:

- **Aggregation is a pure internal sub-step**, not a top-level verb — a shared
  `aggregate(env, ctx)` helper invoked by both the `up` path (dev/test) and the
  `release` path (fixed & elastic stage/prod), mirroring how `run_migrate` is a
  shared, foundation-dispatched helper. It has no standalone use (an unconsumed
  aggregate is just stale state) and exposing it as a verb would invite an
  operator to think it deployed something. Debug visibility is served by
  `docex secrets status` (redacted), not by a materializing verb.
- **TTE generation (`ensure_tte`) is the first sub-step of aggregation** (§1.3).
- The aggregate is a **fixed-foundation file artifact only**; on elastic
  "aggregation" = pushing all three categories to SSM (secrets/TTE as
  `SecureString`, config as `String`).
- **The merge is a disjoint union** (see §4.1) — no precedence, no layering.

### 4.1 Collision rules — categories are disjoint by construction

The aggregate is keyed by the **source-key namespace** (`POSTGRES_PASSWORD`,
`TELEMETRY_API_KEY`, `PROJECT_B_URL`) — *not* the container-env namespace
(`DATABASE_PASSWORD`) that `infra.yml` `env:`/magic-refs produce. The source-key
namespace is fully deterministic from `infra.yml` + doctrine + transfer tables
(no values, no per-env state), so all collision detection is a **compile-time
check in `cicl/validate.py`** (per `compiler.md`'s "a compile error is always
preferable" principle), not an aggregation-time check.

The three source-key sets:

| Category | Source keys |
| -------- | ----------- |
| **TTE** | backing engine `env:` entries with `kind: minted` |
| **Secrets** | core `secrets:` keys + backing engine `env:` entries with `kind: secret` + doctrine-injected (`TELEMETRY_API_KEY`) |
| **Config** | core `config:` block keys |

(`kind: fixed` vars are inlined at compile and enter no store, so they are absent
from this namespace.)

Rules:

- **Across categories: disjoint.** A source key claimed by more than one
  category is a compile error — provenance (and thus value / lifecycle /
  read-write permission) would be ambiguous. There is no legitimate case.
- **Within a category, across services: shared.** Two core services declaring
  the same key in the same category (e.g. `web` and `worker` both needing
  `STRIPE_API_KEY`) share one value, deduped in the aggregate. Forcing distinct
  names would just manufacture duplication and drift.
- **Doctrine-injected keys are reserved.** A project may not redeclare
  `TELEMETRY_API_KEY` (or future doctrine keys) in any category — same spirit as
  `reserved_names` for service names.
- The container-env namespace keeps its existing per-service uniqueness rule
  (cicl.md:114 "a key appears in at most one of `env:`/`secrets:`"), **extended
  to include `config:`**.

Because compile guarantees cross-category disjointness, the aggregation merge is
a plain disjoint union — the "who wins" precedence question is moot. Aggregation
may still *defensively* re-check, but it carries no merge semantics of its own.

A separate **conformance** check (every key in the actual `<env>.env`
is declared; no required key missing) is not compile-time — it reads the files,
so it runs at `scaffold` / `status` and defensively at aggregation.

### 4.2 Aggregate location & the store-vs-aggregate distinction

The aggregate is a **gitignored, derived, ephemeral, secret-bearing** artifact —
so it lives in none of the committed locations (`infra/output/` is committed and
non-secret) and is never a source of truth. It is always
**`(authoritative TTE store) ∪ secrets ∪ config`**, regenerated on every
`up` / `release`.

Crucially it is a *different object* from the **persistent authoritative TTE
store** (§1.4): the TTE store persists across releases and is never clobbered;
the aggregate is regenerated every time.

| Circumstance | Persistent TTE store (authority) | Secrets / Config source | **Aggregate** (derived) |
| ------------ | -------------------------------- | ----------------------- | ----------------------- |
| dev/test | `infra/tte/<env>.env` | `infra/{secrets,config}/…` | `.docex/agg/<env>.env` |
| fixed stage/prod | host `/opt/<project>/<env>/tte.env` | control-node `infra/{secrets,config}/…` | host `/opt/<project>/<env>/.env` |
| elastic stage/prod | SSM `/<project>/<env>/…` | control-node `infra/{secrets,config}/…` | SSM `/<project>/<env>/…` (same namespace) |

The non-obvious calls:

- **dev aggregate → `.docex/agg/<env>.env`.** Reuse the established `.docex/`
  convention (docex's home for gitignored ephemeral working state — worktrees
  live there; bootstrap gitignores it). It signals "derived, not a source" and
  won't be confused with the `infra/tte|secrets|config/` source files.
- **fixed prod carries two host files.** The aggregate *is* the host runtime env
  file at `/opt/<project>/<env>/.env` — **same path as today**, just now fed by
  the merge (minimal change to the ansible render step). The host *also* carries
  a separate persistent `/opt/<project>/<env>/tte.env` (the authoritative TTE
  store `ensure_tte` reads over SSH before minting). `.env` is clobbered each
  release; `tte.env` is only appended-to when a new minted key first appears.
- **elastic: no file; the SSM prefix is the aggregate.** All three categories
  land flat under `/<project>/<env>/` (today's `_push_secrets` extended to all
  three). Disjointness (§4.1) makes a flat namespace safe — no sub-prefixes. The
  only per-category behavior: **TTE keys put-if-absent** (preserve write-once
  authority), **secrets/config overwrite** (`Overwrite=True`). docex knows each
  key's category from compile and applies the right policy per key.
- **Consumption mechanism.** docex hands the aggregate to compose via
  **`--env-file <aggregate path>`** on its explicit compose invocation (it
  already passes `--project-directory` / `--project-name`, per
  masterplan § DooD). That is what resolves the `${VAR}` runtime-ref
  substitution, and is why the aggregate's name/location is a free
  docex-internal choice rather than a forced literal `.env` in the project dir.

*The aggregation walk is complete — both open items (placement, location) are
resolved above.*

---

## 5. Layout & Paths

**Subdir-per-category**, same *scheme* everywhere; only the *root* differs
(inherent: local tree / remote host / SSM prefix):

```
infra/
  secrets/            # gitignored values; example.env (keys-only manifest) tracked
    <env>.env
    example.env
  tte/                # gitignored
    <env>.env
  config/             # gitignored values; declarations live in infra.yml
    <env>.env
```

On the fixed prod host, the parallel structure lives under
`/opt/<project>/<env>/` (e.g. `/opt/<project>/<env>/tte.env`); on elastic the
parallel structure is the SSM path prefix. Standardize the scheme in all three;
do not attempt to unify the roots.

---

## 6. Meta-Questions (resolved)

1. **Standardize all paths?** Yes — subdir-per-category, same scheme in the dev
   tree, the `/opt` host, and the SSM prefix. The root differs by necessity.
2. **Re-standardize `.env` to YAML?** No — all three categories stay flat
   `KEY=value` `.env` files. YAML type-coercion is dangerous on opaque values,
   and a uniform flat form keeps parsing, redaction, and tooling identical.

---

## 7. Scope

**In scope for this campaign:**

- The three-category split.
- TTE: engine `env:` `kind` schema (`fixed`/`minted`/`secret`); username as a
  `fixed` literal; `POSTGRES_PASSWORD` as the sole `minted` value;
  `generation_policies.password` with `alphabet: url_safe`; the elastic HCL
  emitter change (inline `fixed`, SSM-source `minted`/`secret`).
- The authoritative-store rule + `ensure_tte` inside aggregation.
- Secrets: deterministic direct-generation via reconciliation; `example.env`
  demoted to keys-only manifest.
- The standard secrets **form** (incl. base64-for-multiline).
- Secrets **tooling**: `scaffold` / `status` / `set` / `copy` (pulled into scope
  — a downstream project is waiting on these).
- Config: `config:` declaration block, `<env>.env` file, same rails
  (`String` on elastic), parallel-but-permissive tooling.
- Aggregation across the three circumstances.
- Subdir-per-category layout.

**Deferred (with caveat / note):**

- `tte reconcile` / TTE rotation — foundation-general caveat only; command filed
  as a future, table-declared capability.
- Legacy-username override hatch — revisit at versioning.
- Redaction beyond binary SET/UNSET (no length/hash).

**Parked:** versioning level (aiming MINOR) and the upgrade-guide details,
including the legacy-username migration.

---

## Decisions Log

Chronological record of settled decisions, so nothing is lost between sessions.

1. The three categories map cleanly onto already-separable sources in
   `emit_example_env`; the split is a source-level reorganization, not a new
   injection model.
2. **TTE load-bearing risk downgraded.** Lost TTE creds are recoverable
   out-of-band (RDS master-password reset on elastic; `docker exec` + `ALTER
   ROLE` on fixed) → inconvenient, not destructive. docex-as-custodian-of-
   un-loseable-state framing retired.
3. **Username → `fixed` literal** (`appuser`), not minted, not stored, not
   derived. RDS can't rename a master username anyway, reinforcing "derive/fix,
   don't store."
4. **Engine `env:` gains `kind`** (`fixed`/`minted`/`secret`) driving compile
   resolution + store placement; existing `$[…]` sites unchanged.
5. **Password mint rules → new `generation_policies:` section**, not
   `naming_policies:` (generator vs formatter; allowlist cleanliness). One
   general `password` policy, `alphabet: url_safe` (non-negotiable: parts-only
   URI composition + RDS forbidden chars). stdlib CSPRNG.
6. **Generation is impure → out of `compile`**, folded into aggregation as
   `ensure_tte` (first sub-step), spanning `up` (dev/test) and `release`
   (stage/prod).
7. **Authoritative store = runtime-read store** (local / SSM / host by
   circumstance); generate-if-absent checks *that*, not blindly the local file,
   to prevent spurious re-mint → lockout.
8. **Aggregation moves the merge down the flow**, it does not eliminate it (the
   improvement is machine-merge from clean single-category inputs).
9. **Recovery = defer-with-caveat.** No per-engine prose; one foundation-general
   caveat beside rotation. `tte reconcile` == rotation; future, table-declared.
10. **Config is justified** as a deliberate flexibility valve; real driver is
    per-env non-secret values CICL can't express. `config:` declaration block +
    non-tracked `<env>.env`; keep the declaration requirement; `String` on
    elastic; flat `KEY=value` (no YAML).
11. **Secrets keys are deterministic** → direct generation via **reconciliation**
    (preserve values). `example.env` demoted to keys-only manifest. Secrets stay
    `<env>.env`-canonical; tooling is local-file only.
12. **Standard secrets form**: flat single-line scalar `KEY=value`; raw-literal
    values; base64 for multiline/binary. Not YAML.
13. **Secrets tooling** = `scaffold` / `status` (redacted, SET/UNSET only) /
    `set` (tty or `--from-file`, never positional). No `get`. No ACL (write-only
    is intrinsic). Config gets the same ops with permissions inverted.
14. **Layout** = subdir-per-category; standardize the scheme everywhere, accept
    that the root differs. Secrets & config value files gitignored; `example.env`
    and the `infra.yml` `config:` declarations tracked.
15. **Meta-Qs resolved**: standardize paths (yes); YAML — none, all three
    categories are flat `.env`.
16. **Tooling pulled into campaign scope** (form + `scaffold`/`status`/`set`),
    per operator need on a downstream project.
17. **Cross-category key overlap = compile error**; categories are disjoint over
    the **source-key namespace**, checked in `cicl/validate.py` (deterministic,
    earliest layer). Within a category, same key across services = **shared**
    value (deduped). **Doctrine-injected keys are reserved** (no redeclaration
    in any category). The per-service container-env uniqueness rule (cicl.md:114)
    is **extended to `config:`**.
18. **Aggregation is a disjoint union** as a consequence of (17) — the
    precedence / "who wins" question is **moot** and dropped from the open list.
19. **Aggregation is a pure internal sub-step**, not a top-level verb — a shared
    `aggregate(env, ctx)` helper called by the `up` path (dev/test) and the
    `release` path (stage/prod), foundation-dispatched like `run_migrate`. Debug
    visibility comes from `docex secrets status`, not a materializing verb.
20. **Aggregate location settled** (§4.2): dev → `.docex/agg/<env>.env`; fixed
    prod → host `/opt/<project>/<env>/.env` (plus a *separate* persistent
    `tte.env` authority); elastic → the flat SSM `/<project>/<env>/` prefix (TTE
    put-if-absent, secrets/config overwrite). The aggregate is a gitignored,
    derived, ephemeral artifact = `(TTE store) ∪ secrets ∪ config`, distinct
    from the persistent TTE store, consumed by compose via `--env-file`. **The
    aggregation walk is complete.**
21. **`secrets copy <src> <tgt> <KEY>` added** (§2.3) — value-blind env→env copy,
    the purest form of the value-hidden principle (no value channel at all).
    Secrets + config only, **never TTE**; same-side blessed, cross-side warns;
    unset-source errors; overwrites by default. Config gets it too.
