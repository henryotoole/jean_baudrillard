from abc import ABC, abstractmethod


class ContLinks(ABC):
    """Driving port: the operations the links module offers to the outside."""

    @abstractmethod
    def shorten(self, target_url: str) -> str:
        """Create a short code for target_url and return the code."""

    @abstractmethod
    def resolve(self, code: str) -> str | None:
        """Return the target URL for code, or None if no such code exists."""
