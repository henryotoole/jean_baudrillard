"""ContProcessorCli — CLI-mechanism driving adapter for ContProcessor.

Translation only: one invocation in, a processed count out. It owns no
loop, no signal handlers, and no sleep. The runtime host is not an adapter
(internal_dependency_rules.md § Entrypoints, rule 2), so the poll loop
that drives this adapter lives in `entrypoints/worker.py`.
"""

from __future__ import annotations

import logging

from hex.processor.ports.driving.cont_processor import ContProcessor


logger = logging.getLogger(__name__)


class ContProcessorCli:
    def __init__(self, service: ContProcessor) -> None:
        self._service = service

    def run_once(self) -> int:
        # WHY: no try/except here. An adapter that swallowed the exception
        # would report "0 processed" for a *failed* iteration, and the
        # entrypoint's loop must tell those apart — it may only bump the
        # liveness tick on a genuine pass.
        processed = self._service.run_once()
        if processed:
            logger.info("processor: processed %d ping(s)", processed)
        return processed
