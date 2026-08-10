"""JobDrainService — application logic implementing ContJobDrain.

**This is a one-line delegation, and that is correct.** The file is thin
because the operation genuinely is thin: `api.web` asks the worker to drain,
and there is no orchestration, no domain rule, and no sequencing to perform in
between. Inventing logic here to justify the file's existence would be adding
behaviour the project does not have, which is worse than a short method.

What the layer buys is not code, it is placement. The alogic tier is where an
operation is *named* and where the driving port is *implemented*
(hex_overview.md § Layers), and the port/adapter pairs on either side are what
carry the design: `ContJobDrain` in front, `GwyJobRunner` behind. This class is
the seam that keeps `api.web`'s controller from knowing that a sibling process
exists — the controller calls a port, the port is implemented here, and only
`GwyJobRunnerHttp` has ever heard of a hostname.

Note what this service does NOT do: it does not read the queue, it does not
perform a job, and it does not judge the count it gets back. `performed: 0` is
passed through untouched, because whether an empty drain is interesting is the
caller's question, not this layer's.
"""

from __future__ import annotations

from hex.jobs.ports.driven.gwy_job_runner import GwyJobRunner


class JobDrainService:
    def __init__(self, gateway: GwyJobRunner) -> None:
        self._gateway = gateway

    def drain_now(self) -> int:
        return self._gateway.drain_now()
