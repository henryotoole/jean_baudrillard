"""ContJobDrain — driving port for asking the worker to drain the queue.

**Why this is a separate port rather than a `drain()` method on `ContJobs`**,
which would save three files and is the first thing a reader will propose:
`ContJobs` is the port **`api.clock` holds**. Adding a drain method to it would
hand the clock the ability to trigger performance, and a clock that can trigger
performance is one refactor away from performing — which is exactly what
`clock.md § The clock defers; it does not work` forbids and what the rest of
this module spends its comments protecting. The three extra files are the
cheaper mistake to avoid.

The two ports are two use cases with two consumers, not one use case seen
twice — the same reasoning that already separates `ContJobs` (defer) from
`ContJobRunner` (perform).

Implemented by `JobDrainService` and driven by `ContJobDrainHttp` on
`api.web`.
"""

from __future__ import annotations

from typing import Protocol


class ContJobDrain(Protocol):
    def drain_now(self) -> int:
        """Ask the worker to drain the deferred-job queue now; return the count performed."""
        ...
