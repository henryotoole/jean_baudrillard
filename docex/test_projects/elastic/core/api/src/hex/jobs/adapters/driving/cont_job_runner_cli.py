"""ContJobRunnerCli — CLI-mechanism driving adapter for ContJobRunner.

Translation only: one invocation in, a performed count out. It owns no
loop, no signal handlers, and no sleep. The runtime host is not an adapter
(internal_dependency_rules.md § Entrypoints, rule 2), so the poll loop
that drives this adapter lives in `entrypoints/worker.py` — the same loop
that drives `ContProcessorCli`.
"""

from __future__ import annotations

import logging

from hex.jobs.ports.driving.cont_job_runner import ContJobRunner


logger = logging.getLogger(__name__)


class ContJobRunnerCli:
    def __init__(self, service: ContJobRunner) -> None:
        self._service = service

    def run_once(self) -> int:
        # WHY: no try/except here. An adapter that swallowed the exception
        # would report "0 performed" for a *failed* iteration, and the
        # entrypoint's loop must tell those apart — it may only bump the
        # liveness tick on a genuine pass.
        performed = self._service.run_once()
        if performed:
            logger.info("jobs: performed %d job(s)", performed)
        return performed
