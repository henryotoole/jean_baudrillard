"""Entrypoint for the `prune` core service of the `reaper` codebase.

Run-to-completion: one reap pass, then exit with the adapter's status. No
tick and no health server — `scheduler` core services are **exempt** from
the health model (contracts.md § Self health). There is no long-running
container to probe, and a scheduler is never a `consumes` target; "did last
night's job run" is a telemetry question.

Launched by the trigger on each fire — Ofelia on fixed, an EventBridge
Scheduler → ECS RunTask on elastic.
"""

from __future__ import annotations

import logging
import sys

from root import build_reaper


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


if __name__ == "__main__":
    sys.exit(build_reaper().run_once())
