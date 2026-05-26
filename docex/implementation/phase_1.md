# `docex` — Phase 1 Implementation

This document covers the work needed to ship Phase 1 of `docex`: the `compile`, `describe`, and `why` commands, plus the full project scaffolding (shim, Dockerfile, dispatcher, transfer tables) that all later phases will build on.

Phase 1's success criterion: a developer can author `project.yml` + `infra/infra.yml` against a project with one core service and one or two backing services, run `./bin/docex compile`, and get back fully-realized output under `infra/output/<env>/`. They can also run `docex describe <env>` to inspect what was produced and `docex why <resource>` to understand the reasoning.

## Required Reading

Before starting, read these files in order:

1. `~/.claude/jean_baudrillard/doctrine/overview.md` — what the doctrine is for.
2. `~/.claude/jean_baudrillard/doctrine/lexicon.md` — load-bearing vocabulary.
3. `~/.claude/jean_baudrillard/docex/design_proposal.md` — sibling of this file. Authoritative for `docex` architecture, mounts, and scope.
4. `~/.claude/jean_baudrillard/doctrine/infrastructure/infrastructure.md` — overall infra model.
5. `~/.claude/jean_baudrillard/doctrine/infrastructure/cicl.md` — CICL format and validation rules.
6. `~/.claude/jean_baudrillard/doctrine/infrastructure/shape2.md` — infrastructure shape per foundation.
7. `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/transfer_tables.md` — transfer table format, substitution grammar, validation. This is the densest spec; read carefully.
8. `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/networks.md` — network compilation per foundation.
9. `~/.claude/jean_baudrillard/doctrine/infrastructure/docex.md` — authoritative behavior for `compile`, `describe`, `why`.
10. `~/.claude/jean_baudrillard/doctrine/infrastructure/credentials.md` and `specifics/release_mechanism.md` — for context on what the secrets/deploy_creds folders are (you won't touch them in Phase 1, but `compile` emits `example.env`).

## Scope Boundaries (Important)

**In scope for Phase 1:**
- The `docex` Python package and its CLI dispatcher (with stubs for all future commands).
- The `compile`, `describe`, and `why` subcommands, fully implemented.
- The canonical transfer tables for a minimum viable set of roles/engines.
- The `Dockerfile` for the Phase 1 image.
- The `./bin/docex` shim (full version — same shim ships across all phases).
- An install script (`docex_install.sh`) in `~/.claude/jean_baudrillard/` that copies the shim into a project and pins `docex_version` in its `project.yml`.
- Unit and integration tests for the compiler.

**Explicitly NOT in scope:**
- `up`, `down`, `build`, `test`, `migrate` — Phase 2.
- `check`, `merge`, `containerize`, `release`, `stagetest` — Phase 3.
- `bootstrap` (elastic state backend) — Phase 4.
- Anything that requires the docker socket, AWS API, or git operations.
- Tofu, Ansible, AWS CLI in the image. Phase 1 image only needs Python.

The dispatcher must reserve the *interface shape* for all future commands by stubbing them with a clear "<command> is part of <phase>; not yet implemented" message — never with a generic "unknown command".

## Step-by-Step Implementation

### Step 1: Repository scaffolding

Create the directory layout described in [design_proposal.md § Repository Structure](../design_proposal.md#repository-structure) under `~/.claude/jean_baudrillard/docex/`. Phase 1 needs:

```
docex/
├── design_proposal.md           (exists)
├── implementation/
│   └── phase_1.md               (this file, exists)
├── pyproject.toml
├── Dockerfile
├── bin/
│   └── docex                    (the shim template; copied into projects)
├── src/
│   └── docex/
│       ├── __init__.py
│       ├── __main__.py          (CLI entrypoint, argparse dispatcher)
│       ├── context.py           (project discovery, project.yml + infra.yml loading)
│       ├── errors.py            (shared exception types + formatted error reporting)
│       ├── cicl/
│       │   ├── __init__.py
│       │   ├── model.py         (pydantic schema for infra.yml)
│       │   ├── validate.py      (cicl.md § Validation Rules)
│       │   ├── substitute.py    (${...}, $[...], @... substitution engine)
│       │   ├── transfer.py      (transfer table loading + deep merge)
│       │   ├── magic_refs.py    (${backing_services.X.Y} resolution)
│       │   └── compile.py       (the compiler proper)
│       ├── emit/
│       │   ├── __init__.py
│       │   ├── compose.py       (docker-compose.yml emitter)
│       │   ├── hcl.py           (main.tf emitter)
│       │   ├── ansible.py       (playbook.yml/inventory.yml/ansible.cfg emitter)
│       │   └── secrets.py       (example.env emitter)
│       ├── describe/
│       │   ├── __init__.py
│       │   ├── dag.py           (text DAG renderer)
│       │   └── llm.py           (JSON-for-LLM renderer)
│       └── why/
│           ├── __init__.py
│           └── catalog.py       (resource → explanation mapping)
├── tables/                       (canonical transfer tables; bundled into image)
│   ├── roles/
│   │   ├── web.yml
│   │   ├── relational_db.yml
│   │   ├── cache.yml
│   │   ├── object_store.yml
│   │   └── reverse_proxy.yml
│   └── README.md
├── doctrine_excerpts/            (markdown snippets backing `docex why`)
│   ├── network_web.md
│   ├── network_internal.md
│   ├── reverse_proxy.md
│   ├── cert_manager.md
│   ├── ... (one per `why`-queryable resource — see Step 9)
│   └── index.yml                 (resource name → file mapping)
├── ansible/                      (template playbook; empty/placeholder for Phase 1)
│   └── .gitkeep
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
        └── sample_project/       (a minimal project used by integration tests)
            ├── project.yml
            └── infra/
                └── infra.yml
```

Create `pyproject.toml` with `docex` as the package name, entry point `docex = "docex.__main__:main"`, Python `>=3.12`, and dependencies: `pydantic>=2`, `pyyaml`, `jinja2` (used by HCL/playbook templates), `rich` (used for DAG output and error formatting).

### Step 2: CLI dispatcher with stubs

In `src/docex/__main__.py`, build an `argparse`-based dispatcher. Implement subcommands as:

- `compile` — fully implemented in Step 7
- `describe` — fully implemented in Step 8
- `why` — fully implemented in Step 9
- `up`, `down` — stub: print `"'<cmd>' is part of Phase 2 (fixed dev loop); not yet implemented in docex <version>"`, exit code 2
- `build`, `test`, `migrate` — same Phase 2 stub
- `check`, `merge`, `containerize`, `release`, `stagetest` — Phase 3 stub
- `bootstrap` — Phase 4 stub
- Unknown command — exit code 64 (`EX_USAGE`), print usage with the full subcommand list (stubs included) so users discover the eventual surface.

The version string the stubs print should come from `docex.__version__`. Set this to `"0.1.0"` for Phase 1.

The top-level dispatcher must not crash if `project.yml` is missing. Loading it is each subcommand's responsibility — some future commands may not need it.

**Success criterion:** `python -m docex compile`, `python -m docex describe`, `python -m docex why dns`, and `python -m docex up dev` all print sensible output (real or stubbed).

### Step 3: Project context loading

`src/docex/context.py` provides one function: `load_project_context(cwd: Path) -> ProjectContext`.

`ProjectContext` is a dataclass with at minimum:
- `project_root: Path` — found by walking upward from `cwd` looking for `project.yml`
- `project: ProjectManifest` (name, version, docex_version)
- `infra: CICLDocument` — parsed `infra/infra.yml`
- `transfer_tables: TransferTables` — bundled + project-local merged (Step 5)

Failure modes to handle with clear error messages:
- No `project.yml` found anywhere up to `/`
- `project.yml` malformed
- `docex_version` in `project.yml` doesn't match the running `docex` version (warning, not fatal, for Phase 1; will become enforced via the shim later)
- `infra/infra.yml` missing — fatal only for commands that need it (`compile`, `describe`); `why` doesn't need it

Errors raised here propagate to `__main__.py` and are printed with `rich` traceback-free formatting. Stack traces only on `--debug`.

### Step 4: CICL data model

`src/docex/cicl/model.py` defines pydantic v2 models for the CICL document. Mirror the schema in [cicl.md § Service Fields](../../doctrine/infrastructure/cicl.md#service-fields):

- `CICLDocument`: `cicl_version`, `foundation` (Literal["fixed", "elastic"]), `domain`, `container_registry` (optional on elastic), `core_services: dict[str, CoreService]`, `backing_services: dict[str, BackingService]`.
- `CoreService`: `role`, `networks`, `resources` (required), `depends_on`, `port`, `env`, `replicas`, `command`.
- `BackingService`: `role`, `networks`, `engine` (str or list), `version`, `depends_on`, `port`, `schema_owned_by`. Plus a permissive `dict[str, Any]` for role-specific fields (postgres has none beyond `version`; object_store has `versioning`; etc.). These are validated against the transfer table in Step 5, not at the model layer.
- `Resources`: `cpu: float`, `memory: str` (validated against `MB|GB` decimal units per cicl.md), `disk: str | None`, `gpu: GPUSpec | None`.

Use pydantic's `model_validator` for cross-field rules that depend on multiple fields of the same model (e.g. parsing the memory string). Save cross-document validation (depends_on graph, magic ref resolution, container_registry-on-fixed) for Step 6.

### Step 5: Transfer table loader

`src/docex/cicl/transfer.py` loads transfer tables and exposes them as a queryable object. Per [transfer_tables.md § Anatomy of a Role Definition](../../doctrine/infrastructure/specifics/transfer_tables.md#anatomy-of-a-role-definition), each table is YAML rooted under `roles:`.

The loader:

1. Reads all YAMLs under `/opt/docex/tables/` (inside the image) — the **bundled** canonical tables.
2. Reads all YAMLs under `<project_root>/infra/transfer_tables/` if that directory exists — **project-local** tables.
3. Deep-merges them: project-local wins on conflict at the leaf level. Document the merge semantics in `tables/README.md`.
4. Exposes:
   - `tables.role(role_name)` → list of engine entries
   - `tables.engine(role_name, engine_name)` → the engine entry
   - `tables.engine_for(role_name, engine_decl, foundation)` → resolves `engine: [minio, s3]` against the target foundation by checking each candidate's own `foundation:` field.

**Phase 1 ships canonical tables for these roles/engines** (minimum to compile the doctrine's example infra.yml):

| Role | Engine(s) | Notes |
| ---- | --------- | ----- |
| `web` | `container` (both) | Core service role. See [transfer_tables.md § Walking example: `web` / `container`](../../doctrine/infrastructure/specifics/transfer_tables.md#walking-example-web--container). |
| `relational_db` | `postgres` (both) | See [transfer_tables.md § Walking example: `relational_db` / `postgres`](../../doctrine/infrastructure/specifics/transfer_tables.md#walking-example-walking-example-relational_db--postgres). Should also support an elastic RDS variant. |
| `cache` | `redis` (both) | Container on fixed; ElastiCache on elastic. |
| `object_store` | `minio` (fixed), `s3` (elastic) | Two separate engine entries, each declaring its `foundation`. |
| `reverse_proxy` | `traefik` (fixed) | Mostly a passive role on fixed — the prereq machine-wide traefik watches the docker network. On elastic, the ALB is doctrine-provided per env (not from `infra.yml`), so no elastic engine here. Document this asymmetry in `tables/roles/reverse_proxy.yml`. |

For each engine, fill in `defaults`, `fields`, `provides`, `env`, and `naming` per the transfer_tables spec. Use the postgres and container examples in the doctrine as your starting point — they are intended to be canonical.

### Step 6: Substitution engine and magic refs

`src/docex/cicl/substitute.py` and `src/docex/cicl/magic_refs.py` implement the three-syntax substitution grammar from [transfer_tables.md § Substitution Grammar](../../doctrine/infrastructure/specifics/transfer_tables.md#substitution-grammar):

- `${var}` — **compile-time.** Resolved by the compiler against a substitution context that includes `name`, `global_service_name`, `port`, `networks`, `project_name`, `env_name`, `role_name`, `env_subdomain`, `field_value`, and the resolved values of magic refs.
- `$[var]` — **runtime pass-through.** The substituter leaves these alone but tracks them; the emitter (Step 7) translates them per target language (compose `${var}` / ECS `secrets[]`).
- `@<expr>` — **HCL pass-through (elastic only).** The substituter resolves any `${var}` inside the expression, strips the `@` prefix, and marks the result as raw HCL. The fixed emitter must error if it sees one; the HCL emitter writes it verbatim.

Magic refs (`${backing_services.X.Y}` and `${core_services.X.Y}` if applicable) resolve by:
1. Looking up service X in the parsed `infra.yml`.
2. Finding its engine's `provides:` block.
3. Returning the `Y` part's foundation-appropriate template, recursively substituted in X's context.
4. Recording the dependency for validation (rule 7 in [cicl.md § Validation Rules](../../doctrine/infrastructure/cicl.md#validation-rules)).

**Tests for this step are essential** — substitution bugs will silently produce wrong infrastructure. Write fixture-based tests covering:
- Simple `${var}` resolution
- Magic ref chains (`${backing_services.database.url}` resolves through a template containing `${port}` and `$[POSTGRES_USER]`)
- `@<expr>` with embedded `${var}`
- Mixed syntax in one string
- Error cases: undefined `${var}`, magic ref to nonexistent service, magic ref to part not in `provides:`, `@` syntax in a fixed-target template

### Step 7: The `compile` command

`src/docex/cicl/compile.py` is the heart of Phase 1. The compiler's job is to turn `infra.yml` into the per-environment output described in [cicl.md § Compiler Output](../../doctrine/infrastructure/cicl.md#compiler-output).

Process per `docex compile` invocation:

1. Load project context (Step 3) and transfer tables (Step 5).
2. Run all validation rules from [cicl.md § Validation Rules](../../doctrine/infrastructure/cicl.md#validation-rules). Each failure is collected and reported together (not one-at-a-time) so the developer can fix multiple issues per cycle.
3. For each environment in `["dev", "test", "stage", "prod"]`:
   1. Determine the target foundation per [shape2.md § Shape and Environment](../../doctrine/infrastructure/shape2.md#shape-and-environment): `dev` and `test` are always fixed; `stage` and `prod` use the project's declared foundation.
   2. Build the substitution context for this env (`env_name`, `env_subdomain`, etc.).
   3. For each service in `infra.yml`:
      - Look up its engine in the transfer tables for this foundation.
      - Merge `defaults`, apply `fields`, resolve `provides:` templates as needed.
      - Apply [foundation invariants](../../doctrine/infrastructure/specifics/transfer_tables.md#foundation-invariants): per-container additions (container_name, logging, restart, networks) for fixed; tags for elastic.
      - Apply [resources translation](../../doctrine/infrastructure/specifics/transfer_tables.md#resources-translation).
      - Compile network membership per [networks.md](../../doctrine/infrastructure/specifics/networks.md): `${project}_${env}_${network}` docker network or AWS SG.
   4. Hand the resulting in-memory representation to the appropriate emitter:
      - **Fixed envs** → `emit/compose.py`. For `stage`/`prod` *also* `emit/ansible.py`.
      - **Elastic envs** (stage/prod under elastic foundation) → `emit/hcl.py`.
4. Always emit `infra/secrets/example.env` via `emit/secrets.py`, gathering every `env:` entry from every backing service's transfer-table engine, grouped by service with comment headers.
5. Write outputs to `<project_root>/infra/output/<env>/...`. Existing files are overwritten; the directory is created if missing.

The compiler must be deterministic: identical inputs produce byte-identical outputs. YAML key order, HCL block order, and any iteration over dicts must be stable (sort by service name where order is otherwise undefined).

#### Emitter notes

- **`emit/compose.py`:** Emit `docker-compose.yml` only. The doctrine's per-compose-file logging anchor (`x-logging`) goes at the top. Each service gets its emitted block. Networks and volumes go at the bottom.
- **`emit/hcl.py`:** Emit one `main.tf` per env. Include provider block, state backend reference, network resources (VPC subnets, security groups), ALB, ECS cluster/service/task-definition per core service, RDS/S3/etc. per backing service, and Route53 records. Use Jinja2 templates under `src/docex/emit/templates/`.
- **`emit/ansible.py`:** For fixed stage/prod, emit `playbook.yml`, `inventory.yml`, and `ansible.cfg`. Inventory derives from `domain` per [release_mechanism.md § Inventory](../../doctrine/infrastructure/specifics/release_mechanism.md#inventory).
- **`emit/secrets.py`:** Emit `example.env` with sections like `# database (postgres)\nPOSTGRES_USER=\nPOSTGRES_PASSWORD=`, one section per backing service that introduces env vars.

#### Output of `docex compile`

Stdout: a summary of what was emitted (e.g. `Compiled 4 environments. 12 files written under infra/output/.`). Errors go to stderr. Exit 0 on success, 1 on validation failure, 2 on internal error.

**Success criterion:** Running `docex compile` against `tests/fixtures/sample_project/` produces output under `infra/output/dev/docker-compose.yml`, `infra/output/test/docker-compose.yml`, `infra/output/stage/{docker-compose.yml,playbook.yml,inventory.yml,ansible.cfg}`, and `infra/output/prod/{docker-compose.yml,playbook.yml,inventory.yml,ansible.cfg}` — assuming the sample project is fixed-foundation. Switching `foundation: elastic` and re-running produces `infra/output/{stage,prod}/main.tf` instead.

### Step 8: The `describe` command

`src/docex/describe/` implements `docex describe [<env>] [<format>]`.

Per [docex.md § describe](../../doctrine/infrastructure/docex.md#describe), defaults: `env=prod`, `format=dag`. Formats: `dag` (text-based) and `llm` (JSON).

The describer covers all three [infrastructure tiers](../../doctrine/infrastructure/infrastructure.md#infrastructure-tiers):

1. **Prerequisite** — listed from [shape2.md](../../doctrine/infrastructure/shape2.md) per foundation. These are static facts; bundle the descriptions in the docex image.
2. **Project** — derived deterministically by the compiler from `infra.yml` + foundation. VPC, ECR repo, Route53 zone, ACM cert (elastic); container registry reference (fixed). These come from the compiler's project-tier output.
3. **Environment** — the actual services in the target env, with their compiled names, networks, depends-on edges.

`dag` output is a directed graph in plain text — services as nodes, depends-on edges as arrows, grouped by tier. Use `rich.tree` or a simple ASCII renderer; the exact visual form is a design call but it must be greppable and copy-pasteable.

`llm` output is JSON with the structure:
```json
{
  "env": "prod",
  "foundation": "elastic",
  "tiers": {
    "prerequisite": [...],
    "project": [...],
    "environment": [...]
  },
  "edges": [{"from": "api", "to": "database", "kind": "depends_on"}, ...]
}
```

**Success criterion:** `docex describe prod dag` against the sample project prints a tree showing prerequisite + project + env resources with depends-on edges. `docex describe prod llm` prints valid JSON parseable by `jq`.

### Step 9: The `why` command

`src/docex/why/catalog.py` implements `docex why <resource>`. Per [docex.md § why](../../doctrine/infrastructure/docex.md#why), this explains *why* the doctrine handles each infrastructure resource the way it does.

Mechanism:

1. `doctrine_excerpts/index.yml` maps resource name → markdown file under `doctrine_excerpts/`.
2. `docex why dns` reads the indexed markdown and prints it through `rich.markdown.Markdown`.
3. Unknown resource → print the list of known resources and exit 1.

The catalog of queryable resources for Phase 1 should at minimum include everything in the shape tables in [shape2.md](../../doctrine/infrastructure/shape2.md) — `registrar`, `dns`, `host_machine`, `reverse_proxy`, `cert_manager`, `container_registry`, `service_discovery`, `build_image`, `network`, `core_service`, `backing_service`, `environment_config`, `secrets`, `aws_account`, `vpc`. Plus the special network names (`web`, `internal`).

Each excerpt is a short markdown file (5–20 lines) summarizing the doctrine's reasoning for that resource, with a link back to the authoritative doctrine file. **These are not pulled from doctrine files at runtime** — they are hand-authored summaries baked into the image, so doctrine prose can evolve without the image being rebuilt. Keep them tight and information-dense.

**Success criterion:** `docex why reverse_proxy` prints a coherent paragraph explaining why we use Traefik on fixed and ALB on elastic, with a link to `shape2.md`.

### Step 10: Dockerfile

Single-stage Dockerfile, Python-only (Phase 1 doesn't need docker/tofu/ansible/aws):

```dockerfile
FROM python:3.12-slim@sha256:<digest>

WORKDIR /opt/docex
COPY pyproject.toml ./
COPY src/ ./src/
COPY tables/ /opt/docex/tables/
COPY doctrine_excerpts/ /opt/docex/doctrine_excerpts/
COPY ansible/ /opt/docex/ansible/

RUN pip install --no-cache-dir .

WORKDIR /project
ENTRYPOINT ["docex"]
```

Replace `<digest>` with the actual digest of the current `python:3.12-slim` you're building against — look it up at build time and commit the resulting Dockerfile.

Build with `docker build -t docex:0.1.0 .` from `~/.claude/jean_baudrillard/docex/`.

**Success criterion:** `docker run --rm -v /tmp/sample_project:/project docex:0.1.0 compile` works against a sample project copied to `/tmp/`.

### Step 11: The shim

`bin/docex` is the full shim shipped to every project. Per [design_proposal.md § The Shim](../design_proposal.md#the-shim):

```bash
#!/usr/bin/env bash
set -euo pipefail

# Find project.yml by walking up from PWD
find_project_root() {
  local dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/project.yml" ]]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  echo "error: no project.yml found in $PWD or any parent directory" >&2
  exit 1
}

PROJECT_ROOT="$(find_project_root)"

# Read docex_version (simple grep; avoids requiring yq on host)
DOCEX_VERSION="$(grep -E '^docex_version:' "$PROJECT_ROOT/project.yml" \
  | sed -E 's/^docex_version:[[:space:]]*"?([^"]+)"?[[:space:]]*$/\1/')"

if [[ -z "$DOCEX_VERSION" ]]; then
  echo "error: docex_version not set in $PROJECT_ROOT/project.yml" >&2
  exit 1
fi

# Build mount list — skip mounts whose host source doesn't exist
MOUNTS=(
  -v "$PROJECT_ROOT:/project"
  -v "/var/run/docker.sock:/var/run/docker.sock"
)
[[ -f "$HOME/.docker/config.json" ]] && MOUNTS+=(-v "$HOME/.docker/config.json:/root/.docker/config.json:ro")
[[ -d "$HOME/.aws" ]] && MOUNTS+=(-v "$HOME/.aws:/root/.aws:ro")
[[ -f "$HOME/.gitconfig" ]] && MOUNTS+=(-v "$HOME/.gitconfig:/root/.gitconfig:ro")
[[ -d "$HOME/.ssh" ]] && MOUNTS+=(-v "$HOME/.ssh:/root/.ssh:ro")

exec docker run --rm \
  "${MOUNTS[@]}" \
  -w /project \
  "docex:$DOCEX_VERSION" \
  "$@"
```

Notes:
- The shim ships in `bin/docex` of the `docex/` repo as the canonical version, and is copied into projects by `docex_install.sh` in Step 12.
- Image reference is `docex:$DOCEX_VERSION` for now; once we publish to a registry it becomes `ghcr.io/<org>/docex:$DOCEX_VERSION`.
- Phase 1 doesn't *need* most of these mounts, but the shim is permanent — adding mounts later would require every project to update their shim. Mount everything now, skip what isn't present.

### Step 12: docex install script

Create `~/.claude/jean_baudrillard/docex_install.sh` (or a Python equivalent). This is the install script referenced in [design_proposal.md § The Shim](../design_proposal.md#the-shim). It takes a single argument — the target project directory — and:

1. Verifies `<project>/project.yml` exists (errors out if not — project-structure scaffolding is the responsibility of [inception.md](../../doctrine/practices/inception.md), not this script).
2. Copies `~/.claude/jean_baudrillard/docex/bin/docex` to `<project>/bin/docex` and `chmod +x` it.
3. Reads the currently-shipped version from `~/.claude/jean_baudrillard/docex/pyproject.toml` and upserts a `docex_version: "<version>"` line into `<project>/project.yml`.

Both writes are idempotent — re-running the script is also the supported way to upgrade a project from one `docex` version to another.

Keep this script simple — it is not a docex subcommand and is not bundled in the image. It's a doctrine-side helper, so it lives in the `jean_baudrillard` repo alongside the doctrine.

### Step 13: Test fixtures and integration tests

Create `tests/fixtures/sample_project/` with a realistic but minimal project. A good fixture has:
- `project.yml`: name `sample`, version `0.1.0`, docex_version `0.1.0`
- `infra/infra.yml`: foundation fixed, one core service (`api`, role `web`, port 8080, networks [web, internal], depends_on [database], a resources block, env using `${backing_services.database.url}`), one backing service (`database`, role `relational_db`, engine postgres, version "15", networks [internal], schema_owned_by api)

Write integration tests under `tests/integration/test_compile.py` that:
1. Run the compiler against the fixture in a temp directory.
2. Assert each expected output file exists.
3. Snapshot-test the output content (golden files in `tests/fixtures/sample_project/expected_output/`). Use a simple "compare-with-blessed-file, regenerate on `--regenerate` flag" pattern.
4. Repeat with `foundation: elastic` to confirm stage/prod produce `main.tf`.
5. A test that intentionally breaks each validation rule from [cicl.md § Validation Rules](../../doctrine/infrastructure/cicl.md#validation-rules) and asserts the appropriate error.

Unit tests under `tests/unit/` cover the substitution engine, transfer-table merging, magic-ref resolution, and the resources translation.

Tests must run inside the docex container too (so they're CI-friendly): `docker run --rm -v $PWD:/opt/docex --entrypoint pytest docex:0.1.0 /opt/docex/tests/`.

### Step 14: End-to-end smoke test

The final Phase 1 acceptance gate. Manually:

1. Build the image: `cd ~/.claude/jean_baudrillard/docex && docker build -t docex:0.1.0 .`
2. Stage a throwaway project from the sample fixture: `cp -r ~/.claude/jean_baudrillard/docex/tests/fixtures/sample_project /tmp/smoke && cd /tmp/smoke`.
3. Install docex into it: `bash ~/.claude/jean_baudrillard/docex_install.sh .`. Confirm `./bin/docex` exists and `project.yml` has the right `docex_version`.
4. Run `./bin/docex compile`. Check `infra/output/` exists and contains all expected files.
5. Run `./bin/docex describe prod`. Confirm a sensible DAG.
6. Run `./bin/docex describe prod llm | jq .`. Confirm valid JSON.
7. Run `./bin/docex why reverse_proxy`. Confirm a coherent excerpt.
8. Run `./bin/docex up dev`. Confirm the "Phase 2; not yet implemented" message.
9. Switch the fixture to `foundation: elastic` and re-run `./bin/docex compile`. Confirm `infra/output/stage/main.tf` and `infra/output/prod/main.tf` are produced.

If all nine succeed, Phase 1 is done.

## Things to Avoid

- **Don't implement Phase 2+ commands "partially" while you're in there.** Stubs only. Scope creep here turns a clean Phase 1 release into an indefinite one.
- **Don't optimize prematurely.** The compiler runs on a developer's laptop against a handful of services; readability beats speed.
- **Don't invent transfer-table fields beyond what's specified in [transfer_tables.md](../../doctrine/infrastructure/specifics/transfer_tables.md).** If you find you need something more, surface it as a doctrine question rather than extending the schema silently.
- **Don't write your own YAML library or your own template engine.** PyYAML and Jinja2 are fine.
- **Don't make the shim "smart" about the version mismatch case yet.** Phase 1 only warns. The enforcement story belongs in Phase 3 with the rest of the CI/CD machinery.
- **Don't add a `--verbose` or `--debug` flag system beyond a single global `--debug`** that toggles full Python tracebacks on errors. Logging surface is a future concern.

## What Happens After Phase 1

When Phase 1 ships, the doctrine becomes *authorable* but not yet *runnable*. A developer can write `infra.yml`, run `compile`, and inspect the output — they cannot yet bring up a stack or run tests through `docex`. Phase 2 (`up`, `down`, `build`, `test`, `migrate`) closes that gap and is the natural next implementation document.
