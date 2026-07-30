from abc import ABC, abstractmethod

from hex.links.domain.short_link import ShortLink


class RepoShortLink(ABC):
    """Driven port: persistence for ShortLink aggregates."""

    @abstractmethod
    def save(self, link: ShortLink) -> None:
        ...

    @abstractmethod
    def get_by_code(self, code: str) -> ShortLink | None:
        """Return the stored link for code, or None on miss."""
