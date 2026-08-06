"""ContJobsHttp — FastAPI router exposing ContJobs over HTTP.

**One route per job, and no dispatch table here — deliberately.** A route
is not a name lookup. `POST /jobs/{name}` would be one line shorter and
would make the OpenAPI contract meaningless: a contract that says "some
job, named at runtime" describes nothing a consumer can rely on and
nothing `docex check`'s contract gate can verify. So each job gets its own
route calling its own port method directly.

These routes reach the SAME driving port the clock fires, which is the
side effect clock.md § Architecture calls out: firing a scheduled job by
hand in `dev` is an ordinary HTTP call, not a special path.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hex.jobs.ports.driving.cont_jobs import ContJobs


class _DeferredJobResponse(BaseModel):
    job_id: str


class ContJobsHttp:
    """HTTP adapter for ContJobs.

    Owns a FastAPI APIRouter that the composition root mounts on the app.
    """

    def __init__(self, service: ContJobs) -> None:
        self._service = service
        self.router = APIRouter()
        self.router.add_api_route(
            "/jobs/prune_pings",
            self._prune_pings,
            methods=["POST"],
            status_code=202,
            response_model=_DeferredJobResponse,
        )
        self.router.add_api_route(
            "/jobs/heartbeat",
            self._heartbeat,
            methods=["POST"],
            status_code=202,
            response_model=_DeferredJobResponse,
        )

    def _prune_pings(self) -> _DeferredJobResponse:
        """Defer a prune of expired processed pings.

        Takes no body. Returns 202 with the enqueued job's id; the work
        itself happens later, in `api.worker`. A 503 means the queue could
        not be written — nothing was deferred and the caller may retry.

        Returns:
            `{"job_id": "<uuid>"}` with status 202.
        """
        return self._defer(self._service.prune_pings)

    def _heartbeat(self) -> _DeferredJobResponse:
        """Defer a no-op liveness job.

        Takes no body. Returns 202 with the enqueued job's id. Exists so
        the defer → drain path can be exercised by hand without waiting for
        a cron tick. A 503 means the queue could not be written.

        Returns:
            `{"job_id": "<uuid>"}` with status 202.
        """
        return self._defer(self._service.heartbeat)

    def _defer(self, port_method) -> _DeferredJobResponse:
        try:
            job_id = port_method()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"could not enqueue: {exc}")
        return _DeferredJobResponse(job_id=str(job_id))
