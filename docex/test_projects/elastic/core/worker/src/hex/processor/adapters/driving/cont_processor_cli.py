"""ContProcessorCli — long-running poll loop adapter for ContProcessor.

The container's main process. Polls every POLL_INTERVAL_SECONDS and
exits cleanly on SIGTERM.
"""

from __future__ import annotations

import logging
import signal
import time

from hex.processor.ports.driving.cont_processor import ContProcessor


logger = logging.getLogger(__name__)


class ContProcessorCli:
    def __init__(self, service: ContProcessor, poll_interval_seconds: float = 1.0) -> None:
        self._service = service
        self._poll_interval = poll_interval_seconds
        self._stop = False

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        logger.info("processor: starting loop (interval=%.2fs)", self._poll_interval)
        while not self._stop:
            try:
                processed = self._service.run_once()
                if processed:
                    logger.info("processor: processed %d ping(s)", processed)
            except Exception:
                # Don't take the worker down on a transient error; the next
                # iteration will retry. Real projects would alert here.
                logger.exception("processor: iteration failed")
            time.sleep(self._poll_interval)
        logger.info("processor: stopped")

    def _on_signal(self, signum: int, _frame: object) -> None:
        logger.info("processor: caught signal %d, stopping after current iteration", signum)
        self._stop = True
