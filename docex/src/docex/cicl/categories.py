"""Source-key categorization — the single source of truth for which of the
three configurable-value categories (TTE / secret / config) each source key
belongs to. Pure function of (infra.yml, transfer tables); no values, no
per-env state, no I/O. See config_and_secrets.md § The Three Categories and
cicl.md validation rule 20.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from docex.cicl.model import CICLDocument
from docex.cicl.transfer import TransferTables

# Secrets docex injects itself (not declared by any project service). Reserved:
# a project may not redeclare these in any category. Single source of truth —
# emit/secrets.py may import this in a later cleanup.
DOCTRINE_INJECTED_SECRETS: frozenset[str] = frozenset({"TELEMETRY_API_KEY"})


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
