# Mod 152 — Implementation steps: the env-agnostic slot primitive

Scope: **docex source + tests only.** Thread an env-agnostic `slot=k` through
physical-name interpolation in the compiler so N isolated stacks of one fixed env
coexist on one host. Default slot 1 emits **no** segment (byte-identical to
today). No CLI flag, no orchestration, no web-network re-tiering (those are Mods
153/154).

**Do not touch** `plans/core/*.md`, the doctrine (`../../../../doctrine/**`), or
`CHANGELOG.md` — the corporal handles documentation and doctrine amendments
separately. **Do not touch** the `-web` external network naming, `orchestrate/`
(beyond leaving the two re-derivers at their `slot=1` default), the elastic HCL
emitter, or `validate.py`.

Read `plans/core/compiler.md` (Naming flow, Service expansion, Output layout) and
this mod's `overview.md` before starting.

The settled decisions (corporal-ratified): slot token is **`s{k}`** (e.g. `s2`),
inserted between the env segment and the rest; slot-k>1 output lands in
**`.docex/slots/<env>/<k>/`**; the image tag is **not** slotted; the `-web`
network is **not** slotted.

---

## Step 0 — Prove the byte-identical gate FIRST

Before writing any slot-threading code, add the golden-output diff test so the
default path is provably unchanged as you work. It must **pass on the unmodified
tree** (the committed goldens recompile identically today) and continue to pass
after every later step.

Create `tests/unit/test_slot_golden.py`:

```python
"""Mod 152 — the byte-identical default gate.

`docex compile` (slot 1) must reproduce each test project's committed golden
`infra/output/` tree byte-for-byte. This is the SC2 verification gate: the slot
primitive's default emits no segment, so existing output is unchanged.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from docex.cicl.compile import run_compile
from docex.context import load_project_context

_DOCEX_ROOT = Path(__file__).resolve().parents[2]
_TEST_PROJECTS = _DOCEX_ROOT / "test_projects"
_IGNORE = shutil.ignore_patterns(".git", ".docex", ".pytest_cache", "__pycache__")


def _walk_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.mark.parametrize("foundation", ["fixed", "elastic"])
def test_slot1_recompile_is_byte_identical(tmp_path: Path, foundation: str) -> None:
    project = _TEST_PROJECTS / foundation
    golden = _walk_bytes(project / "infra" / "output")
    assert golden, f"no committed golden output under {project}/infra/output"

    dest = tmp_path / foundation
    shutil.copytree(project, dest, ignore=_IGNORE)
    shutil.rmtree(dest / "infra" / "output", ignore_errors=True)

    ctx = load_project_context(dest)
    assert run_compile(ctx) == 0

    fresh = _walk_bytes(dest / "infra" / "output")
    assert set(fresh) == set(golden), (
        f"file set drift: only-fresh={sorted(set(fresh) - set(golden))} "
        f"only-golden={sorted(set(golden) - set(fresh))}"
    )
    for rel in sorted(golden):
        assert fresh[rel] == golden[rel], f"byte drift in {rel}"
```

Run `python -m pytest tests/unit/test_slot_golden.py -q` and confirm **green on
the unmodified codebase**. If it is red before you change anything, stop and
report — the golden tree is already stale and the gate cannot be trusted.

---

## Step 1 — Thread `slot` through the naming helpers (`src/docex/cicl/compile.py`)

### 1a. `_global_service_name`

Add a keyword-only `slot: int = 1`; insert the segment after `env` iff `slot != 1`:

```python
def _global_service_name(
    project: str, env: str, name: str, policy: NamingPolicy,
    *, service: str | None = None, slot: int = 1,
) -> str:
    # Mod 152: the slot segment. Slot 1 (default) inserts NOTHING, so every
    # existing name is byte-identical; slot k>1 weaves `_s{k}` between the env
    # and the rest (`{project}_{env}_s{k}_{name}_{service}`), namespacing this
    # physical name so N stacks of one fixed env coexist on one host. Because
    # container_name/service-keys/volumes/magic-refs all derive from this one
    # function, slotting it here is what closes what `--project-name` cannot.
    slot_seg = "" if slot == 1 else f"_s{slot}"
    raw = (
        f"{project}_{env}{slot_seg}_{name}_{service}" if service is not None
        else f"{project}_{env}{slot_seg}_{name}"
    )
    return apply_policy(raw, policy)
```

Update its docstring's "Core services carry a fourth segment" note to mention the
optional slot segment.

### 1b. `codebase_global_name` (public helper)

```python
def codebase_global_name(
    project: str, env: str, codebase: str, policy: NamingPolicy,
    *, slot: int = 1,
) -> str:
    return _global_service_name(project, env, codebase, policy, slot=slot)
```

Add to its docstring: the two out-of-compiler re-derivers
(`orchestrate/_common.py::exec_service_key`,
`orchestrate/migrate.py::_migration_task_family`) keep the `slot=1` default this
mod and **must be made slot-aware in Mod 154** when a slot-k stack runs
migrations, or they will not match the slotted name this emits.

### 1c. `_network_name` (line ~319)

Thread `slot` for consistency even though it currently has no caller (keeps the
helper correct for a future emitter, e.g. Mod 153):

```python
def _network_name(project: str, env: str, network: str, *, slot: int = 1) -> str:
    slot_seg = "" if slot == 1 else f"-s{slot}"
    return f"{project}_{env}{slot_seg}_{network}"
```

---

## Step 2 — Thread `slot` through `compile_env` and `CompiledEnv`

### 2a. `CompiledEnv` — new field

Add after `project_dns_label` (or anywhere in the dataclass, default-valued so
existing constructions are unaffected):

```python
    # Mod 152: which slot this env was compiled for. 1 (default) means no slot
    # segment — byte-identical to a slotless compile. >1 weaves `-s{slot}` into
    # every physical name. Read by emit/compose.py::_network_section to slot the
    # non-web network names (the only physical name not derived from a
    # global_name).
    slot: int = 1
```

### 2b. `compile_env` — accept and thread `slot`

Add `slot: int = 1` to the signature (keyword-only, beside `notes_seen`). Thread
it into **both** `_global_service_name` call sites and store it on the result:

- the `gname = _global_service_name(...)` call (~line 736): add `slot=slot`.
- the `codebase_global_name=(_global_service_name(project_name, env, cb_name,
  ...))` call (~line 1148): add `slot=slot`.
- the returned `CompiledEnv(...)`: add `slot=slot`.

Add to `compile_env`'s docstring: `slot` (mod 152) scopes every physical name;
`slot=1` is byte-identical to a slotless compile.

Leave `validate_document` and rule 5 untouched — they run on the authored doc
before any slot exists and are slot-independent (within one slot every name
carries the same segment, so relative comparisons are unchanged).

---

## Step 3 — Slot the non-web network names (`src/docex/emit/compose.py`)

In `_network_section`, insert the slot segment on the **non-web** branch only:

```python
def _network_section(compiled: CompiledEnv) -> dict[str, Any]:
    ...docstring: add a line noting the non-web network carries the slot
    segment (`-s{k}`) so two slots of one env do not share an internal
    bridge; the `web` network is projinfra-owned and slot-shared until
    Mod 153 re-tiers it...
    out: dict[str, Any] = {}
    # Mod 152: non-web env networks carry the slot segment so slots are
    # isolated at the network layer too. The `web` network is external/
    # projinfra-owned and stays slot-shared this mod (Mod 153 re-tiers it).
    slot_seg = "" if compiled.slot == 1 else f"-s{compiled.slot}"
    for short in sorted(compiled.networks):
        if short == "web":
            out[short] = {
                "name": f"{compiled.project_dns_label}-{compiled.env}-web",
                "external": True,
            }
            continue
        full = f"{compiled.project_dns_label}-{compiled.env}{slot_seg}-{short}"
        out[short] = {"name": full}
    return out
```

No other emitter change is needed: container names, compose service keys,
sidecars, replica keys, the exec key, and the named-volume block all derive from
`global_name` / `codebase_global_name` (slotted in Step 1) or from the postgres/
clickhouse `${global_service_name}_data` volume (slotted transitively).

---

## Step 4 — The slot-k output emission path (`src/docex/cicl/compile.py`)

`run_compile` must stay **behaviorally unchanged** (all four envs, slot 1, into
`infra/output/<env>/`). Refactor its per-env emit body into a reusable helper,
then add the slot entry point.

### 4a. Extract `_emit_env_dir`

Pull the per-env emit block out of `run_compile`'s loop (the `schedules.yml`
write + the fixed/elastic branch that writes compose / hcl / ansible) into:

```python
def _emit_env_dir(compiled: CompiledEnv, env_dir: Path, *, naming_policies: Any) -> int:
    """Emit one compiled env's artifacts into `env_dir`. Returns files written.

    Shared by run_compile (slot 1, per env, into infra/output/<env>/) and
    compile_slot (any slot, into .docex/slots/<env>/<k>/). It emits ONLY the
    env-tier artifacts; the project tier (networks/traefik) is emitted once by
    run_compile and is slot-shared (Mod 153).
    """
    from docex.emit.compose import emit_compose
    from docex.emit.hcl import emit_hcl
    from docex.emit.ansible import emit_ansible
    from docex.emit.schedules import has_clock, render_schedules_file

    env_dir.mkdir(parents=True, exist_ok=True)
    files = 0
    if has_clock(compiled):
        (env_dir / "schedules.yml").write_text(render_schedules_file(compiled))
        files += 1
    if compiled.foundation == "fixed":
        emit_compose(compiled, env_dir / "docker-compose.yml")
        files += 1
        if compiled.env in ("stage", "prod"):
            emit_ansible(compiled, env_dir)
            files += 3
    else:
        emit_hcl(compiled, env_dir / "main.tf", naming_policies=naming_policies)
        files += 1
    return files
```

Rewrite `run_compile`'s loop body to call `_emit_env_dir(compiled, env_dir,
naming_policies=ctx.transfer_tables.naming_policies)` and add its return to
`files_written`. **Preserve** everything else in `run_compile` verbatim — the
`compiled_envs.append(compiled)` bookkeeping, the `notes_seen` set, the
project-tier emission after the loop, and the final print. Confirm the golden
test (Step 0) is still green after this refactor — it proves the extraction was
behavior-preserving.

### 4b. Add `compile_slot`

```python
def compile_slot(ctx: Any, env: str, slot: int) -> Path:
    """Compile ONE env at `slot` and emit it. Returns the output dir.

    slot == 1 -> infra/output/<env>/ (identical to run_compile's per-env path).
    slot  > 1 -> .docex/slots/<env>/<slot>/ — ephemeral, machine-local scratch
                 (beside .docex/runs/ and .docex/checks/), gitignored, never in
                 the tracked infra/output/ tree.

    The env-agnostic primitive Mod 154's orchestration and the slot tests call.
    No CLI verb reaches it this mod.
    """
    from docex.errors import InfraFileError
    if ctx.infra is None:
        raise InfraFileError(
            f"{ctx.project_root}/infra/infra.yml: file missing — compile "
            "requires an infra.yml"
        )
    issues = validate_document(ctx.infra, ctx.transfer_tables)
    if issues:
        raise ValidationError(issues)

    if slot == 1:
        env_dir = ctx.project_root / "infra" / "output" / env
    else:
        env_dir = ctx.project_root / ".docex" / "slots" / env / str(slot)

    compiled = compile_env(
        ctx.infra, ctx.transfer_tables, env=env,
        project_name=ctx.project.name, project_version=ctx.project.version,
        slot=slot,
    )
    _emit_env_dir(
        compiled, env_dir,
        naming_policies=ctx.transfer_tables.naming_policies,
    )
    return env_dir
```

(Import `validate_document`, `ValidationError` are already imported at module top.)

---

## Step 5 — Slot-behavior tests (`tests/unit/test_slot_primitive.py`)

New file. Uses the fixed test project (has postgres `appdb` + clickhouse
`events` + an `internal` network + the `-web` network — everything the slot must
touch).

```python
"""Mod 152 — the slot primitive: name interpolation, isolation, determinism."""
from __future__ import annotations

import shutil
from pathlib import Path

from docex.cicl.compile import compile_env, compile_slot
from docex.context import load_project_context

_DOCEX_ROOT = Path(__file__).resolve().parents[2]
_FIXED = _DOCEX_ROOT / "test_projects" / "fixed"
_IGNORE = shutil.ignore_patterns(".git", ".docex", ".pytest_cache", "__pycache__")


def _ctx(tmp_path):
    dest = tmp_path / "fixed"
    shutil.copytree(_FIXED, dest, ignore=_IGNORE)
    shutil.rmtree(dest / "infra" / "output", ignore_errors=True)
    return load_project_context(dest), dest


def _compiled(ctx, slot):
    return compile_env(
        ctx.infra, ctx.transfer_tables, env="test",
        project_name=ctx.project.name, project_version=ctx.project.version,
        slot=slot,
    )


def test_slot1_names_equal_slotless(tmp_path):
    ctx, _ = _ctx(tmp_path)
    c1 = _compiled(ctx, 1)
    # slot=1 must equal the default (no `slot` kwarg) name-for-name.
    c0 = compile_env(
        ctx.infra, ctx.transfer_tables, env="test",
        project_name=ctx.project.name, project_version=ctx.project.version,
    )
    assert {n: s.global_name for n, s in c1.services.items()} == \
           {n: s.global_name for n, s in c0.services.items()}
    assert c1.slot == 1


def test_slot2_global_names_carry_segment(tmp_path):
    ctx, _ = _ctx(tmp_path)
    c = _compiled(ctx, 2)
    assert c.slot == 2
    for name, svc in c.services.items():
        assert "-test-s2-" in svc.global_name, (name, svc.global_name)
    # codebase-keyed name (the exec/migrate stem) is slotted too.
    api = next(s for s in c.services.values() if s.codebase == "api")
    assert "-test-s2-api" == api.codebase_global_name.rsplit("-", 0)[0] or \
        "-test-s2-" in api.codebase_global_name


def test_slot2_magic_ref_resolves_to_slot_host(tmp_path):
    ctx, _ = _ctx(tmp_path)
    c = _compiled(ctx, 2)
    web = c.services["api-web"]
    # api.web holds a magic ref to appdb / worker; the resolved host must be
    # the slot-2 physical name, not the slotless one.
    joined = " ".join(str(v) for v in web.env.values())
    assert "-test-s2-" in joined


def test_slot2_emitted_compose_isolates_names(tmp_path):
    ctx, dest = _ctx(tmp_path)
    out_dir = compile_slot(ctx, "test", 2)
    assert out_dir == dest / ".docex" / "slots" / "test" / "2"
    compose = (out_dir / "docker-compose.yml").read_text()
    # container names, sidecar, exec, non-web network, postgres volume slotted.
    assert "container_name: docex-smoke-fixed-test-s2-api-web" in compose
    assert "docex-smoke-fixed-test-s2-api-web-otelcol" in compose
    assert "docex-smoke-fixed-test-s2-api-exec" in compose
    assert "docex-smoke-fixed-test-s2-internal" in compose
    assert "docex-smoke-fixed-test-s2-appdb_data" in compose
    # the -web external network is NOT slotted (Mod 153 seam).
    assert "docex-smoke-fixed-test-web" in compose
    assert "docex-smoke-fixed-test-s2-web" not in compose
    # slot-1 tracked output was NOT written by a slot>1 compile.
    assert not (dest / "infra" / "output" / "test" / "slots").exists()


def test_slot1_via_compile_slot_writes_tracked_path(tmp_path):
    ctx, dest = _ctx(tmp_path)
    out_dir = compile_slot(ctx, "test", 1)
    assert out_dir == dest / "infra" / "output" / "test"
    assert (out_dir / "docker-compose.yml").exists()


def test_slot2_is_deterministic(tmp_path):
    ctx, dest = _ctx(tmp_path)
    a = (compile_slot(ctx, "test", 2) / "docker-compose.yml").read_bytes()
    shutil.rmtree(dest / ".docex" / "slots", ignore_errors=True)
    b = (compile_slot(ctx, "test", 2) / "docker-compose.yml").read_bytes()
    assert a == b
```

Adjust the exact expected container/volume/network strings if the fixed test
project's project name differs from `docex-smoke-fixed` (confirm against
`test_projects/fixed/infra/output/test/docker-compose.yml`). The
`codebase_global_name` assertion in `test_slot2_global_names_carry_segment` is
awkward as written — simplify it to
`assert "-test-s2-api" in api.codebase_global_name`.

---

## Step 6 — Run the full suite

`cd /home/ubuntu/.claude/jean_baudrillard/docex && python -m pytest tests -q`

All green required. Pay special attention that **no existing test regressed** —
the byte-identical gate (Step 0) plus the pre-existing `tests/unit/test_compile.py`
and `test_replicas.py` are the ones that would catch an accidental default-path
change. If any pre-existing test now fails, the slot threading leaked into the
slot-1 path; fix it so slot 1 is byte-identical before proceeding.

Report: the compiler files changed, the new test files, the full `pytest`
summary line, and confirmation that Step 0's gate is green.
