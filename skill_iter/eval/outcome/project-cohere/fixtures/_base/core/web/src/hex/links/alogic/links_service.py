import secrets
import string

from hex.links.domain.short_link import CODE_LENGTH, ShortLink
from hex.links.ports.driving.cont_links import ContLinks
from hex.links.ports.driven.repo_short_link import RepoShortLink

_ALPHABET = string.ascii_letters + string.digits


class LinksService(ContLinks):
    """Orchestrates code generation and persistence for short links."""

    def __init__(self, repo: RepoShortLink) -> None:
        self._repo = repo

    def shorten(self, target_url: str) -> str:
        code = self._generate_code()
        self._repo.save(ShortLink(code=code, target_url=target_url))
        return code

    def resolve(self, code: str) -> str | None:
        link = self._repo.get_by_code(code)
        return link.target_url if link is not None else None

    def _generate_code(self) -> str:
        return "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
