# Mod 086 — Implementation steps

Two tracks. **Track A** (this file, for a sub-agent): mechanical alignment of the
three `docex/plans/core/*` narrative docs. **Track B** (orchestrator, not this
file): `upgrade_1.5.0.md`, the `CHANGELOG` entry, the advance-status flip.

The sub-agent does **Track A only**. Do **not** edit `upgrades/`, `CHANGELOG.md`,
`plans/advances/`, any `doctrine/` file, `tables/`, `src/`, or `tests/`.

## What changed across mods 076-085 (context for the edits)

- **076** engine `env:` gained a per-var `kind` (`fixed`/`minted`/`secret`,
  default secret); `EngineEntry.env: dict[str, EnvVarSpec]`. New top-level
  `generation_policies:` (`{length, alphabet}`) + `cicl/generate.py` (CSPRNG
  `generate`, `url_safe`/`alnum`). `emit_example_env` → secrets-only keys
  manifest.
- **077** compiler inlines a `kind: fixed` `$[VAR]` to its literal `value:` at
  compile (in `cicl/magic_refs.py`); `minted`/`secret` stay runtime refs. So
  `POSTGRES_USER`→`appuser` everywhere and the elastic SSM data-source/`secrets[]`
  fire only for `POSTGRES_PASSWORD` — no emitter change.
- **078** `CoreService.config`; `cicl/categories.py::classify_source_keys` (pure
  TTE/secret/config partition of the source-key namespace) +
  `SourceKeyCategories`; config keys wired as self-ref runtime refs at compile —
  identical shape to a secret, no emitter change.
- **079** validation: rule 16 three-way env/secrets/config overlap; rule 20
  project-wide cross-category disjointness (via the classifier); doctrine-injected
  keys reserved in every category.
- **080** `orchestrate/aggregate.py` + `envfile.py`: dev/test `aggregate()` =
  `ensure_tte` (mint-if-absent into `infra/tte/<env>.env`) → merge → write
  `.docex/agg/<env>.env`; `env_file_for` now returns that aggregate path (pure);
  every fixed-env bring-up feeds it to compose.
- **081** fixed stage/prod: `SSHClient.capture` reads the host-authoritative
  `/opt/<project>/<env>/tte.env`; `aggregate_fixed_prod` stages the aggregate +
  the TTE superset; the ansible playbook renders `.env` (aggregate) + `tte.env`
  onto the host via `--extra-vars`.
- **082** elastic stage/prod: `aggregate_elastic` replaces `_push_secrets` — TTE
  minted-if-absent (`SecureString`, put-if-absent), secrets overwrite
  (`SecureString`), config overwrite (`String`); AWS client gained
  `ssm_get_parameter` + a `param_type` arg.
- **083/084** `docex secrets` (value-blind) + `docex config` (permissions
  inverted); `secretsmgmt/` engine; `secret_manifest`/`config_manifest`
  (`cicl/categories.py`); `envfile.set_env_key`; shim conditional `-t -i`.

## Track A edits

### `docex/plans/core/compiler.md`

1. **Key types** (`src/docex/cicl/`): add `EnvVarSpec` (the `kind` schema),
   `GenerationPolicy`/`generate` (note the module is `cicl/generate.py` — a
   sibling to `naming.py`), and `SourceKeyCategories`/`classify_source_keys`
   +`secret_manifest`/`config_manifest`/`minted_policies` (`cicl/categories.py`).
2. **Substitution grammar** section: add a line that a `$[VAR]` naming a
   `kind: fixed` engine env var is inlined to its literal at compile time (in
   `magic_refs.py`), while `minted`/`secret` stay runtime pass-through — so the
   backing-body/`provides` `$[VAR]` for a fixed var never reaches emit.
3. **Validation** section: add rule 13 (minted `policy:` → a defined
   `generation_policies` entry, load-time), rule 14 (fixed⇒`value`/no-`policy`,
   minted⇒`policy`/no-`value`), rule 16 (per-service env/secrets/config
   three-way overlap), rule 20 (project-wide cross-category source-key
   disjointness + doctrine-injected reserved).
4. **`example.env`** description (the `emit/secrets.py` paragraph): it is now a
   secrets-only keys manifest rendered from `secret_manifest` (core `secrets:` +
   backing `kind: secret` + doctrine-injected). `kind: fixed`/`minted` vars are
   absent (inlined / minted respectively).
5. **"Where to look when changing things"** table: add rows —
   - engine env `kind` / a fixed literal / a minted policy → `tables/roles/*.yml`
     `env:` + `tables/generation_policies.yml`; loader in `cicl/transfer.py`.
   - how a minted value is generated → `cicl/generate.py`.
   - how `$[VAR]` resolves per kind → `cicl/magic_refs.py::_inline_fixed`.
   - the config block → `cicl/model.py` + the config loop in `cicl/compile.py`.
   - which category a source key is in → `cicl/categories.py`.
   - the container-facing env file (dev/test) → `orchestrate/aggregate.py` +
     `envfile.py`.

### `docex/plans/core/release_flow.md`

1. **Scope / inputs**: the secrets source is now three category dirs
   (`infra/{secrets,config,tte}/`) merged by aggregation, not a single
   `<env>.env`.
2. **Fixed-foundation flow**: before the playbook, docex builds the aggregate —
   `ensure_tte_fixed` SSH-reads the host-authoritative
   `/opt/<project>/<env>/tte.env` (`SSHClient.capture`), mints missing minted
   keys, stages the superset; `aggregate_fixed_prod` writes `.docex/agg/<env>.env`.
   The playbook renders `tte.env` (store) + `.env` (aggregate) onto the host via
   `--extra-vars`. Note: `docex migrate stage/prod` reads the host `.env` a prior
   release rendered (the untagged copy tasks are skipped under `--tags migrate`).
3. **Elastic-foundation flow** step 1: `_push_secrets` is replaced by
   `aggregate_elastic` — the SSM prefix `/<project>/<env>/` IS the aggregate;
   TTE minted-if-absent (`SecureString`, never clobbers a live value → no RDS
   lockout), secrets overwrite (`SecureString`), config overwrite (`String`).
   `dry_run` skips it; `skip_migrations`/rollback preserves live TTE.
4. **"Where to look" tables**: add — SSM push semantics →
   `orchestrate/aggregate.py::aggregate_elastic` (not the removed
   `release.py::_push_secrets`); TTE minting →
   `aggregate.py::ensure_tte_elastic`/`ensure_tte_fixed`; the host TTE read →
   `ssh` client `capture`; SSM get → `aws/boto3_client.py::ssm_get_parameter`;
   the fixed aggregate/store render → the playbook `agg_env_file`/`tte_store_file`
   extra-vars.
5. If the rollback section lists a "mirror step", note it now also mirrors
   `infra/config/<env>.env` into the worktree.

### `docex/plans/core/masterplan.md`

1. **Subcommand surface** table: add `secrets` (`scaffold`/`status`/`set`/`copy`;
   both foundations; reads/writes `infra/secrets/<env>.env`) and `config`
   (`scaffold`/`status`/`set`/`get`/`copy`; reads/writes `infra/config/<env>.env`).
2. **Filesystem surface**: under Read add `infra/tte/<env>.env` (dev/test TTE
   store), `infra/config/<env>.env`; under Write add `infra/tte/<env>.env`
   (dev/test minting), `.docex/agg/<env>.env` (the derived aggregate). Note the
   aggregate is gitignored (under the existing `.docex/`).
3. **The Shim** section: one line that the shim allocates `-t -i` only on an
   interactive terminal (for `docex secrets set`'s no-echo prompt), additive +
   backward-compatible.

Keep edits surgical and in each doc's existing voice/format. Do not restate
`config_and_secrets.md`; link to it where the core doc would otherwise duplicate
the model.

## Definition of done (Track A)

- The three core docs mention every mod-076-085 behavior a reader would look for,
  with correct file/symbol pointers, and no dangling references to removed
  symbols (e.g. `_push_secrets`).
- No file outside `docex/plans/core/{compiler,release_flow,masterplan}.md`
  touched. (Track B — upgrade guide, changelog, advance status — is the
  orchestrator's.)
