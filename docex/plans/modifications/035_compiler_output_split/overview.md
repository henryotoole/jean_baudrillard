# Mod 035 — Compiler Output Split + Always-on Four `-web` Networks

Sixth mod of the [doctrine-shape-and-tier campaign](../../campaigns/shape_overhaul_mod_list.md). Stages the project-tier output layout for the projinfra emission work that follows (mods 036–039).

## The Doctrine Change

From [`cicl.md § Compiler Output`](../../../../doctrine/infrastructure/cicl.md#compiler-output) and [`projinfra/overview.md`](../../../../doctrine/infrastructure/specifics/projinfra/overview.md):

**New project-tier output layout** — split by side:

```
infra/output/project/
    development/
        docker-compose.yml      # always emitted (dev side is always fixed-style)
    production/
        docker-compose.yml      # fixed-foundation only
        playbook.yml            # fixed + remote prod host (mod 036)
        inventory.yml           # fixed + remote prod host (mod 036)
        ansible.cfg             # fixed + remote prod host (mod 036)
        main.tf                 # elastic-foundation only
```

**Both sides emit on every project** regardless of foundation. An elastic project still emits `infra/output/project/development/docker-compose.yml` for the operator's dev machine; only the `production/` artifact differs (HCL instead of compose).

**All four `-web` networks emit on every side** regardless of which envs that side hosts (per [`projinfra/overview.md § Why all four -web networks live on every side`](../../../../doctrine/infrastructure/specifics/projinfra/overview.md#why-all-four--web-networks-live-on-every-side)):

```yaml
networks:
  ${project}-dev-web:    { name: ${project}-dev-web }
  ${project}-test-web:   { name: ${project}-test-web }
  ${project}-stage-web:  { name: ${project}-stage-web }
  ${project}-prod-web:   { name: ${project}-prod-web }
  docex-ingress:         { external: true }   # owned by preinfra
```

## Scope of mod 035 — emission only, no behavior cutover

This mod is **pure path layout + emission**. The compiler emits the new project-tier compose files (with networks but no traefik), and moves the existing elastic `project/main.tf` to `project/production/main.tf`. Env-tier compose files are **unchanged** — they still self-declare their own `-web` network. Mod 036 will both add the per-project traefik to the new project-tier compose files AND flip env-tier compose to `external: true` web-network references.

This staging keeps mod 035 free of any runtime behavior changes — `projinfra` is still a stub from mod 034, no one's actually applying the new project compose, and env stacks keep working exactly as they do today.

## Concrete file surface

### Compiler — `src/docex/cicl/compile.py:run_compile`

The current code (lines 791–855):

```python
if ctx.infra.foundation == "elastic":
    project_dir = output_root / "project"
    ...
    emit_hcl_project(..., out_path=project_dir / "main.tf")
```

becomes:

```python
# Project-tier development side: always emit a compose file with the
# four -web external networks. Compose-only because dev side is always
# fixed-style per shape2.md. Mod 035 emits the networks; mod 036 adds
# the project traefik.
dev_project_dir = output_root / "project" / "development"
dev_project_dir.mkdir(parents=True, exist_ok=True)
emit_project_compose(
    project=ctx.project.name,
    out_path=dev_project_dir / "docker-compose.yml",
)
files_written += 1

# Project-tier production side: shape depends on foundation.
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
        ...,
        out_path=prod_project_dir / "main.tf",   # NEW PATH
    )
    files_written += 1
```

### New emitter — `src/docex/emit/compose.py:emit_project_compose`

A new function that writes a small compose file declaring the four `-web` external networks plus the `docex-ingress` reference. No services, no version key (compose's `version:` field is deprecated). The function takes `project` and `out_path`; produces a self-contained compose file.

Suggested shape (illustrative):

```python
def emit_project_compose(*, project: str, out_path: Path) -> None:
    """Emit a project-tier compose file declaring the four ${project}-${env}-web
    external networks plus the docex-ingress preinfra network reference. No
    services in mod 035; mod 036 adds the per-project traefik."""
    data = {
        "networks": {
            short: {"name": f"{project}-{env}-web"}
            for env, short in (
                ("dev", f"{project}-dev-web"),
                ("test", f"{project}-test-web"),
                ("stage", f"{project}-stage-web"),
                ("prod", f"{project}-prod-web"),
            )
        }
    }
    # docex-ingress is preinfra-owned, referenced via external: true.
    data["networks"]["docex-ingress"] = {"external": True}
    out_path.write_text(yaml.safe_dump(data, sort_keys=False))
```

The implementer should reuse whatever YAML-dumping helper `emit_compose` uses (with logging anchors, etc.); this snippet is illustrative.

### Updated path — `src/docex/pipeline/bootstrap.py`

`run_bootstrap` reads `infra/output/project/main.tf`. After mod 035 the file lives at `infra/output/project/production/main.tf`. Update the path constant on line 111–112.

The bootstrap logic itself is unchanged — only the path moves.

### Env-tier compose — UNCHANGED in mod 035

Env compose files (`infra/output/<env>/docker-compose.yml`) keep self-declaring their own `-web` network in mod 035. Mod 036 flips them to `external: true` referencing the projinfra-owned networks. The reason for the deferral:

- Mod 035's projinfra compose is **emitted but not yet applied** — `projinfra up <side>` is still a stub for fixed projects (per mod 034). So nothing actually creates the projinfra `-web` networks at runtime.
- If env compose declared `external: true` references now, env stacks would fail to come up (`network not found`).
- Mod 036 lands the projinfra-up wiring AND flips env compose in one coordinated change.

In the meantime, the projinfra compose file declares the same network names env compose owns. This is fine at compile time (no collision) and at runtime as long as projinfra isn't applied (still true in mod 035).

## Ramifications

### File-tree shape changes

Operators running `docex compile` will see:
- `infra/output/project/main.tf` → moved to `infra/output/project/production/main.tf` (elastic projects).
- New file: `infra/output/project/development/docker-compose.yml` (every project).
- New file: `infra/output/project/production/docker-compose.yml` (fixed projects).

The `git diff` on test-projects would be substantial if we recompiled — but per campaign-wide deferral, we don't.

### `pipeline/bootstrap.py` continuity

`bootstrap` (now `projinfra up production` on elastic per mod 034) reads `infra/output/project/<something>/main.tf`. Path moves to the new location. Anything downstream that hardcodes the old path needs updating.

Quick search:

```bash
grep -rn 'infra/output/project/main\.tf\|"project"\s*/\s*"main\.tf"\|/ "project" / "main' src/
```

### Tests

- `tests/integration/test_compile.py` — likely has assertions on `infra/output/project/main.tf` existence (elastic case) and absence (fixed case). Move to the new path.
- New assertions: `infra/output/project/development/docker-compose.yml` exists for every project; `infra/output/project/production/docker-compose.yml` exists for fixed; `infra/output/project/production/main.tf` exists for elastic.
- Content assertions on the new project-tier compose: contains the four expected `-web` network names; contains `docex-ingress` external reference; no `services:` key.

### Doctrine artifact: `tables/README.md`, `plans/core/compiler.md`

`plans/core/compiler.md` has an "Output layout" section (lines ~129–145) showing the old shape:

```
infra/output/
├── project/                       elastic only
│   └── main.tf
├── dev/...
```

Update to the new layout from [`cicl.md § Compiler Output`](../../../../doctrine/infrastructure/cicl.md#compiler-output).

## Operator Decisions

1. **Project-tier compose YAML** — minimal: networks block only, no `services:`, no logging anchor.
2. **Env compose unchanged** in mod 035; the `external: true` flip lands with mod 036 alongside the per-project traefik and `projinfra up <side>` real behavior.
3. **`bootstrap.py` path fix** lands in mod 035 since this mod owns the file move.

## What This Mod Is NOT

- **No per-project traefik emission** — mod 036.
- **No `projinfra up/down` real behavior on fixed** — mod 036 wires it.
- **No env compose changes** — mod 036 flips web-network references to `external: true`.
- **No ansible artifacts at project tier** — mod 036's responsibility for "fixed + remote prod host" path.
- **No `test_projects/{fixed,elastic}/` edits.**
- **No elastic `project/production/main.tf` content changes** — only the file path moves; content emission is unchanged in mod 035, grown in mods 037–039.

Quiet structural mod — relocate one file, add two new files, update one path reference, no runtime behavior changes.
