from hex.links.domain.short_link import ShortLink
from hex.links.ports.driven.repo_short_link import RepoShortLink


class RepoShortLinkMemory(RepoShortLink):
    """In-process dict-backed store. Suitable for dev and tests only."""

    def __init__(self) -> None:
        self._by_code: dict[str, ShortLink] = {}

    def save(self, link: ShortLink) -> None:
        self._by_code[link.code] = link

    def get_by_code(self, code: str) -> ShortLink | None:
        return self._by_code.get(code)
