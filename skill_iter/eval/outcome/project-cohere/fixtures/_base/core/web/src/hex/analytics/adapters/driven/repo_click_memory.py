from collections import defaultdict

from hex.analytics.ports.driven.repo_click import RepoClick


class RepoClickMemory(RepoClick):
    """In-process tally store. Every record increments a running total for the
    code — clicks are NOT de-duplicated by visitor."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)

    def record(self, code: str) -> None:
        self._counts[code] += 1

    def count(self, code: str) -> int:
        return self._counts.get(code, 0)
