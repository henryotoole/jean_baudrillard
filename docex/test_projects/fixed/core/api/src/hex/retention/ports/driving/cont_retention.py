"""ContRetention — driving port for the prune use case.

This is the one port another hex module is allowed to import: `jobs`'
runner holds a `ContRetention` and the composition root injects the
`RetentionService` behind it. A *driving* port is the single legal
cross-module import (internal_dependency_rules.md § Cross-Module Imports).
"""

from __future__ import annotations

from typing import Protocol


class ContRetention(Protocol):
    def prune(self) -> int:
        """Prune expired processed pings. Returns rows deleted."""
        ...
