"""ContProcessor — driving port for the `processor` module."""

from __future__ import annotations

from typing import Protocol


class ContProcessor(Protocol):
    def run_once(self) -> int:
        """Process all currently-unprocessed pings; return the number processed."""
        ...
