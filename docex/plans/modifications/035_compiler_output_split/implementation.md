# Implementation — Mod 035 — Compiler Output Split + Always-on Four `-web` Networks

## Context for fresh-context implementer

You are executing mod 035. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`cicl.md § Compiler Output`](../../../../doctrine/infrastructure/cicl.md#compiler-output) — new file-tree layout.
- [`projinfra/overview.md`](../../../../doctrine/infrastructure/specifics/projinfra/overview.md) — what project-tier vs side means and why all four `-web` networks emit on every side.
- [`projinfra/fixed_reverse_proxy.md`](../../../../doctrine/infrastructure/specifics/projinfra/fixed_reverse_proxy.md) — eventually the per-project traefik joins these networks (mod 036).

## Operator decisions binding on this implementation

- **Minimal project-tier compose YAML.** Networks block + `docex-ingress` external reference. No `services:`.
- **Env compose unchanged.** Do not touch `infra/output/<env>/docker-compose.yml` emission in this mod. The `external: true` flip is mod 036.
- **`bootstrap.py` path fix** lands in this mod.

## Step-by-step plan

### Step 1 — Add `emit_project_compose` helper

Edit `src/docex/emit/compose.py`. Add a new top-level function:

```python
def emit_project_compose(*, project: str, out_path: Path) -> None:
    """Emit a project-tier compose file that declares the four
    ${project}-${env}-web external networks plus the docex-ingress
    preinfra network reference. No services in mod 035 — the
    per-project traefik joins these networks in mod 036.

    Both the development and production sides emit this same shape;
    the only side-specific differences live elsewhere (HCL on elastic
    production, ansible artifacts when fixed prod is remote — mod 036).
    """
    data: dict[str, Any] = {
        "networks": {
            f"{project}-dev-web":   {"name": f"{project}-dev-web"},
            f"{project}-test-web":  {"name": f"{project}-test-web"},
            f"{project}-stage-web": {"name": f"{project}-stage-web"},
            f"{project}-prod-web":  {"name": f"{project}-prod-web"},
            "docex-ingress":        {"external": True},
        }
    }
    out_path.write_text(yaml.safe_dump(data, sort_keys=False))
```

Use whatever yaml import is already at module top. Don't add the logging anchor — there are no services to log.

### Step 2 — Update `run_compile` to emit project-tier output by side

Edit `src/docex/cicl/compile.py:run_compile` (around lines 791–855). Replace the existing project-tier block:

```python
if ctx.infra.foundation == "elastic":
    project_dir = output_root / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    emit_hcl_project(
        ...,
        out_path=project_dir / "main.tf",
    )
    files_written += 1
```

with the new side-split block:

```python
# Mod 035: project-tier output is split by side. Both sides emit on
# every project. The development side is always fixed-style (compose);
# the production side switches by foundation.
dev_project_dir = output_root / "project" / "development"
dev_project_dir.mkdir(parents=True, exist_ok=True)
emit_project_compose(
    project=ctx.project.name,
    out_path=dev_project_dir / "docker-compose.yml",
)
files_written += 1

prod_project_dir = output_root / "project" / "production"
prod_project_dir.mkdir(parents=True, exist_ok=True)
if ctx.infra.foundation == "fixed":
    emit_project_compose(
        project=ctx.project.name,
        out_path=prod_project_dir / "docker-compose.yml",
    )
    files_written += 1
else:  # elastic
    emit_hcl_project(
        ...same kwargs as before...,
        out_path=prod_project_dir / "main.tf",
    )
    files_written += 1
```

Don't forget to import `emit_project_compose` from `docex.emit.compose` alongside `emit_compose`.

### Step 3 — Update `pipeline/bootstrap.py` path

`src/docex/pipeline/bootstrap.py` lines ~111–112 currently:

```python
project_dir = ctx.project_root / "infra" / "output" / "project"
main_tf = project_dir / "main.tf"
```

Update to:

```python
project_dir = ctx.project_root / "infra" / "output" / "project" / "production"
main_tf = project_dir / "main.tf"
```

The function name `_print_delegation_instructions(project_dir, ...)` and the downstream `tofu_*(project_dir)` calls keep working — `project_dir` is now the production-side directory, which is correct because `bootstrap` (now `projinfra up production` per mod 034) targets the production side.

Update any docstrings in the file that reference the old `infra/output/project/main.tf` path.

### Step 4 — Sweep for old project-tier path references

```bash
cd ~/.claude/jean_baudrillard/docex
grep -rn '"output" / "project"\|/project/main\.tf\|infra/output/project/main' src/ tests/
```

Every hit either belongs to the bootstrap update (Step 3) or needs migration to the new `production/` path.

### Step 5 — Update plans/core/compiler.md output-layout section

`docex/plans/core/compiler.md` lines ~129–145 show the old layout in a code block:

```
infra/output/
├── project/                       elastic only — emitted by emit/hcl.py::emit_hcl_project
│   └── main.tf                    state backend ref, VPC, ...
├── dev/...
```

Replace with the new layout from [`cicl.md § Compiler Output`](../../../../doctrine/infrastructure/cicl.md#compiler-output):

```
infra/output/
├── project/
│   ├── development/
│   │   └── docker-compose.yml    # always — four -web networks + docex-ingress
│   └── production/
│       ├── docker-compose.yml    # fixed-foundation only
│       └── main.tf               # elastic-foundation only
├── dev/...
```

Mention that mod 035 emits networks only; per-project traefik arrives in mod 036. Mention that ansible artifacts (`playbook.yml`, `inventory.yml`, `ansible.cfg`) at project tier come later (mod 036's `fixed + remote prod host` path).

### Step 6 — Tests

#### `tests/integration/test_compile.py`

Find every assertion on the project-tier output. Search:

```bash
grep -n 'project/main\.tf\|output.*project' tests/integration/test_compile.py
```

For each hit:
- Move elastic-project assertion of `infra/output/project/main.tf` → `infra/output/project/production/main.tf`.

Add new assertions:

- `test_project_tier_development_compose_emitted_for_every_project`: every project (fixed and elastic) gets `infra/output/project/development/docker-compose.yml`.
- `test_project_tier_production_compose_emitted_for_fixed_only`: fixed project produces `infra/output/project/production/docker-compose.yml`; elastic project does NOT.
- `test_project_tier_production_main_tf_emitted_for_elastic_only`: elastic project produces `infra/output/project/production/main.tf`; fixed project does NOT.
- `test_project_tier_compose_declares_four_web_networks`: read the dev-side compose; assert each of `${project}-{dev,test,stage,prod}-web` appears as a top-level network name; assert `docex-ingress` is declared with `external: true`; assert no `services:` key.

Use the existing `_write_sample_project` / `_write_underscore_project` helpers; no new sample fixtures needed.

#### `tests/unit/test_pipeline_bootstrap.py`

The bootstrap test surface probably stubs out file existence checks. If any pin the old `project/main.tf` path, flip to `project/production/main.tf`.

### Step 7 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green.

### Step 8 — Sanity sweep

```bash
cd ~/.claude/jean_baudrillard/docex

# No old project path remains in source
grep -rn '"output" / "project"\|/project/main\.tf\|infra/output/project/main' src/

# New paths in use
grep -rn 'project/development\|project/production' src/ tests/
```

First sweep: zero hits. Second: legitimate hits in the new compile.py code and the new tests.

## Out of scope

- **No per-project traefik emission** — mod 036.
- **No env-tier compose changes** — mod 036.
- **No `projinfra up/down` runtime behavior changes** — mod 036.
- **No ansible artifacts at project tier** — mod 036 (`fixed + remote prod host`).
- **No content changes to the elastic `main.tf` body** — only the file path moves; broader content emission lives in mods 037–039.
- **No `test_projects/{fixed,elastic}/` edits.**
- **No env-tier output path changes** (`infra/output/<env>/...` stays where it is).

## Done criteria

- [ ] `emit_project_compose` added in `src/docex/emit/compose.py`.
- [ ] `run_compile` emits both sides' project-tier output; elastic `main.tf` moved to `production/`.
- [ ] `pipeline/bootstrap.py` reads from `infra/output/project/production/main.tf`.
- [ ] `plans/core/compiler.md` output-layout section reflects new structure.
- [ ] Test coverage: dev-side compose for every project, production-side compose only for fixed, production-side main.tf only for elastic, network declarations match doctrine spec.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] No old project path in `src/`; new paths appear only in the expected sites.
- [ ] No env-tier compose changes; no `test_projects/{fixed,elastic}/` edits.

Working tree dirty when finished. Do not commit.
