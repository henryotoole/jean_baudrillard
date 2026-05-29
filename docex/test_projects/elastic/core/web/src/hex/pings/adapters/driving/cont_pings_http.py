"""ContPingsHttp — FastAPI router exposing the `pings` module over HTTP."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hex.pings.ports.driving.cont_pings import ContPings


class _CreatePingRequest(BaseModel):
    payload: str


class _CreatePingResponse(BaseModel):
    id: str


class ContPingsHttp:
    """HTTP adapter for ContPings.

    Owns a FastAPI APIRouter that the composition root mounts on the app.
    """

    def __init__(self, service: ContPings) -> None:
        self._service = service
        self.router = APIRouter()
        self.router.add_api_route(
            "/pings",
            self._create,
            methods=["POST"],
            status_code=201,
            response_model=_CreatePingResponse,
        )

    def _create(self, body: _CreatePingRequest) -> _CreatePingResponse:
        try:
            ping = self._service.create(payload=body.payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _CreatePingResponse(id=str(ping.id))
