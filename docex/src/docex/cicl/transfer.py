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


# Strict allowlists for transfer-table schema validation. Per
# transfer_tables.md § Failure-mode contract, anything outside these sets
# is rejected at load time. Adding to these is a doctrine change (extend
# the schema), not a permissive workaround.

_ALLOWED_TOPLEVEL_KEYS: frozenset[str] = frozenset({
    "roles",
    "naming_policies",
})

# Role-level keys reserved for metadata. Anything else under a role is
# treated as an engine name (since engine names are user-defined).
_RESERVED_ROLE_KEYS: frozenset[str] = frozenset({
    "description",
})

# Engine-entry sub-keys. Must match `_parse_entry`'s consumed set
# exactly. Mod 015 will add `persistent_storage` here when EFS lands.
_ALLOWED_ENGINE_KEYS: frozenset[str] = frozenset({
    "foundation",
    "default_port",
    "emits",
    "defaults",
    "fields",
    "provides",
    "env",
    "naming",
    "reserved_names",
})


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


def _levenshtein(a: str, b: str) -> int:
    """Iterative Levenshtein edit distance. Two short strings — O(len(a)*len(b))."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _did_you_mean(needle: str, haystack: frozenset[str] | set[str]) -> str:
    """Return a `— did you mean 'X'?` suffix, or a `— allowed: ...` list.

    Cutoff of edit distance 2 keeps suggestions tight. Below that, list
    the full allowlist so the developer sees the schema.
    """
    if not haystack:
        return ""
    closest = min(haystack, key=lambda k: _levenshtein(needle, k))
    if _levenshtein(needle, closest) <= 2:
        return f" — did you mean {closest!r}?"
    return f" — allowed: {', '.join(sorted(haystack))}"


def _display_path(path: Path, root: Path, kind: str) -> str:
    """Render a YAML file path as a developer-friendly relative form.

    For bundled tables: ``tables/<rel>``.
    For project-local tables: ``infra/transfer_tables/<rel>``.

    `kind` is 'bundled' or 'project'. `root` is the layer root the file
    was discovered under.
    """
    rel = path.relative_to(root)
    if kind == "bundled":
        return f"tables/{rel}"
    if kind == "project":
        return f"infra/transfer_tables/{rel}"
    return str(path)


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


def _validate_file(display_path: str, doc: dict[str, Any]) -> None:
    """Strictly validate one transfer-table YAML doc's schema shape.

    Walks the doc top-down, raising TransferTableError with source path
    attribution on any unknown key, malformed structure, or invalid value.
    Does not construct typed objects — that happens after merging.
    """
    # Top-level keys.
    for key in doc:
        if key not in _ALLOWED_TOPLEVEL_KEYS:
            raise TransferTableError(
                f"{display_path}: unknown top-level key {key!r}"
                + _did_you_mean(key, _ALLOWED_TOPLEVEL_KEYS)
            )

    # naming_policies block.
    policies = doc.get("naming_policies") or {}
    if not isinstance(policies, dict):
        raise TransferTableError(
            f"{display_path}: `naming_policies:` must be a mapping"
        )
    for policy_name, body in policies.items():
        if not isinstance(body, dict):
            raise TransferTableError(
                f"{display_path}: naming_policies.{policy_name}: "
                f"must be a mapping"
            )
        # Delegate sub-key validation to naming.py — same code path
        # that parses bundled policies. Pass display_path so errors
        # attribute correctly.
        from docex.naming import _validate_policy_keys
        _validate_policy_keys(display_path, policy_name, body)

    # roles block.
    roles = doc.get("roles") or {}
    if not isinstance(roles, dict):
        raise TransferTableError(
            f"{display_path}: `roles:` must be a mapping"
        )
    for role_name, role_body in roles.items():
        if not isinstance(role_body, dict):
            raise TransferTableError(
                f"{display_path}: roles.{role_name}: must be a mapping"
            )
        for child_key, child_body in role_body.items():
            if child_key in _RESERVED_ROLE_KEYS:
                if child_key == "description" and not isinstance(child_body, str):
                    raise TransferTableError(
                        f"{display_path}: roles.{role_name}.description: "
                        f"must be a string"
                    )
                continue
            # Otherwise it's an engine.
            _validate_engine_entry(
                display_path, role_name, child_key, child_body
            )


def _validate_engine_entry(
    display_path: str,
    role: str,
    engine: str,
    raw: Any,
) -> None:
    """Strictly validate one engine entry's schema, per-file.

    WHY (per-file vs merged): a project-local table is allowed to be a
    partial override of a bundled engine (e.g. tweak `defaults.elastic`
    only). Such a fragment legitimately omits `foundation:` and
    `naming:` — those come from the bundled half. So per-file
    validation only enforces what is *present*: it rejects unknown
    sub-keys, rejects malformed `emits:` structure, and rejects bad
    `emits:` destination values. Required-field existence is checked
    after merge in _parse_entry's caller.
    """
    if not isinstance(raw, dict):
        raise TransferTableError(
            f"{display_path}: roles.{role}.{engine}: must be a mapping"
        )
    # Unknown sub-keys.
    for key in raw:
        if key not in _ALLOWED_ENGINE_KEYS:
            raise TransferTableError(
                f"{display_path}: roles.{role}.{engine}: unknown key {key!r}"
                + _did_you_mean(key, _ALLOWED_ENGINE_KEYS)
            )
    # foundation value (only if present — a partial override may omit it).
    if "foundation" in raw and raw["foundation"] not in ("fixed", "elastic", "both"):
        raise TransferTableError(
            f"{display_path}: roles.{role}.{engine}.foundation: must be "
            f"'fixed', 'elastic', or 'both' (got {raw['foundation']!r})"
        )
    # naming value (only if present — partial overrides may omit).
    if "naming" in raw:
        naming_ref = raw["naming"]
        if not isinstance(naming_ref, str) or not naming_ref:
            raise TransferTableError(
                f"{display_path}: roles.{role}.{engine}.naming: "
                f"must be a non-empty string naming-policy reference "
                f"(got {naming_ref!r})"
            )
    # emits: structure + destination values (only when present).
    if "emits" in raw:
        raw_emits = raw["emits"] or {}
        if not isinstance(raw_emits, dict):
            raise TransferTableError(
                f"{display_path}: roles.{role}.{engine}.emits: must be a "
                f"mapping of foundation -> list of destinations"
            )
        for fnd, targets in raw_emits.items():
            if fnd not in EMIT_DESTINATIONS:
                raise TransferTableError(
                    f"{display_path}: roles.{role}.{engine}.emits.{fnd}: "
                    f"unknown foundation {fnd!r} — allowed: "
                    f"{', '.join(sorted(EMIT_DESTINATIONS))}"
                )
            if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
                raise TransferTableError(
                    f"{display_path}: roles.{role}.{engine}.emits.{fnd}: "
                    f"must be a list of destination name strings"
                )
            valid_dests = EMIT_DESTINATIONS[fnd]
            for dest in targets:
                if dest not in valid_dests:
                    raise TransferTableError(
                        f"{display_path}: roles.{role}.{engine}.emits.{fnd}: "
                        f"unknown destination {dest!r}"
                        + _did_you_mean(dest, valid_dests)
                    )


def _parse_entry(role: str, engine: str, raw: dict[str, Any]) -> EngineEntry:
    # WHY: schema-shape and emit-destination validation ran in
    # _validate_file during the per-file pass. This runs after deep
    # merge across layers and only enforces required-field existence —
    # which can't be checked per-file because a project-local override
    # may legitimately be a partial patch of a bundled engine.
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
    emits: dict[str, list[str]] = {
        fnd: list(targets) for fnd, targets in raw_emits.items()
    }
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

    layers: list[tuple[Path, str]] = []
    bundled_root = _bundled_tables_root()
    if bundled_root is not None:
        layers.append((bundled_root, "bundled"))
    proj_root = _project_tables_root(project_root)
    if proj_root is not None:
        layers.append((proj_root, "project"))

    for layer_root, kind in layers:
        for path, doc in _read_yaml_files(layer_root):
            display_path = _display_path(path, layer_root, kind)
            # WHY: validate-then-merge. Per-file validation gives source
            # attribution; the merge accumulates already-validated data.
            _validate_file(display_path, doc)
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
        for engine, raw_entry in engines.items():
            if engine == "description":
                # Reserved role-level key: a human description, not an engine.
                if isinstance(raw_entry, str):
                    descriptions[role] = raw_entry
                continue
            entry = _parse_entry(role, engine, raw_entry)
            # Cross-validate the naming ref against the policy table.
            # No source-path attribution here — the entry could come
            # from multiple files via deep merge, but role+engine is
            # enough for the developer to grep their tables.
            try:
                policies.get(entry.naming)
            except TransferTableError as exc:
                raise TransferTableError(
                    f"roles.{role}.{engine}.naming: {exc}"
                ) from exc
            by_role.setdefault(role, {})[engine] = entry
    return TransferTables(
        by_role=by_role,
        descriptions=descriptions,
        naming_policies=policies,
    )
