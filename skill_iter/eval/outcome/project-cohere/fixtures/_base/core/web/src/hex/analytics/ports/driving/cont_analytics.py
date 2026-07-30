from abc import ABC, abstractmethod


class ContAnalytics(ABC):
    """Driving port: the operations the analytics module offers."""

    @abstractmethod
    def record_click(self, code: str) -> None:
        """Record one click (hit) against a short code."""

    @abstractmethod
    def click_count(self, code: str) -> int:
        """Return the total number of clicks recorded for a short code."""
