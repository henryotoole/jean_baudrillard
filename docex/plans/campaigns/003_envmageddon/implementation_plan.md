# Envmageddon — docex Implementation Plan

Sequencing plan for the **step-2 work** of the envmageddon campaign: updating
`docex` code to match the already-written doctrine (`config_and_secrets.md`,
`configurable.md`, and the `cicl.md` / `transfer_tables.md` edits). The design
is settled in [`plan.md`](./plan.md); this document turns it into an ordered
sequence of mod cycles grounded in the current `docex` source.

## Operator decisions (settled up front)

| Decision | Choice |
| -------- | ------ |
| Version level | **MINOR → 1.5.0**, with a project-upgrade guide (`upgrades/upgrade_1.5.0.md`). Old-pinned projects keep working via their image pin. |
| Autonomy scope | Implement every mod, keep the 5 artifacts aligned, run unit + `pytest -m integration`, migrate the smoke projects to the new layout, update docs/changelog. **STOP at ready-to-cut** — no real-infra smoke walk, no `RELEASING.md` tag/image build. |
| Doctrine edits during impl | **Fix small, flag large** — autonomously fix typos / dangling links / obvious contradictions; collect anything semantic for operator review (see [Flagged doctrine items](#flagged-doctrine-items)). |
| Legacy-username override hatch | **Deferred** — `appuser` fixed literal for everyone; filed as future alongside `tte reconcile`. |

## The backbone: `classify_source_keys`

The one new abstraction the whole campaign hangs off. A **pure** function of
`(CICLDocument, TransferTables)` returning the category of every **source key**
(the `POSTGRES_PASSWORD` / `TELEMETRY_API_KEY` / `PROJECT_B_URL` namespace, *not*
the container-env `DATABASE_PASSWORD` namespace):

```
classify_source_keys(doc, tables) -> dict[str, Category]   # Category = TTE | SECRET | CONFIG
```

Derivation (per `config_and_secrets.md § The Three Categories` + `plan.md §4.1`):
- **TTE** — backing engine `env:` entries with `kind: minted`.
- **SECRET** — core `secrets:` keys + backing engine `env:` entries with `kind: secret` + doctrine-injected (`TELEMETRY_API_KEY`).
- **CONFIG** — core `config:` block keys.
- `kind: fixed` vars are inlined at compile → absent from this namespace.

Because it is pure and cheap, **every consumer calls it directly** rather than
threading state:
- `cicl/validate.py` — cross-category disjointness + reserved-key rules.
- `emit/hcl.py` — String (config) vs SecureString (secret/TTE) SSM choice.
- the aggregation helper + `release` — put-if-absent (TTE) vs overwrite (secret/config) routing, and which source file feeds each key.
- `docex secrets` / `docex config` tooling — which keys each command legitimately touches.

Introduced in **Mod 078** (with the config block); consumed from Mod 079 onward.

## Current-state anchors (where each change lands)

- `EngineEntry.env` is `dict[str, str]` (key→desc). → becomes `dict[str, EnvVarSpec]`. `src/docex/cicl/transfer.py:103`.
- No `generation_policies` section; `_ALLOWED_TOPLEVEL_KEYS = {roles, naming_policies}`. `transfer.py:45`.
- `$[VAR]` runtime refs are emitted verbatim by substitution; the elastic emitter turns *every* `$[VAR]` in a backing body into an `aws_ssm_parameter` data source (`emit/hcl.py:236`) and every bare-`$[REF]` core env value into an ECS `secrets[]` entry (`emit/hcl.py:274`).
- `POSTGRES_USER` / `POSTGRES_PASSWORD` appear as `$[…]` in four sites of `tables/roles/relational_db.yml` (fixed env, healthcheck, elastic username, `provides.user`) + password twice.
- `env_file_for` returns `infra/secrets/<env>.env` and is fed to compose `--env-file` (`orchestrate/_common.py:60`, `up.py`, `migrate.py`).
- `_push_secrets` reads `infra/secrets/<env>.env` line-by-line and pushes each to SSM `overwrite=True` (`pipeline/release.py:375`).
- `CoreService` has `env`/`secrets`, no `config` (`cicl/model.py:86`).
- `emit_example_env` iterates backing `entry.env` as `{key: descstr}` (`emit/secrets.py`).
- CLI dispatch is a flat handler table in `__main__.py`; no nested subcommands yet.

## Mod sequence

Each is a full mod cycle (overview → implementation.md → foreground sub-agent →
drift review → tests). Ordering keeps the suite green at every boundary.

### Mod 076 — Transfer-table `kind` schema + generation policies
**Touches:** `tables/roles/relational_db.yml`, new `tables/generation_policies.yml`, `cicl/transfer.py`, new `cicl/generate.py`, `emit/secrets.py`, `tables/README.md`.
- `EngineEntry.env` → `dict[str, EnvVarSpec]` (`kind: fixed|minted|secret`; `value` for fixed; `policy` for minted; `desc`). Loader parse + strict per-file validation (kind required; value⇔fixed; policy⇔minted references a defined generation policy).
- New top-level `generation_policies:` (allowlist + `GenerationPolicy{length, alphabet}` + parse; sibling to `naming_policies`, kept out of the naming allowlists per `plan.md §1.2`).
- `cicl/generate.py`: pure CSPRNG generator (`secrets` module), `url_safe` alphabet (`[A-Za-z0-9]`), `generate(policy) -> str`. Unit-testable; **not** called from compile.
- Rewrite postgres `env:` to the kind schema (`POSTGRES_USER` fixed=`appuser`; `POSTGRES_PASSWORD` minted policy=`password`); add `generation_policies.password{length:32, alphabet:url_safe}`.
- `emit_example_env` → new shape: emit **secret-kind backing keys + core `secrets:` + `TELEMETRY_API_KEY` only** (keys-only manifest per `plan.md §2.1`); minted/fixed excluded.
- **Tests:** loader accept/reject of kind + generation-policy schema; generator charset/length; example.env excludes minted/fixed.

### Mod 077 — Compiler: kind-aware `$[VAR]` resolution
**Touches:** `cicl/compile.py`, `cicl/magic_refs.py` / `cicl/substitute.py`.
- When resolving a backing service's own body + `provides:` templates, a `$[VAR]` whose engine `env[VAR].kind == fixed` is replaced by the literal `value` at compile; `minted`/`secret` stay as `$[VAR]`. The resolver already holds `engines` — give it the "resolving-against-this-engine" context.
- Net effect (no emitter change needed): `POSTGRES_USER` inlines to `appuser` in compose env, healthcheck, RDS `username`, and consumer `DATABASE_USER`; the elastic SSM data-source + `secrets[]` machinery now only fires for `POSTGRES_PASSWORD` because it is the only surviving `$[VAR]`.
- **Tests:** compose has `POSTGRES_USER: appuser` literal + `${POSTGRES_PASSWORD}`; elastic RDS `username="appuser"`, one SSM data source (password only); consumer user part is a literal, password is `secrets[]`.

### Mod 078 — `config:` block + `classify_source_keys` backbone
**Touches:** `cicl/model.py`, new `cicl/categories.py`, `cicl/compile.py`, `emit/hcl.py`.
- `CoreService.config: dict[str, str]` (declaration only; values float per-env).
- New `cicl/categories.py::classify_source_keys` (the [backbone](#the-backbone-classify_source_keys)).
- Compile: after the `secrets:` loop, `env_block[key] = "$[key]"` for each `config:` key (self-referential runtime ref, mirroring secrets). Carry the classification onto `CompiledEnv` (convenience) — but keep the function pure and independently callable.
- Elastic emit: choose SSM param type per `$[REF]` category — **config = `String`**, secret/TTE = `SecureString`. (See flagged item on config delivery mechanism.)
- **Tests:** config key auto-injected on both foundations; elastic config → String, secret → SecureString; fixed compose `${KEY}`.

### Mod 079 — Cross-category disjointness + reserved-key + config uniqueness validation
**Touches:** `cicl/validate.py` (align rule numbers with the edited `cicl.md`; rules 16 & 20 per `config_and_secrets.md`).
- Source-key namespace **disjoint across categories** → compile error (uses `classify_source_keys`).
- Doctrine-injected keys **reserved in every category** (extend the reserved-key check to config).
- Per-service container-env uniqueness extended to include `config:` (extend `_validate_env_secrets_overlap` to three-way).
- **Tests:** overlap across categories errors; `TELEMETRY_API_KEY` redeclared in config errors; same key in env+config errors.

### Mod 080 — `aggregate()` + `ensure_tte()` — dev/test path
**Touches:** new `orchestrate/aggregate.py`, `orchestrate/_common.py` (`env_file_for` → aggregate), `orchestrate/up.py`, `orchestrate/migrate.py`, `.gitignore` defaults.
- `aggregate(env, ctx)` foundation-dispatched (mirrors `run_migrate`). Dev/test branch: `ensure_tte` reads/generate-if-absent into `infra/tte/<env>.env` (authoritative store for dev/test), then writes `.docex/agg/<env>.env` = `tte ∪ secrets ∪ config`.
- `up`/dev-`migrate` call `aggregate` first and feed `.docex/agg/<env>.env` to compose `--env-file` (and `DOCEX_SECRETS_ENV_FILE`).
- Bootstrap/inception gitignore: `.docex/`, `infra/tte/`, `infra/config/` value files.
- **Tests:** first `up` mints `POSTGRES_PASSWORD` into `infra/tte/dev.env`; aggregate holds all three; re-run reuses (no re-mint); integration `up dev` smoke.

### Mod 081 — Aggregation on the fixed stage/prod release path
**Touches:** `pipeline/release.py` (`_release_fixed`), `emit/ansible.py` + `templates/playbook.yml.j2`, `ssh` client.
- `ensure_tte` reads/writes the host `/opt/<project>/<env>/tte.env` over SSH (authoritative store). Aggregate = `tte ∪ secrets ∪ config` rendered to host `/opt/<project>/<env>/.env` (same runtime path as today — now merge-fed).
- **Tests:** unit (mocked SSH + render assertions); real path covered by the fixed smoke walk (out of autonomous scope).

### Mod 082 — Aggregation on the elastic stage/prod release path
**Touches:** `pipeline/release.py` (`_push_secrets` → `aggregate`-driven), `aws/boto3_client.py`, `aws/client.py`.
- Replace `_push_secrets` with a 3-category SSM push: **TTE put-if-absent** (get→generate→put, preserving write-once authority), **secrets/config overwrite=True**; secret/TTE `SecureString`, config `String`. Uses `classify_source_keys` directly (release already recompiles).
- Add `ssm_get_parameter` (existence/read) to the AWS client surface.
- **Tests:** integration (moto or real-ish) — put-if-absent vs overwrite; String vs SecureString; existing TTE reused.

### Mod 083 — `docex secrets` command group
**Touches:** new `secretsmgmt/` (shared file engine), `__main__.py` (nested subparser + help groups), `bin/docex` (tty allocation).
- `scaffold` (reconcile deterministic secret key set into `infra/secrets/<env>.env`, preserve values), `status [--format json]` (redacted SET/UNSET + source + desc), `set <KEY>` (tty no-echo prompt or `--from-file`; single-line replace; never positional), `copy <src> <tgt> <KEY>` (value-blind; secrets/config only, never TTE; same-side blessed / cross-side warn; unset-source error; overwrite default).
- Shim: allocate `-it` when stdin is a tty (additive, backward-compatible; version-independent shim rule preserved).
- **Tests:** reconcile add/flag/preserve; status redaction (SET/UNSET only, no length/hash); set via `--from-file`; copy rules incl. TTE refusal + cross-side warning.

### Mod 084 — `docex config` command group (permissions inverted)
**Touches:** `secretsmgmt/` (permission flag), `__main__.py`.
- Same ops on `infra/config/<env>.env` with inverted permissions: `status` shows values, `set` positional-arg OK, `get` prints, `copy` identical rules (lower-stakes). Reuse the Mod 083 engine.
- **Tests:** config status shows values; set positional; get prints; copy parity.

### Mod 085 — Smoke-project migration to the new layout
**Touches:** `test_projects/{fixed,elastic}/infra/{secrets,config,tte}/`, `.gitignore`, READMEs; recompile; inner-repo commits + outer catchup per `test_projects.md` cadence.
- Split each `<env>.env`: keep `TELEMETRY_API_KEY` (+ any real secrets) in `secrets/`, move non-secret per-env values to `config/`, drop `POSTGRES_*` (now minted TTE). Add `infra/config/`, `infra/tte/` + gitignore. Recompile with source docex; verify clean.
- Version repin to 1.5.0 is noted for cut time (image doesn't exist until the cut).

### Mod 086 — Core-doc alignment + upgrade guide + changelog
**Touches:** `docex/plans/core/{compiler.md,release_flow.md,masterplan.md}`, `docex/plans/core/docex_process.md` (artifact table stays valid), `upgrades/upgrade_1.5.0.md`, `CHANGELOG.md`.
- Reflect: kind schema, generation policies, `classify_source_keys`, aggregation across the 3 circumstances, `secrets`/`config` subcommands, subdir-per-category layout.
- `upgrade_1.5.0.md`: split-the-env-file + mint-TTE + add-config + repin steps for downstream projects.
- Mark `003_envmageddon/plan.md` status → implemented (pending cut).

## Flagged doctrine items (fix-small/flag-large)

Collected here as I hit them; resolved with the operator before/at cut.

1. **Config delivery on elastic (SEMANTIC — flag).** `config_and_secrets.md` line ~206 says config is delivered via ECS `environment[]` "sourcing" the SSM path. ECS `environment[]` entries are *static inline values*; only `secrets[]` can `valueFrom` an SSM parameter — and `secrets[]` works for plain `String` params too, not just `SecureString`. **Recommended resolution:** config is delivered via `secrets[]` `valueFrom` against a `String` SSM param (the `String`/`SecureString` split is about SSM storage/KMS, not the ECS delivery verb). Proceeding on this reading in Mod 078/082; doctrine wording to be tightened at cut. Will implement so config still lands as a plain container env var identical in shape to secrets.

2. **`docex config` command surface not in `docex.md` (GAP — flag).** `docex.md § Command surface` documents the `secrets` group but not a `config` group, while `config_and_secrets.md § Tooling` (and `plan.md §3.2`) explicitly give config the same ops with inverted permissions (`status` shows values, `set` positional OK, `get` prints, `copy` value-blind, plus `scaffold`). **Recommended resolution:** implement `docex config` per `config_and_secrets.md` (Mod 084) and add the matching `### config` section to `docex.md` — documenting a surface the tooling doctrine already mandates, not inventing a new rule. Flagged because it touches the authoritative command-surface doc.

## Process notes

- Work on `main` (release trunk; per `docex_process.md` trunk-based + memory).
- Commit the operator's uncommitted envmageddon **doctrine** + this plan as the step-1 baseline before Mod 076, so each mod diff is clean.
- Keep the [five artifacts](../../core/docex_process.md#additional-artifacts) aligned every mod: doctrine ⇄ core docs ⇄ tables ⇄ src ⇄ tests.
- No manual-test pause (docex mods have none); run automated tests at each mod's end.
