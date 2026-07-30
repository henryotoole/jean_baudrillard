from hex.links.ports.driving.cont_links import ContLinks


class ContLinksHttp:
    """Translates HTTP requests into ContLinks port calls.

    Framework wiring is omitted in this fixture; the methods model the two
    routes the service exposes.
    """

    def __init__(self, service: ContLinks) -> None:
        self._service = service

    def post_shorten(self, body: dict) -> dict:
        code = self._service.shorten(body["target_url"])
        return {"code": code}

    def get_resolve(self, code: str) -> dict:
        target = self._service.resolve(code)
        if target is None:
            return {"status": 404}
        return {"status": 302, "location": target}
