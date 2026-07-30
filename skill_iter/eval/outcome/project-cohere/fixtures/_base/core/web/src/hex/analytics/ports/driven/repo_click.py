from abc import ABC, abstractmethod


class RepoClick(ABC):
    """Driven port: persistence for click tallies."""

    @abstractmethod
    def record(self, code: str) -> None:
        ...

    @abstractmethod
    def count(self, code: str) -> int:
        """Total clicks recorded for code (0 if none)."""
