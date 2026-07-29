"""ContReaperCli — driving adapter translating the job trigger into a
single reap() call against the driving port.

Unlike `api.worker`, whose entrypoint wraps its ``run_once`` in a poll
loop, a scheduler job runs to completion: one pass, then exit. The exit
code is 0 on success so the scheduler (Ofelia / EventBridge RunTask)
records the job as succeeded.
"""

from __future__ import annotations

import logging

from hex.reaper.ports.driving.cont_reaper import ContReaper

logger = logging.getLogger(__name__)


class ContReaperCli:
    def __init__(self, service: ContReaper) -> None:
        self._service = service

    def run_once(self) -> int:
        deleted = self._service.reap()
        logger.info("reap complete: %d expired ping(s) deleted", deleted)
        return 0
