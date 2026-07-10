"""Source-key categorization — the single source of truth for which of the
three configurable-value categories (TTE / secret / config) each source key
belongs to. Pure function of (infra.yml, transfer tables); no values, no
per-env state, no I/O. See config_and_secrets.md § The Three Categories and
cicl.md validation rule 20.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from docex.cicl.generate import GenerationPolicy
from docex.cicl.model import CICLDocument
from docex.cicl.transfer import TransferTables

# Secrets docex injects itself (not declared by any project service). Reserved:
# a project may not redeclare these in any category. Single source of truth —
# emit/secrets.py may import this in a later cleanup.
DOCTRINE_INJECTED_SECRETS: frozenset[str] = frozenset({"TELEMETRY_API_KEY"})

# desc + source for each doctrine-injected secret (single source of truth;
# replaces emit/secrets.py's hardcoded TELEMETRY_API_KEY comment).
_DOCTRINE_INJECTED_SECRET_META: dict[str, tuple[str, str]] = {
    "TELEMETRY_API_KEY": (
        "doctrine",
        "The OTel collector sidecar's auth key against observability_backend_url. "
        "Required in stage/prod; dev/test sidecars use the debug exporter and ignore it.",
    ),
}


@dataclass(frozen=True)
class ManifestEntry:
    key: str
    desc: str
    source: str   # declaring service name, or "doctrine"


def secret_manifest(
    doc: CICLDocument, tables: TransferTables
) -> list[ManifestEntry]:
    """Every required secret: key + description + declaring source. The single
    source of truth for ``example.env``, ``secrets scaffold``, and
    ``secrets status``. Order: doctrine-injected first, then core services
    (sorted), then backing services (sorted). A key shared across services
    keeps its first source + desc (dedup)."""
    out: list[ManifestEntry] = []
    seen: set[str] = set()

    def add(key: str, desc: str, source: str) -> None:
        if key in seen:
            return
        seen.add(key)
        out.append(ManifestEntry(key, desc, source))

    for key in sorted(DOCTRINE_INJECTED_SECRETS):
        src_meta = _DOCTRINE_INJECTED_SECRET_META.get(key, ("doctrine", ""))
        source, desc = src_meta
        add(key, desc, source)
    for name in sorted(doc.core_services):
        for k, desc in sorted((doc.core_services[name].secrets or {}).items()):
            add(k, desc, name)
    for name in sorted(doc.backing_services):
        svc = doc.backing_services[name]
        cands = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        for cand in cands:
            try:
                entry = tables.engine(svc.role, cand)
            except Exception:
                continue
            for k, spec in (entry.env or {}).items():
                if spec.kind == "secret":
                    add(k, spec.desc, name)
    return out


def config_manifest(
    doc: CICLDocument, tables: TransferTables
) -> list[ManifestEntry]:
    """Every declared config key: key + description + declaring core service.
    Config is core-service-declared only — no doctrine-injected, no backing
    engine vars. Source = the declaring service. (``tables`` is unused but kept
    for signature symmetry with ``secret_manifest`` so the engine can call
    either uniformly.)"""
    out: list[ManifestEntry] = []
    seen: set[str] = set()
    for name in sorted(doc.core_services):
        for k, desc in sorted((doc.core_services[name].config or {}).items()):
            if k in seen:
                continue
            seen.add(k)
            out.append(ManifestEntry(k, desc, name))
    return out


class Category(str, Enum):
    TTE = "tte"
    SECRET = "secret"
    CONFIG = "config"


@dataclass(frozen=True)
class SourceKeyCategories:
    tte: frozenset[str]
    secret: frozenset[str]
    config: frozenset[str]

    def all_keys(self) -> frozenset[str]:
        return self.tte | self.secret | self.config

    def conflicts(self) -> dict[str, list[Category]]:
        """Keys claimed by more than one category (rule 20 violations)."""
        out: dict[str, list[Category]] = {}
        for key in self.tte | self.secret | self.config:
            cats = [c for c, s in (
                (Category.TTE, self.tte),
                (Category.SECRET, self.secret),
                (Category.CONFIG, self.config),
            ) if key in s]
            if len(cats) > 1:
                out[key] = cats
        return out

    def category_of(self, key: str) -> Category | None:
        """The single category of a key. Assumes disjointness (validated at
        compile via rule 20); if a key is in multiple sets this returns the
        first by TTE<SECRET<CONFIG precedence — callers run after validation."""
        if key in self.tte:
            return Category.TTE
        if key in self.secret:
            return Category.SECRET
        if key in self.config:
            return Category.CONFIG
        return None


def classify_source_keys(
    doc: CICLDocument, tables: TransferTables
) -> SourceKeyCategories:
    tte: set[str] = set()
    secret: set[str] = set(DOCTRINE_INJECTED_SECRETS)
    config: set[str] = set()

    # Backing engine env vars — union across candidate engines (foundation-
    # agnostic), split by kind. `fixed` vars are inlined at compile and enter
    # no store, so they are excluded from every category.
    for _name, svc in doc.backing_services.items():
        cands = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        for cand in cands:
            try:
                entry = tables.engine(svc.role, cand)
            except Exception:
                continue
            for var_name, spec in (entry.env or {}).items():
                if spec.kind == "minted":
                    tte.add(var_name)
                elif spec.kind == "secret":
                    secret.add(var_name)
                # kind == "fixed": inlined, no store — skip.

    # Core service declarations.
    for _name, svc in doc.core_services.items():
        secret.update(svc.secrets or {})
        config.update(getattr(svc, "config", {}) or {})

    return SourceKeyCategories(
        tte=frozenset(tte), secret=frozenset(secret), config=frozenset(config)
    )


def minted_policies(
    doc: CICLDocument, tables: TransferTables
) -> dict[str, GenerationPolicy]:
    """minted source key -> its resolved GenerationPolicy. Used by ensure_tte.

    Reuses the same candidate-engine walk as ``classify_source_keys`` so the
    set of minted keys can never drift from the TTE category.
    """
    out: dict[str, GenerationPolicy] = {}
    for _name, svc in doc.backing_services.items():
        cands = svc.engine if isinstance(svc.engine, list) else [svc.engine]
        for cand in cands:
            try:
                entry = tables.engine(svc.role, cand)
            except Exception:
                continue
            for var_name, spec in (entry.env or {}).items():
                if spec.kind == "minted":
                    out[var_name] = tables.generation_policies.get(spec.policy)
    return out
