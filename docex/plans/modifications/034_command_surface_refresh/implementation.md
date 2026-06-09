# Implementation — Mod 034 — Command Surface Refresh

## Context for fresh-context implementer

You are executing mod 034 of a 16-mod docex campaign. Read [`overview.md`](./overview.md) first.

Invoke the `docex-edit` skill via Skill.

Authoritative doctrine reading:
- [`docex.md`](../../../../doctrine/infrastructure/docex.md) — the full command surface (current spec).
- [`docex.md § preinfra`](../../../../doctrine/infrastructure/docex.md#preinfra), [`§ projinfra`](../../../../doctrine/infrastructure/docex.md#projinfra), [`§ envinfra`](../../../../doctrine/infrastructure/docex.md#envinfra) — the new commands' contracts.

## Operator decisions binding on this implementation

Per [`overview.md § Operator Decisions`](./overview.md#operator-decisions):

- Phase categorization → dropped, replaced with purpose grouping.
- `envinfra` refuses `stage`/`prod`.
- `preinfra` stub returns 0 with notice.
- `projinfra` mostly stubs; only `projinfra up production` on elastic runs the existing `run_bootstrap`.
- No `bin/docex` shim changes.

## Step-by-step plan

### Step 1 — Remove old commands and phase categorization from the dispatcher

Edit `src/docex/__main__.py`:

1. **Delete `_cmd_bootstrap`** function entirely (currently around line 385). The body's logic moves to `_cmd_projinfra`'s elastic branch (Step 3).
2. **Delete `_cmd_up` and `_cmd_down`** functions. The CLI surface goes away; the internal `run_up`/`run_down` keep their names and signatures.
3. **Delete `_PHASE1_COMMANDS` through `_PHASE5_COMMANDS`** constants and the `_phase_of` helper. They're only consumed by `_format_usage`, which is also being rewritten.
4. **Drop `bootstrap`, `up`, `down`** from `_HELP_TEXT` (no longer commands).
5. **Drop `bootstrap`, `up`, `down`** from `_build_handler_table` return dict.

### Step 2 — Add the new commands' help text

Add to `_HELP_TEXT`:

```python
"preinfra": "Check prerequisite infrastructure for a side (development | production).",
"projinfra": "Bring up or tear down project-tier infrastructure for a side.",
"envinfra":  "Bring up or tear down a local dev or test environment.",
```

The exact wording can mirror the doctrine `docex.md` short-table phrasing.

### Step 3 — Add the three new handlers

Add to `src/docex/__main__.py`:

#### `_cmd_envinfra(args)`

```python
def _cmd_envinfra(args: list[str]) -> int:
    """``docex envinfra <direction> <env>`` — bring up or tear down a
    local dev / test environment. Dev/test only; stage/prod go via
    `release`."""
    parser = argparse.ArgumentParser(prog="docex envinfra", add_help=True)
    parser.add_argument("direction", choices=["up", "down"],
                        help="up | down")
    parser.add_argument("env", choices=["dev", "test"],
                        help="environment (dev or test)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context

    ctx = load_project_context(Path(os.getcwd()))
    docker = _require_docker()

    if ns.direction == "up":
        from docex.orchestrate.up import run_up
        return run_up(ctx, docker, env=ns.env)
    else:
        from docex.orchestrate.down import run_down
        return run_down(ctx, docker, env=ns.env)
```

`stage`/`prod` are intentionally absent from the `env` choices — argparse will reject them with a clear error.

#### `_cmd_preinfra(args)`

```python
def _cmd_preinfra(args: list[str]) -> int:
    """``docex preinfra <side>`` — check prerequisite infrastructure
    for the given side. STUB in mod 034 — real checks land in mod 042."""
    parser = argparse.ArgumentParser(prog="docex preinfra", add_help=True)
    parser.add_argument("side", choices=["development", "production"],
                        help="side to check (development or production)")
    ns = parser.parse_args(args)

    print(f"preinfra check (stub): {ns.side} side — "
          f"real checks land in mod 042. Returning success.")
    return 0
```

#### `_cmd_projinfra(args)`

```python
def _cmd_projinfra(args: list[str]) -> int:
    """``docex projinfra <direction> <side>`` — bring up or tear down
    project-tier infrastructure for a side. Mostly STUB in mod 034.
    The only real behavior is `projinfra up production` on elastic
    projects, which runs the existing state-backend setup (formerly
    the `bootstrap` command). Mods 036 (fixed) and 037-039 (elastic)
    flesh out the rest."""
    parser = argparse.ArgumentParser(prog="docex projinfra", add_help=True)
    parser.add_argument("direction", choices=["up", "down"],
                        help="up | down")
    parser.add_argument("side", choices=["development", "production"],
                        help="side (development or production)")
    ns = parser.parse_args(args)

    from docex.context import load_project_context

    ctx = load_project_context(Path(os.getcwd()))

    # Elastic + up + production: run the existing state-backend setup.
    if (ctx.infra.foundation == "elastic"
            and ns.direction == "up"
            and ns.side == "production"):
        from docex.pipeline.bootstrap import run_bootstrap
        aws = _make_aws_client()
        return run_bootstrap(ctx, aws)

    print(f"projinfra {ns.direction} {ns.side} (stub): "
          f"real behavior lands in mod 036 (fixed) or mods 037-039 "
          f"(elastic). Returning success.")
    return 0
```

### Step 4 — Rewrite `_format_usage` with purpose grouping

Replace the existing `_format_usage` body. Group commands by doctrine-table-aligned purpose:

```python
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Introspection", ("compile", "describe", "why", "roles", "role")),
    ("Infrastructure", ("preinfra", "projinfra", "envinfra")),
    ("Development", ("build", "test", "migrate")),
    ("Pipeline", ("check", "merge", "containerize", "release",
                  "stagetest", "rollback")),
)
```

`_format_usage` iterates `_GROUPS`, prints each group's heading and commands with help text. The implementation pattern from the current `_format_usage` (the `_group(title, cmds)` closure) is reusable; just replace the data source.

### Step 5 — Update `_build_handler_table`

```python
def _build_handler_table() -> dict[str, Callable[[list[str]], int]]:
    return {
        "compile": _cmd_compile,
        "describe": _cmd_describe,
        "why": _cmd_why,
        "preinfra": _cmd_preinfra,
        "projinfra": _cmd_projinfra,
        "envinfra": _cmd_envinfra,
        "build": _cmd_build,
        "test": _cmd_test,
        "migrate": _cmd_migrate,
        "check": _cmd_check,
        "merge": _cmd_merge,
        "containerize": _cmd_containerize,
        "release": _cmd_release,
        "stagetest": _cmd_stagetest,
        "rollback": _cmd_rollback,
        "roles": _cmd_roles,
        "role": _cmd_role,
    }
```

Keep ordering aligned with `_GROUPS` for readability.

### Step 6 — Sweep for `_cmd_up`/`_cmd_down`/`_cmd_bootstrap` references

```bash
cd ~/.claude/jean_baudrillard/docex
grep -rn '_cmd_up\|_cmd_down\|_cmd_bootstrap' src/ tests/
```

There should be no callers other than the (now-removed) handler-table entry. Remove any straggler imports or test helpers that referenced them.

### Step 7 — Update tests

#### Dispatcher tests

Search for tests that exercise `docex up <env>` / `docex down <env>` / `docex bootstrap`:

```bash
grep -rn '"up"\|"down"\|"bootstrap"\|docex up\|docex down\|docex bootstrap' tests/
```

For each:
- `docex up <env>` invocations become `docex envinfra up <env>`.
- `docex down <env>` invocations become `docex envinfra down <env>`.
- `docex bootstrap` invocations become `docex projinfra up production`.

Tests that pin help-text grouping (the `Phase 1 (implemented)` headings) need updating to the new purpose grouping. Search:

```bash
grep -rn 'Phase 1\|Phase 2\|Phase 3\|Phase 4\|Phase 5\|_PHASE' tests/
```

#### New handler tests

Add minimal tests for the three new dispatchers:

- `test_preinfra_stub_returns_zero` — invokes `preinfra development` and `preinfra production`; both return 0; stdout contains "stub" + the side name.
- `test_preinfra_rejects_unknown_side` — argparse rejects (`docex preinfra invalid` → non-zero exit).
- `test_envinfra_dispatches_to_run_up` and `test_envinfra_dispatches_to_run_down` — mock `run_up`/`run_down` and confirm they're invoked with the right args.
- `test_envinfra_refuses_stage_and_prod` — argparse rejection.
- `test_projinfra_elastic_up_production_runs_bootstrap` — mock `run_bootstrap`, point context to an elastic project, assert it's called.
- `test_projinfra_other_invocations_are_stubs` — fixed projects' projinfra, elastic projinfra down, etc., all return 0 with stub message and DON'T call `run_bootstrap`.

#### Real-test guards

Some `*_real.py` integration tests probably shell out to `docex bootstrap` or `docex up`/`down`. Per campaign-wide rule, those are out of scope; don't fix them. They'll surface in the final smoke walk.

### Step 8 — Run tests

```bash
cd ~/.claude/jean_baudrillard/docex
pytest tests/unit -x
pytest tests/integration -x -m "not integration"
```

Both green. `*_real.py` deselected.

### Step 9 — Sanity sweep

```bash
cd ~/.claude/jean_baudrillard/docex
# No old command names in handler / help / phase machinery
grep -rn '_PHASE\|_phase_of\|_cmd_bootstrap\|_cmd_up\b\|_cmd_down\b' src/

# Old command literals only in deprecated-test or comment contexts
grep -rn '"bootstrap"\|docex bootstrap\|docex up\|docex down' src/ tests/
```

The first sweep should return no hits. The second should return only legitimate references (e.g. comments in pipeline/bootstrap.py describing what `run_bootstrap` historically corresponded to).

## Out of scope

- **No internal-module renames.** `orchestrate/up.py`, `orchestrate/down.py`, `pipeline/bootstrap.py` keep their names and signatures.
- **No `preinfra` real checks** — mod 042.
- **No `projinfra` real behavior beyond elastic-up-production** — mods 036/037/038/039.
- **No `bin/docex` shim changes** — shim is command-name-transparent.
- **No `docex --version`, `--debug` global option changes.**
- **No `test_projects/{fixed,elastic}/` edits.**

## Done criteria

- [ ] `_cmd_bootstrap`, `_cmd_up`, `_cmd_down` deleted.
- [ ] `_cmd_preinfra`, `_cmd_projinfra`, `_cmd_envinfra` added with the contracts in Step 3.
- [ ] `_PHASE*_COMMANDS` constants and `_phase_of` deleted; `_GROUPS` (purpose-based) added.
- [ ] `_format_usage` rewritten to iterate `_GROUPS`.
- [ ] `_build_handler_table` updated; `_HELP_TEXT` reflects the new surface.
- [ ] Dispatcher tests for the three new commands added; existing tests using `up`/`down`/`bootstrap` migrated.
- [ ] `pytest tests/unit -x` and offline `tests/integration -x -m "not integration"` both green.
- [ ] Sanity sweeps clean.
- [ ] No internal-module renames, no `test_projects/` edits, no shim edits.

Working tree dirty when finished. Do not commit.
