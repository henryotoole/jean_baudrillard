"""ContJobRunnerHttp — `api.worker`'s `rpc` surface, over the existing
ContJobRunner driving port.

**This is a surface, declared as one.** `api.worker` carries
`surfaces: {rpc: {api_styles: [rpc]}, events: {api_styles: [events]}}` in
`infra.yml`, and this adapter is the whole of the first of those two. Its
contract is `infra/contracts/api.worker.rpc.asyncapi.yml`; declaring the
surface is what makes this core service a provider and what lets `api.web`
name it in `uses:` at all (cicl.md § Surfaces).

**Why the boundary crosses a process edge at all**, which is the reader's
first fair objection given that `api.web` shares this module's source: the
PERFORM side of the queue belongs to `api.worker`. An HTTP edge that drained
the queue in its own process — with its own sizing, its own replica count,
and its own request-scoped lifetime — would be performing rather than
deferring, which is precisely the violation
`clock.md § The clock defers; it does not work` forbids of the clock one core
service over. The clock defers and the edge defers; only the worker performs.
`api.web` asks, and this is where the asking lands.

`Http` is the *mechanism* suffix (hex_overview.md § Controller Mechanism) and
`rpc` is the *api_style* (cicl.md § Surfaces). They are different axes and
the doctrine keys the contract FORMAT on the second, which is why a request/
reply boundary spoken over HTTP is described by an AsyncAPI document rather
than an OpenAPI one. This is the case MCP made, and this adapter shares it.

**Concurrency, and why there is no lock.** This router is served from a daemon
thread in `entrypoints/worker.py` while the poll loop drains the same queue on
its own interval, so two callers in one process can be mid-drain at once.
That is safe for a reason already written down rather than a new one:
`QueueJobsPostgres` opens a connection per call and `claim` takes its batch
with `SELECT ... FOR UPDATE SKIP LOCKED`, which is the same guarantee that
makes `replicas: 2` safe against itself. A second in-process caller is that
identical race under a shorter name. **Do not add a lock** — it would
serialize the drain without making it any more correct.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hex.jobs.ports.driving.cont_job_runner import ContJobRunner


class _DrainResult(BaseModel):
    performed: int


class ContJobRunnerHttp:
    """HTTP-mechanism adapter for ContJobRunner.

    Owns a FastAPI APIRouter that `entrypoints/worker.py` mounts on the
    `rpc` surface's app. The runtime host is not an adapter
    (internal_dependency_rules.md § Entrypoints, rule 2), so this class
    builds no server and binds no socket.
    """

    def __init__(self, service: ContJobRunner) -> None:
        self._service = service
        self.router = APIRouter()
        self.router.add_api_route(
            "/drain",
            self._drain,
            methods=["POST"],
            status_code=200,
            response_model=_DrainResult,
        )

    def _drain(self) -> _DrainResult:
        """Claim and perform one batch of deferred jobs now.

        Takes no body. Called by `api.web` when a caller asks for the queue
        to be drained without waiting for this core service's next poll.

        **`performed: 0` is a SUCCESS, not an error.** This core service's own
        loop drains on its interval, so finding the queue already empty is the
        ordinary outcome of asking at the wrong moment. A caller that treats 0
        as a failure is asserting on scheduling, which is not something this
        boundary promises.

        Returns:
            `{"performed": N}` with status 200, N >= 0.

        Raises:
            HTTPException: 503 if the batch could not be claimed at all —
                the queue was unreachable and nothing was performed.
        """
        try:
            performed = self._service.run_once()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"could not drain: {exc}")
        return _DrainResult(performed=performed)
