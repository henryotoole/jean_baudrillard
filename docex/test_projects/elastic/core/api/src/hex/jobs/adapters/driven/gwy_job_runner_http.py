"""GwyJobRunnerHttp — calls `api.worker`'s `rpc` surface over HTTP.

The consumer half of the one cross-core-service call either seed makes, and
the reason three declarations in `infra.yml` are true rather than decorative.

**How the address arrives.** `WORKER_HOST` / `WORKER_PORT` are resolved by the
compiler from the five-segment magic refs
`${codebases.api.core_services.worker.{host,port}}`, declared on the `api.web`
core service's `env:` only. One env-var name resolves on both foundations —
docker network DNS on fixed, ECS Service Connect on elastic — so nothing in
this file branches on foundation and nothing in it knows which one it is
running on.

Those refs oblige two separate things, and this adapter is why both hold:

  - Holding a ref to `api.worker` obliges the `api.worker` entry in `api.web`'s
    `uses:` list (cicl.md validation rule 7). A ref implies an edge.
  - Holding a ref makes the worker DIRECTLY ADDRESSED, which is what obliges
    the worker's own `port:` under rule 32's positive arm. Without this call
    the worker would be reached only through the `jobs` table — the way
    `api.clock` reaches it — and would need no port at all.

The address is **injected**, never read from `os.environ` here. Only the
composition root reads the environment; an adapter that reached for a variable
itself would be a wiring decision hidden inside a module.

**Stdlib `urllib`, not `httpx`.** `httpx` is installed only in the
Dockerfile's `test` stage, so it is not importable in the image `api.web`
actually runs. `root.py` reaches for `urllib` for the same reason.

Failures are allowed to raise. The driving adapter on the other side of the
alogic translates any exception into a 503, which is `cont_jobs_http.py`'s
existing pattern; a bespoke exception type for one call site would be
ceremony.
"""

from __future__ import annotations

import json
import urllib.request

from hex.jobs.ports.driven.gwy_job_runner import GwyJobRunner


# Short and hard on purpose: an unreachable or wedged worker must fail this
# call fast rather than stall an inbound web request behind it.
_TIMEOUT_SECONDS = 5


class GwyJobRunnerHttp(GwyJobRunner):
    def __init__(self, host: str | None, port: str | int | None) -> None:
        self._host = host
        self._port = port

    def drain_now(self) -> int:
        if not self._host or not self._port:
            raise RuntimeError("WORKER_HOST/WORKER_PORT not set")
        request = urllib.request.Request(
            f"http://{self._host}:{self._port}/drain",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as resp:
            return int(json.loads(resp.read())["performed"])
