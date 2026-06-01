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
from docex.naming import NamingPolicies, parse_policies

# Candidate locations for the bundled tables. The first one found wins.
# In the container image, the tables live at /opt/docex/tables/. When
# running from a source checkout (tests, dev), they live at
# <repo>/tables/, which we find by walking up from this file.
_BUNDLED_TABLES_CANDIDATES: list[Path] = [
    Path("/opt/docex/tables"),
    Path(__file__).resolve().parent.parent.parent.parent / "tables",
]


# The closed set of emit destinations the compiler recognizes. Engines
# declare a subset of these in their `emits:` block; fields route to
# one of them via `target:`. Adding a destination requires growing the
# routing layer in compile.py + emit/hcl.py — that's the point: new
# destinations are doctrine knowledge embedded in docex source, not a
# free extension surface in the transfer tables.
EMIT_DESTINATIONS: dict[str, frozenset[str]] = {
    "fixed": frozenset({"compose_service"}),
    "elastic": frozenset({
        "task_definition",
        "ecs_service",
        "target_group",
        "rds_instance",
        "elasticache_cluster",
        "s3_bucket",
    }),
}


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
    # Reference into ``naming_policies:`` — resolved against
    # TransferTables.naming_policies by callers (compile.py,
    # orchestrate/migrate.py). See doctrine § Naming Policies.
    naming: str = ""
    # The port the engine listens on by default. Used for the ${port}
    # substitution variable when a service omits the `port:` field.
    default_port: int | None = None
    # Names the engine reserves and won't accept as identifiers — e.g.
    # postgres reserves SQL keywords like ``select`` and ``database``.
    # Compile-time validation matches the backing-service name against
    # this list (case-insensitive) so the operator hears about a
    # collision at ``docex compile`` time instead of at ``tofu apply``.
    reserved_names: list[str] = field(default_factory=list)
    # Per-foundation ordered list of emit destinations. First entry =
    # default target (where `defaults:` and any field translation
    # without an explicit `target:` lands). Subsequent entries are
    # alternative destinations selectable via `target:` on a field
    # translation. See transfer_tables.md § emits.
    emits: dict[str, list[str]] = field(default_factory=dict)

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

    def default_target(self, foundation: str) -> str:
        """Return the engine's default emit destination for ``foundation``.

        Raises TransferTableError if the engine declares no `emits:` for
        that foundation. Every engine that supports a foundation must
        declare a non-empty emits list for it — checked by validation.
        """
        targets = (self.emits or {}).get(foundation) or []
        if not targets:
            raise TransferTableError(
                f"engine {self.engine!r} of role {self.role!r}: no `emits:` "
                f"declared for foundation {foundation!r}. Every engine must "
                f"declare at least one emit destination per supported "
                f"foundation."
            )
        return targets[0]

    def field_translation(
        self, field_name: str, foundation: str
    ) -> tuple[str, dict[str, Any]] | None:
        """Resolve a role-specific field translation to (target, body).

        Returns ``None`` if the engine doesn't define the field for this
        foundation. The ``target`` is the field's explicit ``target:``
        when set, otherwise the engine's default target for this
        foundation. The ``body`` is the translation YAML *minus* the
        ``target:`` key.
        """
        f = (self.fields or {}).get(field_name)
        if f is None:
            return None
        per_foundation = f.get(foundation)
        if per_foundation is None:
            return None
        if not isinstance(per_foundation, dict):
            return None
        body = dict(per_foundation)
        target = body.pop("target", None) or self.default_target(foundation)
        return (target, body)


@dataclass
class TransferTables:
    """Loaded transfer tables exposed as a queryable object."""

    # role_name -> engine_name -> EngineEntry
    by_role: dict[str, dict[str, EngineEntry]]
    # role_name -> human-readable description, from the reserved role-level
    # `description:` key in the transfer table (optional).
    descriptions: dict[str, str] = field(default_factory=dict)
    # Top-level naming policies (canonical AWS-resource-type rules);
    # engines reference one by name via ``EngineEntry.naming``.
    naming_policies: NamingPolicies = field(
        default_factory=lambda: NamingPolicies(by_name={})
    )

    def roles(self) -> list[str]:
        """All known role names, sorted."""
        return sorted(self.by_role)

    def description(self, role_name: str) -> str | None:
        """The human description for a role, if the table declares one."""
        return self.descriptions.get(role_name)

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
    naming_ref = raw.get("naming")
    if not isinstance(naming_ref, str) or not naming_ref:
        raise TransferTableError(
            f"role {role!r} engine {engine!r}: `naming:` must be a string "
            f"naming-policy reference (got {naming_ref!r}). "
            f"See transfer_tables.md § Naming Policies."
        )
    raw_emits = raw.get("emits") or {}
    if not isinstance(raw_emits, dict):
        raise TransferTableError(
            f"role {role!r} engine {engine!r}: `emits:` must be a "
            f"mapping of foundation -> list of destinations"
        )
    emits: dict[str, list[str]] = {}
    for fnd, targets in raw_emits.items():
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            raise TransferTableError(
                f"role {role!r} engine {engine!r}: `emits.{fnd}:` must be "
                f"a list of destination name strings"
            )
        emits[fnd] = list(targets)
    return EngineEntry(
        role=role,
        engine=engine,
        foundation=foundation,
        defaults=raw.get("defaults", {}) or {},
        fields=raw.get("fields", {}) or {},
        provides=raw.get("provides", {}) or {},
        env=raw.get("env", {}) or {},
        naming=naming_ref,
        default_port=raw.get("default_port"),
        reserved_names=[
            # YAML 1.1 parses bare ``true`` / ``false`` / ``on`` as
            # booleans; coerce to lowercase strings so the
            # case-insensitive identifier match works regardless of how
            # the operator wrote them in the table.
            str(item).lower()
            for item in (raw.get("reserved_names") or [])
        ],
        emits=emits,
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
            if "roles" in doc and isinstance(doc["roles"], dict):
                raw_merged = _deep_merge(raw_merged, {"roles": doc["roles"]})
            if "naming_policies" in doc and isinstance(doc["naming_policies"], dict):
                raw_merged = _deep_merge(
                    raw_merged, {"naming_policies": doc["naming_policies"]}
                )

    policies = parse_policies(raw_merged.get("naming_policies", {}))

    by_role: dict[str, dict[str, EngineEntry]] = {}
    descriptions: dict[str, str] = {}
    for role, engines in (raw_merged.get("roles") or {}).items():
        if not isinstance(engines, dict):
            raise TransferTableError(
                f"role {role!r}: expected a mapping of engine name -> entry"
            )
        for engine, raw_entry in engines.items():
            if engine == "description":
                # Reserved role-level key: a human description, not an engine.
                if isinstance(raw_entry, str):
                    descriptions[role] = raw_entry
                continue
            if not isinstance(raw_entry, dict):
                raise TransferTableError(
                    f"role {role!r} engine {engine!r}: expected a mapping"
                )
            entry = _parse_entry(role, engine, raw_entry)
            # Cross-validate the naming ref against the policy table.
            policies.get(entry.naming)
            by_role.setdefault(role, {})[engine] = entry
    return TransferTables(
        by_role=by_role,
        descriptions=descriptions,
        naming_policies=policies,
    )
