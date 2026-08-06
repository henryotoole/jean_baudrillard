"""ContJobRunner — driving port for draining the deferred-job queue.

The perform side. `api.worker`'s poll loop drives this once per iteration;
`ContJobs` (the defer side) is what the clock drives. Two ports because
they are two use cases with two consumers, not one use case seen twice.
"""

from __future__ import annotations

from typing import Protocol


class ContJobRunner(Protocol):
    def run_once(self) -> int:
        """Claim and perform one batch of jobs; return the number performed."""
        ...
