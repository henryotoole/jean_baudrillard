from hex.analytics.ports.driving.cont_analytics import ContAnalytics


class ContAnalyticsHttp:
    """Translates analytics HTTP routes into ContAnalytics port calls.

    Framework wiring is omitted in this fixture; the methods model the two
    routes the module exposes.
    """

    def __init__(self, service: ContAnalytics) -> None:
        self._service = service

    def post_click(self, code: str) -> dict:
        self._service.record_click(code)
        return {"status": 204}

    def get_count(self, code: str) -> dict:
        return {"code": code, "clicks": self._service.click_count(code)}
