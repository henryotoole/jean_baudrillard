"""ContReaper — driving port for the reap use case.

A scheduler job is triggered from the outside (Ofelia on fixed, an
EventBridge RunTask on elastic) via the CLI controller, which translates
that trigger into a single call against this port.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ContReaper(ABC):
    @abstractmethod
    def reap(self) -> int:
        """Prune expired processed pings. Returns rows deleted."""
        raise NotImplementedError
