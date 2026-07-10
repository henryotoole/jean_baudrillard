"""Mod 012: strict transfer-table validation with descriptive failure messages."""

from __future__ import annotations

from pathlib import Path

import pytest

from docex.cicl.transfer import load_transfer_tables
from docex.errors import TransferTableError


def _write_project_table(project_root: Path, content: str, name: str = "extra.yml") -> None:
    """Write a project-local transfer-table file at the conventional path."""
    tt_dir = project_root / "infra" / "transfer_tables"
    tt_dir.mkdir(parents=True, exist_ok=True)
    (tt_dir / name).write_text(content)


def test_unknown_toplevel_key_typo_suggests_correction(tmp_path: Path) -> None:
    """`role:` (singular) at top level — error names the file and suggests `roles`."""
    _write_project_table(tmp_path, "role:\n  sidecar:\n    nginx:\n      foundation: both\n")
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "unknown top-level key 'role'" in msg
    assert "did you mean 'roles'" in msg


def test_unknown_toplevel_key_unrelated_lists_allowed(tmp_path: Path) -> None:
    """A wholly-unrelated top-level key falls back to listing allowed keys."""
    _write_project_table(tmp_path, "frobnicate: true\n")
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "frobnicate" in msg
    assert "allowed: generation_policies, naming_policies, roles" in msg


def test_unknown_engine_subkey_with_typo(tmp_path: Path) -> None:
    """`defualts:` typo under an engine entry — error names file + role + engine + key."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  sidecar:\n"
        "    nginx:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      defualts:\n"
        "        fixed: {}\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "roles.sidecar.nginx" in msg
    assert "'defualts'" in msg
    assert "did you mean 'defaults'" in msg


def test_unknown_emit_destination_value(tmp_path: Path) -> None:
    """`s3_buckets` (plural typo) — error names file + role + engine + foundation + bad value."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  storage:\n"
        "    bespoke:\n"
        "      foundation: elastic\n"
        "      naming: s3\n"
        "      emits:\n"
        "        elastic: [s3_buckets]\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "roles.storage.bespoke.emits.elastic" in msg
    assert "unknown destination 's3_buckets'" in msg
    assert "did you mean 's3_bucket'" in msg


def test_unknown_naming_policy_subkey(tmp_path: Path) -> None:
    """`seperator:` typo on a policy — error names file + policy + key."""
    _write_project_table(
        tmp_path,
        "naming_policies:\n"
        "  custom:\n"
        "    seperator: hyphen\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "naming_policies.custom" in msg
    assert "'seperator'" in msg
    assert "did you mean 'separator'" in msg


def test_unknown_foundation_in_emits(tmp_path: Path) -> None:
    """An invalid foundation key under `emits:` is rejected with the allowed list."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  weird:\n"
        "    bespoke:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        mainframe: [compose_service]\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "infra/transfer_tables/extra.yml" in msg
    assert "emits.mainframe" in msg
    assert "unknown foundation 'mainframe'" in msg


def test_bundled_table_passes_clean(tmp_path: Path) -> None:
    """Sanity: with no project-local table, loading still succeeds with bundled tables only."""
    tables = load_transfer_tables(tmp_path)
    # Bundled-only load should return all canonical roles.
    assert "web" in tables.by_role
    assert "relational_db" in tables.by_role


def test_well_formed_project_table_loads(tmp_path: Path) -> None:
    """A correctly-shaped project table merges cleanly — no spurious errors."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  sidecar:\n"
        "    nginx:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        fixed: [compose_service]\n"
        "        elastic: [task_definition, ecs_service]\n"
        "      defaults:\n"
        "        fixed: {image: 'nginx:1.27-alpine'}\n"
        "        elastic: {image: 'nginx:1.27-alpine'}\n"
        "      provides: {}\n"
        "      env: {}\n",
    )
    tables = load_transfer_tables(tmp_path)
    assert "sidecar" in tables.by_role
    assert "nginx" in tables.by_role["sidecar"]


# ---------------------------------------------------------------------------
# Mod 015 — persistent_storage <-> efs_file_system bidirectional validation.
# ---------------------------------------------------------------------------


def test_persistent_storage_without_efs_destination_fails(tmp_path: Path) -> None:
    """Mod 015: declaring persistent_storage without efs_file_system in emits fails at load."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  analytics_db:\n"
        "    clickhouse:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        fixed: [compose_service]\n"
        # missing efs_file_system in the elastic emits list:
        "        elastic: [task_definition, ecs_service]\n"
        "      defaults:\n"
        "        fixed: {image: 'clickhouse/clickhouse-server:24'}\n"
        "        elastic: {image: 'clickhouse/clickhouse-server:24', cpu: '512', memory: '2048'}\n"
        "      persistent_storage:\n"
        "        mount_path: /var/lib/clickhouse\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "persistent_storage" in msg
    assert "efs_file_system" in msg


def test_efs_destination_without_persistent_storage_fails(tmp_path: Path) -> None:
    """Mod 015: declaring efs_file_system in emits without persistent_storage fails at load."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  analytics_db:\n"
        "    clickhouse:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        fixed: [compose_service]\n"
        # has the destination but no persistent_storage field:
        "        elastic: [task_definition, ecs_service, efs_file_system]\n"
        "      defaults:\n"
        "        fixed: {image: 'clickhouse/clickhouse-server:24'}\n"
        "        elastic: {image: 'clickhouse/clickhouse-server:24', cpu: '512', memory: '2048'}\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "efs_file_system" in msg
    assert "persistent_storage" in msg


def test_persistent_storage_requires_mount_path(tmp_path: Path) -> None:
    """Mod 015: persistent_storage missing mount_path fails at load."""
    _write_project_table(
        tmp_path,
        "roles:\n"
        "  analytics_db:\n"
        "    clickhouse:\n"
        "      foundation: both\n"
        "      naming: ecs\n"
        "      emits:\n"
        "        fixed: [compose_service]\n"
        "        elastic: [task_definition, ecs_service, efs_file_system]\n"
        "      defaults:\n"
        "        fixed: {image: 'foo'}\n"
        "        elastic: {image: 'foo'}\n"
        "      persistent_storage: {}\n",  # empty — missing mount_path
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "mount_path" in msg


# ---------------------------------------------------------------------------
# Mod 076 — env-var kind schema + generation policies validation.
# ---------------------------------------------------------------------------


_ENGINE_HEAD = (
    "roles:\n"
    "  sidecar:\n"
    "    nginx:\n"
    "      foundation: both\n"
    "      naming: ecs\n"
    "      emits:\n"
    "        fixed: [compose_service]\n"
    "      env:\n"
)


def test_env_unknown_kind_rejected(tmp_path: Path) -> None:
    _write_project_table(
        tmp_path, _ENGINE_HEAD + "        FOO:\n          kind: sneaky\n"
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    assert "sneaky" in str(exc.value)


def test_env_unknown_subkey_rejected(tmp_path: Path) -> None:
    _write_project_table(
        tmp_path,
        _ENGINE_HEAD
        + "        FOO:\n          kind: secret\n          descr: typo\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "descr" in msg
    assert "did you mean 'desc'" in msg


def test_env_fixed_without_value_rejected(tmp_path: Path) -> None:
    _write_project_table(
        tmp_path, _ENGINE_HEAD + "        FOO:\n          kind: fixed\n"
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    assert "value" in str(exc.value)


def test_env_fixed_with_policy_rejected(tmp_path: Path) -> None:
    _write_project_table(
        tmp_path,
        _ENGINE_HEAD
        + "        FOO:\n          kind: fixed\n          value: x\n"
        "          policy: password\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    assert "policy" in str(exc.value)


def test_env_minted_without_policy_rejected(tmp_path: Path) -> None:
    _write_project_table(
        tmp_path, _ENGINE_HEAD + "        FOO:\n          kind: minted\n"
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    assert "policy" in str(exc.value)


def test_env_minted_with_value_rejected(tmp_path: Path) -> None:
    _write_project_table(
        tmp_path,
        _ENGINE_HEAD
        + "        FOO:\n          kind: minted\n          policy: password\n"
        "          value: x\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    assert "value" in str(exc.value)


def test_env_minted_unknown_policy_rejected(tmp_path: Path) -> None:
    """Rule 13: a minted var whose policy names no generation policy fails."""
    _write_project_table(
        tmp_path,
        _ENGINE_HEAD
        + "        FOO:\n          kind: minted\n          policy: nonesuch\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "nonesuch" in msg
    assert "sidecar.nginx.env.FOO.policy" in msg


def test_generation_policy_unknown_subkey_rejected(tmp_path: Path) -> None:
    _write_project_table(
        tmp_path,
        "generation_policies:\n"
        "  custom:\n"
        "    length: 8\n"
        "    alphabets: alnum\n",  # typo
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    msg = str(exc.value)
    assert "generation_policies.custom" in msg
    assert "alphabets" in msg
    assert "did you mean 'alphabet'" in msg


def test_generation_policy_bad_alphabet_rejected(tmp_path: Path) -> None:
    _write_project_table(
        tmp_path,
        "generation_policies:\n  custom:\n    length: 8\n    alphabet: hex\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    assert "alphabet" in str(exc.value)


def test_generation_policy_bad_length_rejected(tmp_path: Path) -> None:
    _write_project_table(
        tmp_path,
        "generation_policies:\n  custom:\n    length: -1\n    alphabet: alnum\n",
    )
    with pytest.raises(TransferTableError) as exc:
        load_transfer_tables(tmp_path)
    assert "length" in str(exc.value)
