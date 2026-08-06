"""ContJobsCron — Cron-mechanism driving adapter for ContJobs.

The clock entrypoint owns the loop; this owns the two things an adapter
owes and a runtime host must not: the job-name → port-method dispatch
table, and the fired / deferred / failed translation. That is what keeps
`entrypoints/clock.py` thin enough to satisfy the standing rule that an
entrypoint needing its own test is doing too much
(clock.md § Architecture).

**There are two dispatch tables in this module and they are NOT
duplication.** This one maps a job name to how the job is *deferred*; the
other, in `JobRunnerService`, maps a job name to how it is *performed*.
Collapsing them is the obvious cleanup and it would couple the clock to
the worker's implementation — the clock would have to know how a job is
performed in order to know how to defer it, at which point nothing stops
it performing the job itself, which is exactly what
`clock.md § The clock defers; it does not work` forbids.

**Binding coverage IS asserted, at clock startup.** `unbound()` below
answers "which of these scheduled names can I not dispatch?", and
`entrypoints/clock.py` calls it before entering the cron loop and exits
non-zero if the answer is non-empty. The split is deliberate: the adapter
owns `JOB_NAMES` and the dispatch table, so the *question* is its to
answer; the *policy* that an unbound name is fatal belongs to the runtime
host, because process lifecycle does (clock.md § Architecture). A
schedule naming a job nobody implements therefore fails the deploy, not
the 3 a.m. fire. `JOB_NAMES` / `job_names()` are class-level and
instance-free so that check costs one set comparison and no database.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable
from uuid import UUID

from hex.jobs.ports.driving.cont_jobs import ContJobs


logger = logging.getLogger(__name__)


class ContJobsCron:
    # WHY class-level, and why `job_names()` is a classmethod: the names
    # must be readable with NO service instance, NO database, and NO
    # DATABASE_* in the environment. An instance property would require
    # constructing the whole graph — a composition root, a DSN, a live
    # postgres — just to answer "what jobs does this image implement?".
    # Do not turn this into an instance attribute.
    JOB_NAMES: tuple[str, ...] = ("heartbeat", "prune_pings")

    @classmethod
    def job_names(cls) -> tuple[str, ...]:
        """Every job name this adapter can fire. No instance required."""
        return cls.JOB_NAMES

    @classmethod
    def unbound(cls, scheduled: Iterable[str]) -> tuple[str, ...]:
        """Scheduled job names this adapter cannot dispatch, sorted.

        Empty means every scheduled name has a binding.

        Classmethod for the same reason `job_names()` is one — see the
        note on `JOB_NAMES` above. The startup check must run with no
        service instance and no database.
        """
        # ONE DIRECTION ONLY. This answers "which of these can I not
        # fire?" and nothing else.
        #
        # A bound job with NO schedule is legitimate and must never be
        # reported. The driving port is shared, so a job reachable only
        # over HTTP or CLI is a deliberate design — firing a job by hand
        # stopped being a special path, which is one of the clock
        # architecture's stated benefits. Do not make this symmetric.
        return tuple(sorted(set(scheduled) - set(cls.JOB_NAMES)))

    def __init__(self, service: ContJobs) -> None:
        self._service = service
        self._dispatch: dict[str, Callable[[], UUID]] = {
            "heartbeat": service.heartbeat,
            "prune_pings": service.prune_pings,
        }
        # The instance table and the class tuple must not drift: the tuple
        # is what `unbound()` — and therefore the clock's startup check —
        # reads, and a name present in one but not the other would make
        # that check answer about the wrong set.
        assert set(self._dispatch) == set(self.JOB_NAMES), (
            f"dispatch keys {sorted(self._dispatch)} != "
            f"JOB_NAMES {sorted(self.JOB_NAMES)}"
        )

    def fire(self, name: str) -> UUID:
        """Translate a due job name into one call against the driving port.

        Args:
            name: a job name from the compiler-delivered schedule table.
                Must be a key of this adapter's dispatch map.

        Returns:
            The id of the enqueued job.

        Raises:
            KeyError: the schedule names a job this image does not
                implement. The clock's startup check (`unbound()`, see the
                binding-coverage note in the class docstring) should have
                made this unreachable, so this is the last line of defence
                — for a name that arrived some other way, or a dispatch
                table mutated after startup. Re-raised rather than
                swallowed so the loop records a genuine failure.
            Exception: whatever the port raises (typically a database
                error on enqueue), logged and re-raised.
        """
        handler = self._dispatch.get(name)
        if handler is None:
            logger.error("jobs: no binding for scheduled job %r", name)
            raise KeyError(f"no binding for scheduled job {name!r}")
        logger.info("jobs: %r fired", name)
        try:
            job_id = handler()
        except Exception:
            logger.exception("jobs: %r failed to defer", name)
            raise
        logger.info("jobs: %r deferred as job %s", name, job_id)
        return job_id
