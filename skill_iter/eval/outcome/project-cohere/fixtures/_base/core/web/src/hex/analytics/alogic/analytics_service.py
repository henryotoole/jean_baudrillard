from hex.analytics.domain.click import Click
from hex.analytics.ports.driving.cont_analytics import ContAnalytics
from hex.analytics.ports.driven.repo_click import RepoClick


class AnalyticsService(ContAnalytics):
    """Records clicks and reports total click counts per short code."""

    def __init__(self, repo: RepoClick) -> None:
        self._repo = repo

    def record_click(self, code: str) -> None:
        Click(code=code)  # validate before persisting
        self._repo.record(code)

    def click_count(self, code: str) -> int:
        return self._repo.count(code)
