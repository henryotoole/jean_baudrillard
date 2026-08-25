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
    assert "-test-s2-api" in api.codebase_global_name


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
