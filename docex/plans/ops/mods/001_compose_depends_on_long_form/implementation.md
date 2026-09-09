# Mod 001 — Implementation Steps

Self-contained instructions for executing this mod. Read `overview.md` in the same folder for the design rationale.

## Context for a fresh agent

You are working in the `docex` project at `~/.claude/jean_baudrillard/docex/`. `docex` is the executor of the doctrine; full background is in `plans/core/masterplan.md` and `plans/core/docex_process.md`. The doctrine itself lives at `~/.claude/jean_baudrillard/doctrine/`.

**The bug.** The compose emitter (`src/docex/emit/compose.py`) writes `depends_on` in compose's *short-form* (a flat list). Short-form only makes compose wait for the target to *start*, not to be *healthy*. The postgres engine declares a `pg_isready` healthcheck, so when `docex up dev` runs `compose exec ./migrate.sh` immediately after `compose up --detach`, it hits postgres before it's accepting connections, and the migration fails with `dial tcp 172.x.0.2:5432: connect: connection refused`.

**The fix.** Convert `depends_on` to compose's *long-form* (a map). For each dependency, emit `condition: service_healthy` if the target service has a `healthcheck:` block in the emitted compose; otherwise emit `condition: service_started` (semantically equivalent to the current short-form, just expressed in long-form). The fix is purely in the compose emitter; elastic/HCL output is untouched (HCL strips `depends_on` via `src/docex/emit/hcl.py:206`).

**Bundled cleanup.** Two integration tests (`tests/integration/test_up_down_real.py` and `tests/integration/test_migrate_real.py`) still reference a fixture backing service named `"database"`, but the fixture (`tests/fixtures/sample_project/infra/infra.yml`) renamed it to `"db"`. Rename the test-side references in this same mod.

## Steps

### 1. Compose emitter — emit `depends_on` in long-form

File: `src/docex/emit/compose.py`

The current block at lines 169–182 translates `depends_on` from simple names to global names but keeps the list shape:

```python
simple_to_global = {
    n: s.global_name for n, s in compiled.services.items()
}
for name in sorted(compiled.services):
    svc = compiled.services[name]
    block = _service_block(svc)
    if isinstance(block.get("depends_on"), list):
        block["depends_on"] = [
            simple_to_global.get(d, d) for d in block["depends_on"]
        ]
```

Change this so:
- `block["depends_on"]` becomes a `dict` keyed by global name.
- Each value is `{"condition": "service_healthy"}` when the target service's emitted block has a `healthcheck` key, else `{"condition": "service_started"}`.

The target service's healthcheck status must be determined from the *emitted compose blocks*, not from the transfer-table source — by the time `depends_on` is being rewritten, the per-service blocks for the entire env have been built. Build the lookup the same way `simple_to_global` is built: from `compiled.services`, by inspecting each service's emitted block. The simplest structure:

1. After all `_service_block(svc)` calls have populated a `services` dict, do a second pass that rewrites every service's `depends_on`. (Equivalently: build `services` in one loop, then do the depends_on rewrite in a second loop.)
2. In the rewrite pass, look up the target service's block by its global name in `services` and check `"healthcheck" in target_block`.

Preserve existing behavior:
- If a service has no `depends_on`, do nothing.
- If `depends_on` is already a dict (defensive — shouldn't happen with current `_service_block`), leave it alone.
- Continue mapping simple names → global names; the dict key must be the global name.

### 2. Unit tests — cover both condition branches

File: `tests/unit/test_compose_emitter.py`

Add two new test functions. Use the existing helpers (`_copy_fixture`, `_compose_services`, `_find_core_service_block`) and the existing fixture at `tests/fixtures/sample_project`. The fixture's `infra.yml` has core service `api` depending on backing service `db` (with `engine: postgres`, so the emitted compose for `db` has a healthcheck). That's enough to cover the `service_healthy` branch.

For the `service_started` branch, you'll need a service whose dependency target has no healthcheck. Two options — pick whichever feels cleaner:
- **(a)** Add a second fixture, or extend `sample_project`, with a backing service that has no healthcheck (e.g. a `reverse_proxy` role engine, if one exists with no healthcheck). Check `tables/roles/` to see what's available without a healthcheck.
- **(b)** Build the compose input synthetically inside the test by constructing a `CompiledEnv` directly, bypassing the fixture. Look at how `tests/unit/test_compose_emitter.py` currently constructs inputs; if it always uses `run_compile`, follow the same pattern for consistency.

Recommended test names and shapes:

```python
def test_depends_on_uses_service_healthy_when_target_has_healthcheck(tmp_path: Path):
    # Compile sample_project; api depends on db (postgres → has healthcheck).
    # Assert api's depends_on is a dict, keyed by db's global name,
    # with {"condition": "service_healthy"}.

def test_depends_on_uses_service_started_when_target_has_no_healthcheck(tmp_path: Path):
    # Construct or use a fixture where the dep target has no healthcheck.
    # Assert the emitted condition is "service_started".
```

Both tests must check the `dev` env's compose; the rewrite applies uniformly across envs, so one env is sufficient.

### 3. Integration test fixture rename — `database` → `db`

Replace stale `"database"` references that should have been updated when the sample fixture renamed its backing service. Exact edits:

**`tests/integration/test_up_down_real.py`**
- Line 40: `s.endswith("database")` → `s.endswith("db")`

**`tests/integration/test_migrate_real.py`**
- Line 28 comment: "We exec into the database container." → "We exec into the db container."
- Line 30 comment: "Find database service's project-scoped global name." → "Find db service's project-scoped global name."
- Line 39: `s.strip().endswith("database")` → `s.strip().endswith("db")`
- Line 40: default value `"database"` → `"db"`
- Lines 42–44 comment: replace with "The default db name is the backing-service name \"db\" (from the engine table's ${name} substitution), not the project name."
- Line 51: `"psql", "-U", "sample", "-d", "database"` → `"psql", "-U", "sample", "-d", "db"`

**Fixture env cleanup.** While you're in this area, `tests/fixtures/sample_project/infra/secrets/dev.env` has two stale entries that referenced the old name and aren't read by anything compiled today:

```
POSTGRES_DB=sample
POSTGRES_HOST=sample_dev_database
```

The postgres engine's transfer-table entry sets `POSTGRES_DB` from the service name at compile time, and nothing reads `POSTGRES_HOST` from `.env` (host is constructed from the engine's `provides.host` part). Delete both lines. Leave `POSTGRES_USER=sample` and `POSTGRES_PASSWORD=sample-dev-password` — they ARE referenced by the engine via `$[POSTGRES_USER]` / `$[POSTGRES_PASSWORD]`.

### 4. Doctrine — add the new invariant

File: `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics/transfer_tables.md`

Inside `## Foundation Invariants`, add a new third subsection between the existing `### Per-container (fixed)` and `### Per-compose-file (fixed)` (or after both — pick the position where it reads best in context). Title: `### Depends-on emission (fixed)`.

The body should state, in doctrine voice:

- Compose `depends_on` is always emitted in long-form (a map), never short-form.
- For each dependency, `condition` is `service_healthy` when the target service's emitted compose block contains a `healthcheck:`, otherwise `service_started`.
- Why: short-form only waits for the target container to start. Backing services like postgres take measurable time to become reachable after starting, and a dependent service (or `compose exec` from `docex up`) that connects too early hits a refused TCP socket. The healthcheck is already declared by the engine; using it as the wait condition is the deterministic translation.

Show the emitted shape, mirroring the style of the sibling subsections:

```yml
depends_on:
  ${global_service_name_of_target}:
    condition: service_healthy   # or service_started
```

Keep the prose tight — these subsections are reference material, not narrative. One short paragraph plus the YAML block.

### 5. Validation

After all edits:

1. From `~/.claude/jean_baudrillard/docex`:
   ```
   python3 -m pytest tests/unit/ -v
   ```
   All previously-passing unit tests must still pass (currently 163). New tests from step 2 must pass.

2. Re-compile both test projects and confirm the depends_on shape:
   ```
   cd test_projects/fixed && ./bin/docex compile
   grep -A 3 "depends_on" infra/output/dev/docker-compose.yml
   ```
   Expected: long-form map with `condition: service_healthy` against the `-db` key.

3. Run `docex up dev` against the fixed test project — migrations must succeed on a clean run:
   ```
   cd test_projects/fixed
   ./bin/docex down dev  # in case stale state
   ./bin/docex up dev
   ./bin/docex down dev
   ```
   No `connection refused` from `migrate.sh`.

4. Run `docex test` against the fixed test project:
   ```
   cd test_projects/fixed && ./bin/docex test
   ```
   Exit 0.

5. Repeat steps 3–4 for `test_projects/elastic` (its dev/test envs compile to compose just like fixed).

6. Run integration tests with real docker:
   ```
   cd ~/.claude/jean_baudrillard/docex
   python3 -m pytest -m integration
   ```
   `test_up_down_real.py::test_up_then_down_dev` and `test_migrate_real.py::test_migrate_dev_creates_health_table` must now pass. All previously-passing integration tests must still pass.

## Out of scope

- No changes to the HCL emitter (`src/docex/emit/hcl.py`).
- No changes to transfer tables (`tables/`).
- No changes to `docex` core planning docs (`plans/core/*`) per `modifications.md` step 3.1.
- No contract edits — this mod doesn't touch any provider service boundary.
- No version bump in `pyproject.toml` / `src/docex/__init__.py`. Cutting happens later per `docex_process.md § Cutting a version`.
- The remaining PRE_CUT_CHECKLIST sections (real DNS, registry, AWS) are blocked on infra, not this mod.
