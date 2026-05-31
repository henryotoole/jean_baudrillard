# Mod 004 — Implementation Steps

Self-contained instructions for executing this mod. Read `overview.md` in the same folder for the design rationale.

## Context for a fresh agent

You are working in the `docex` project at `~/.claude/jean_baudrillard/docex/`. Two small changes only — no doctrine prose, no new tests.

1. `test_projects/fixed/teardown.sh` — stray-resource filter only matches the underscore form of the project name (`docex_smoke_fixed`), but running containers/networks/volumes use the hyphen form (`docex-smoke-fixed-…`). Loop over both forms.
2. `src/docex/emit/ansible.py` — `_image_for` is dead after mod 003's switch to `docker compose run`. Delete the function, its import dependency, and its Jinja registration.

## Steps

### 1. teardown.sh — accept both name forms

File: `~/.claude/jean_baudrillard/docex/test_projects/fixed/teardown.sh`

Find the `PROJECT_NAME` declaration (around line 17):

```bash
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="docex_smoke_fixed"
REGISTRY_HOST="registry.luxrnd.tech"
```

Insert a hyphen-form variable immediately after `PROJECT_NAME`:

```bash
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="docex_smoke_fixed"
# Hyphenated form. Doctrine name-translation rules (transfer_tables.md
# § naming) produce hyphenated container/network/volume names from
# underscore project names; teardown's `docker ... --filter name=…`
# substring matching needs both forms to find every running resource.
PROJECT_NAME_HYPHEN="${PROJECT_NAME//_/-}"
REGISTRY_HOST="registry.luxrnd.tech"
```

Then find step 2 (around lines 32–44):

```bash
# -- 2. Stray containers/networks/volumes by name prefix ------------------
# WHY: compose-named resources should be caught above, but a partial run
# can leave artifacts that compose's project filter no longer sees.
echo "-- stray docker resources by name prefix"
for container in $(docker ps -aq --filter "name=${PROJECT_NAME}" 2>/dev/null || true); do
  docker rm -f "$container" >/dev/null || true
done
for network in $(docker network ls -q --filter "name=${PROJECT_NAME}" 2>/dev/null || true); do
  docker network rm "$network" >/dev/null 2>&1 || true
done
for volume in $(docker volume ls -q --filter "name=${PROJECT_NAME}" 2>/dev/null || true); do
  docker volume rm "$volume" >/dev/null 2>&1 || true
done
```

Replace with:

```bash
# -- 2. Stray containers/networks/volumes by name prefix ------------------
# WHY: compose-named resources should be caught above, but a partial run
# can leave artifacts that compose's project filter no longer sees. We
# loop over both name forms because docex's name-translation produces
# hyphenated runtime names (`docex-smoke-fixed-…`) from the underscore
# project name (`docex_smoke_fixed`), and `--filter name=` is substring
# match — the underscore form never appears in hyphenated runtime names.
echo "-- stray docker resources by name prefix"
for pattern in "$PROJECT_NAME" "$PROJECT_NAME_HYPHEN"; do
  for container in $(docker ps -aq --filter "name=${pattern}" 2>/dev/null || true); do
    docker rm -f "$container" >/dev/null 2>&1 || true
  done
  for network in $(docker network ls -q --filter "name=${pattern}" 2>/dev/null || true); do
    docker network rm "$network" >/dev/null 2>&1 || true
  done
  for volume in $(docker volume ls -q --filter "name=${pattern}" 2>/dev/null || true); do
    docker volume rm "$volume" >/dev/null 2>&1 || true
  done
done
```

(Note: also harmonized the first `docker rm -f` redirect from `>/dev/null` to `>/dev/null 2>&1` to match the network/volume lines — minor cleanliness, makes the loop body uniform.)

Leave steps 1, 3, 4, and 5 unchanged.

### 2. Drop `_image_for` from `src/docex/emit/ansible.py`

File: `~/.claude/jean_baudrillard/docex/src/docex/emit/ansible.py`

Current state (relevant lines):

```python
from docex.cicl.compile import CompiledEnv, CompiledService


_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _image_for(svc: CompiledService) -> str:
    img = svc.body.get("image")
    if isinstance(img, str):
        return img
    return f"<image-for-{svc.name}>"


def emit_ansible(compiled: CompiledEnv, out_dir: Path) -> None:
    ...
    playbook_tpl = env.get_template("playbook.yml.j2")
    (out_dir / "playbook.yml").write_text(playbook_tpl.render(
        project=compiled.project,
        project_version=compiled.project_version,
        env=compiled.env,
        core_services_with_schema=core_with_schema,
        image_for=_image_for,
    ))
```

Make three deletions:

1. **Trim the import** — change `from docex.cicl.compile import CompiledEnv, CompiledService` to `from docex.cicl.compile import CompiledEnv` (CompiledService was only referenced by `_image_for`).
2. **Delete the function** — remove the entire `_image_for(svc: CompiledService) -> str:` definition including its body (5 lines).
3. **Delete the kwarg** — remove the line `image_for=_image_for,` from the `playbook_tpl.render(...)` call.

After the changes, the file should be ~12 lines shorter. The remaining `emit_ansible` function still renders all three templates correctly; `_image_for` was unreferenced by any live template after mod 003.

### 3. Validation

1. From `~/.claude/jean_baudrillard/docex`:
   ```
   python3 -m pytest tests/unit/ -v
   ```
   Expected: 170 passed (same as before mod 004 — no test counts change).

2. Re-compile `test_projects/fixed` and confirm output is byte-identical to pre-mod-004 (after the mod 003 follow-up's recompile):
   ```
   cd test_projects/fixed && ./bin/docex compile
   git status --short infra/output/
   ```
   Expected: no diff to infra/output/ in the test project's git status — the dead helper was never referenced by the templates.

3. The teardown.sh change has no automated test. Smoke-test by hand if desired:
   ```
   cd test_projects/fixed
   ./bin/docex up dev   # cheap; uses local network only
   bash teardown.sh
   bash verify_clean.sh
   ```
   Expected: `verify_clean: clean.` Don't burn a full stage/prod release just for this — the underlying bug is well-understood and the fix is mechanical.

## Out of scope

- No HCL emitter changes (`src/docex/emit/hcl.py`).
- No transfer table changes (`tables/`).
- No `plans/core/*` changes (per `modifications.md` step 3.1).
- No version bumps (`pyproject.toml`, `__init__.py`, `CHANGELOG.md`) — handled by the design context post-implementation.
- No changes to `test_projects/elastic/teardown.sh` — it already handles the hyphen translation correctly.
- No changes to release-ordering (out of scope as noted in mod 003).
