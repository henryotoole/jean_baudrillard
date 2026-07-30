"""Composition root: the single place adapters and services are wired."""

from hex.analytics.adapters.driven.repo_click_memory import RepoClickMemory
from hex.analytics.adapters.driving.cont_analytics_http import ContAnalyticsHttp
from hex.analytics.alogic.analytics_service import AnalyticsService
from hex.links.adapters.driven.repo_short_link_memory import RepoShortLinkMemory
from hex.links.adapters.driving.cont_links_http import ContLinksHttp
from hex.links.alogic.links_service import LinksService


def build_links_controller() -> ContLinksHttp:
    repo = RepoShortLinkMemory()
    service = LinksService(repo=repo)
    return ContLinksHttp(service=service)


def build_analytics_controller() -> ContAnalyticsHttp:
    repo = RepoClickMemory()
    service = AnalyticsService(repo=repo)
    return ContAnalyticsHttp(service=service)
