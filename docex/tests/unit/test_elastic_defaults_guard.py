"""Mod 138: the compile-time guard against inert `defaults.elastic` keys.

The ECS task-definition renderer (emit/hcl.py::render_task_definition) reads a
NAMED, closed set of keys off the merged service body — it does not merge the
block generically the way the fixed compose path does. A `defaults.elastic`
key outside that set would fall on the floor unread (mod 127's healthCheck
near-miss). `compile.py` now rejects any such stray key on a
`task_definition`-target engine.

These tests exercise the guard's predicate directly (constructing an
`EngineEntry` is cheap; driving a full `compile_env` is not) and assert every
shipped engine whose elastic default target is `task_definition` passes clean.
"""

from __future__ import annotations

from docex.cicl.transfer import EngineEntry, load_transfer_tables
from docex.emit.hcl import TASK_DEF_DEFAULT_READ_KEYS


def _stray(entry: EngineEntry) -> set[str]:
    """Mirror of the compile.py guard predicate."""
    return set(entry.defaults_for("elastic")) - TASK_DEF_DEFAULT_READ_KEYS


def test_bogus_defaults_elastic_key_is_flagged_stray():
    entry = EngineEntry(
        role="web",
        engine="python",
        foundation="both",
        emits={"elastic": ["task_definition", "ecs_service"]},
        defaults={
            "elastic": {
                "healthCheck": {"command": ["CMD", "./health.sh", "api"]},
                "bogus_key": 1,
            }
        },
        naming="ecs",
    )
    assert _stray(entry) == {"bogus_key"}


def test_healthcheck_only_defaults_elastic_has_no_stray_key():
    entry = EngineEntry(
        role="web",
        engine="python",
        foundation="both",
        emits={"elastic": ["task_definition", "ecs_service"]},
        defaults={
            "elastic": {"healthCheck": {"command": ["CMD", "./health.sh", "api"]}}
        },
        naming="ecs",
    )
    assert _stray(entry) == set()


def test_the_two_removed_keys_would_now_be_flagged():
    """The exact keys mod 138 deleted (launch_type / network_mode) are stray."""
    entry = EngineEntry(
        role="web",
        engine="python",
        foundation="both",
        emits={"elastic": ["task_definition", "ecs_service"]},
        defaults={
            "elastic": {
                "launch_type": "FARGATE",
                "network_mode": "awsvpc",
                "healthCheck": {"command": ["CMD", "./health.sh", "api"]},
            }
        },
        naming="ecs",
    )
    assert _stray(entry) == {"launch_type", "network_mode"}


def test_shipped_task_definition_engines_pass_the_guard():
    """Every bundled engine whose elastic default target is the task
    definition must carry only readable `defaults.elastic` keys."""
    tables = load_transfer_tables(project_root=None)
    checked = []
    for entry in tables.all_engines():
        if "elastic" not in (entry.emits or {}):
            continue
        if entry.default_target("elastic") != "task_definition":
            continue
        checked.append((entry.role, entry.engine))
        assert _stray(entry) == set(), (entry.role, entry.engine, _stray(entry))
    # The three core roles must be among those actually exercised here, so a
    # future emits: change that stops routing them through task_definition
    # cannot silently drop this coverage.
    roles_checked = {role for role, _ in checked}
    assert {"web", "worker", "clock"} <= roles_checked, roles_checked
