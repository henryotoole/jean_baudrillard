"""Transfer-table loader.

Transfer tables describe how each ``role/engine`` combination is
realized per foundation. The doctrine ships canonical tables in
``/opt/docex/tables/`` (inside the image) or, when running from a
source checkout, ``<repo>/tables/``. Projects may also place
overrides at ``<project_root>/infra/transfer_tables/``.

The two layers are deep-merged at compile time. The merge semantics:

- For dicts, keys are unioned and values are recursively merged.
- For scalars and lists, the project-local value wins outright.

This module also resolves the ``engine: [minio, s3]`` pattern in
``infra.yml`` against the foundation being compiled, by consulting
each candidate's own ``foundation:`` declaration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from docex.errors import TransferTableError

# Candidate locations for the bundled tables. The first one found wins.
# In the container image, the tables live at /opt/docex/tables/. When
# running from a source checkout (tests, dev), they live at
# <repo>/tables/, which we find by walking up from this file.
_BUNDLED_TABLES_CANDIDATES: list[Path] = [
    Path("/opt/docex/tables"),
    Path(__file__).resolve().parent.parent.parent.parent / "tables",
]


@dataclass
class EngineEntry:
    """A single role/engine entry from a transfer table."""

    role: str
    engine: str
    foundation: str  # 'fixed' | 'elastic' | 'both'
    defaults: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)
    provides: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    naming: dict[str, Any] = field(default_factory=dict)

    def supports(self, foundation: str) -> bool:
        return self.foundation in (foundation, "both")

    def defaults_for(self, foundation: str) -> dict[str, Any]:
        return dict(self.defaults.get(foundation, {}) or {})

    def provides_for(self, foundation: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for part_name, per_foundation in (self.provides or {}).items():
            if not isinstance(per_foundation, dict):
                continue
            if foundation in per_foundation:
                out[part_name] = per_foundation[foundation]
        return out

    def field_translation(
        self, field_name: str, foundation: str
    ) -> dict[str, Any] | None:
        f = (self.fields or {}).get(field_name)
        if f is None:
            return None
        return f.get(foundation)


@dataclass
class TransferTables:
    """Loaded transfer tables exposed as a queryable object."""

    # role_name -> engine_name -> EngineEntry
    by_role: dict[str, dict[str, EngineEntry]]

    def role(self, role_name: str) -> dict[str, EngineEntry]:
        if role_name not in self.by_role:
            raise TransferTableError(
                f"unknown role {role_name!r} — not in bundled or project-local "
                "transfer tables"
            )
        return self.by_role[role_name]

    def engine(self, role_name: str, engine_name: str) -> EngineEntry:
        engines = self.role(role_name)
        if engine_name not in engines:
            raise TransferTableError(
                f"unknown engine {engine_name!r} for role {role_name!r}; "
                f"known: {sorted(engines)}"
            )
        return engines[engine_name]

    def engine_for(
        self,
        role_name: str,
        engine_decl: str | list[str],
        foundation: str,
    ) -> EngineEntry:
        """Resolve ``engine: [minio, s3]`` against the target foundation.

        If ``engine_decl`` is a string, the engine entry must support the
        foundation. If it's a list, return the first candidate whose
        ``foundation`` permits the target.
        """
        candidates: list[str]
        if isinstance(engine_decl, str):
            candidates = [engine_decl]
        else:
            candidates = list(engine_decl)
        for cand in candidates:
            entry = self.engine(role_name, cand)
            if entry.supports(foundation):
                return entry
        raise TransferTableError(
            f"no engine in {candidates!r} supports foundation "
            f"{foundation!r} for role {role_name!r}"
        )

    def all_engines(self) -> Iterable[EngineEntry]:
        for role_engines in self.by_role.values():
            yield from role_engines.values()


# ---------------------------------------------------------------------------
# Loading + merging
# ---------------------------------------------------------------------------


def _deep_merge(base: Any, override: Any) -> Any:
    """Deep-merge ``override`` onto ``base``.

    Dicts merge key-by-key. Scalars and lists are replaced wholesale by
    the override. ``None`` in override does not remove a key (use an
    explicit empty dict if you want a leaf zeroed out)."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            if k in out:
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out
    # Lists and scalars: override wins.
    return override


def _read_yaml_files(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Read every ``*.yml`` / ``*.yaml`` file under ``root`` recursively.

    Recurses into subdirectories so the bundled layout (``tables/roles/*.yml``)
    is discovered without each consumer having to know the depth. Project-local
    tables may use either layout: flat ``infra/transfer_tables/*.yml`` or a
    nested ``infra/transfer_tables/roles/*.yml``.
    """
    if not root.is_dir():
        return []
    out: list[tuple[Path, dict[str, Any]]] = []
    paths = sorted(p for p in root.rglob("*.yml")) + sorted(
        p for p in root.rglob("*.yaml")
    )
    # Stable, deterministic order: relative path string.
    paths.sort(key=lambda p: str(p.relative_to(root)))
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise TransferTableError(f"{path}: malformed YAML: {exc}") from exc
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise TransferTableError(
                f"{path}: expected a YAML mapping at the document root"
            )
        out.append((path, raw))
    return out


def _bundled_tables_root() -> Path | None:
    for cand in _BUNDLED_TABLES_CANDIDATES:
        if cand.is_dir():
            return cand
    return None


def _project_tables_root(project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    p = project_root / "infra" / "transfer_tables"
    return p if p.is_dir() else None


def _parse_entry(role: str, engine: str, raw: dict[str, Any]) -> EngineEntry:
    foundation = raw.get("foundation")
    if foundation not in ("fixed", "elastic", "both"):
        raise TransferTableError(
            f"role {role!r} engine {engine!r}: foundation must be "
            f"'fixed', 'elastic', or 'both' (got {foundation!r})"
        )
    return EngineEntry(
        role=role,
        engine=engine,
        foundation=foundation,
        defaults=raw.get("defaults", {}) or {},
        fields=raw.get("fields", {}) or {},
        provides=raw.get("provides", {}) or {},
        env=raw.get("env", {}) or {},
        naming=raw.get("naming", {}) or {},
    )


def load_transfer_tables(project_root: Path | None) -> TransferTables:
    """Load bundled + project-local tables and return the merged view."""
    raw_merged: dict[str, Any] = {}

    bundled_root = _bundled_tables_root()
    sources: list[Path] = []
    if bundled_root is not None:
        sources.append(bundled_root)
    proj_root = _project_tables_root(project_root)
    if proj_root is not None:
        sources.append(proj_root)

    for root in sources:
        for _path, doc in _read_yaml_files(root):
            roles = doc.get("roles")
            if not isinstance(roles, dict):
                continue
            # Merge under the same top-level shape: ``{"roles": {...}}``
            raw_merged = _deep_merge(raw_merged, {"roles": roles})

    by_role: dict[str, dict[str, EngineEntry]] = {}
    for role, engines in (raw_merged.get("roles") or {}).items():
        if not isinstance(engines, dict):
            raise TransferTableError(
                f"role {role!r}: expected a mapping of engine name -> entry"
            )
        for engine, raw_entry in engines.items():
            if not isinstance(raw_entry, dict):
                raise TransferTableError(
                    f"role {role!r} engine {engine!r}: expected a mapping"
                )
            by_role.setdefault(role, {})[engine] = _parse_entry(
                role, engine, raw_entry
            )
    return TransferTables(by_role=by_role)
