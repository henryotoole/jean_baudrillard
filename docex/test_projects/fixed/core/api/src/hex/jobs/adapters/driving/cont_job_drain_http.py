"""ContJobDrainHttp — `POST /jobs/drain` on `api.web`.

The consumer-side entry point of the one cross-core-service call either seed
makes. It sits on `api.web`'s `rest` surface
(`infra/contracts/api.web.rest.openapi.yml`) and translates an inbound HTTP
request into a `ContJobDrain` port call — nothing more. It does not know that
the port is satisfied over the network, which is the entire point of the
gateway behind it.

Together with `GwyJobRunner`, `GwyJobRunnerHttp`, `ContJobDrain`, and
`JobDrainService`, this file is one fifth of the doctrine's worked example of a
**consumer-side gateway onto a sibling core service** — the shape rule 32's
positive arm exists to govern. Five files for one call is the honest tax for a
clean hexagon: the alternative is an HTTP call written directly in `root.py`,
which is what this codebase used to do and what mod 129 deleted.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hex.jobs.ports.driving.cont_job_drain import ContJobDrain


class _DrainResult(BaseModel):
    performed: int


class ContJobDrainHttp:
    """HTTP adapter for ContJobDrain.

    Owns a FastAPI APIRouter that the composition root mounts on the app.
    """

    def __init__(self, service: ContJobDrain) -> None:
        self._service = service
        self.router = APIRouter()
        self.router.add_api_route(
            "/jobs/drain",
            self._drain,
            methods=["POST"],
            status_code=200,
            response_model=_DrainResult,
        )

    def _drain(self) -> _DrainResult:
        """Ask `api.worker` to drain the deferred-job queue now.

        Takes no body. Exists because the perform side of the queue belongs to
        `api.worker`: this edge asks, and the worker does the work in its own
        process.

        **`performed: 0` is a SUCCESS, not an error.** The worker's own poll
        loop drains on its interval, so finding the queue already empty is the
        ordinary outcome of asking at the wrong moment. A caller that treats 0
        as a failure is asserting on scheduling.

        Returns:
            `{"performed": N}` with status 200, N >= 0.

        Raises:
            HTTPException: 503 if `api.worker` could not be reached, in which
                case **nothing was drained**. The caller may retry, and the
                worker's own poll loop will drain the queue regardless.
        """
        try:
            performed = self._service.drain_now()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"worker unreachable: {exc}")
        return _DrainResult(performed=performed)
