"""GwyJobRunner — driven port for asking `api.worker` to drain the queue.

The canonical **Gateway** pattern
(hex_overview.md § Driven Port / Adapter Patterns): it encapsulates access to
an external system. `api.worker` shares this module's source, this image, and
this database — but it is a DIFFERENT PROCESS reached over the network, and
from `api.web`'s side that is exactly what a gateway is for. A port is drawn
around what the module has to reach across, not around what happens to be
compiled into the same artifact.

Held by `JobDrainService` and satisfied at runtime by `GwyJobRunnerHttp`,
which the composition root injects. This is the seam that keeps `api.web`'s
application logic from knowing that HTTP, a hostname, or a sibling core
service exists at all.
"""

from __future__ import annotations

from typing import Protocol


class GwyJobRunner(Protocol):
    def drain_now(self) -> int:
        """Ask `api.worker` to drain the queue now; return the number of jobs performed."""
        ...
