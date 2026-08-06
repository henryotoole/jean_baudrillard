"""Tests for the `api.clock` core service's driving adapter.

**These deliberately touch NO database and never import `root`.** That is
the whole point: `ContJobsCron.job_names()` is a class-level, instance-free
accessor so that "what jobs does this image implement?" can be answered
with no service instance, no DSN, and no DATABASE_* in the environment.
Any binding-coverage check the operator later rules on — a `docex check`
gate, or startup validation in the clock entrypoint — reads exactly that
accessor, so this file exists to keep it from silently regressing into an
instance property.
"""

from __future__ import annotations

import sys
from uuid import UUID, uuid4


sys.path.insert(0, "/service/dist")

from hex.jobs.adapters.driving.cont_jobs_cron import ContJobsCron  # noqa: E402


class _StubJobs:
    """Stub ContJobs. Records what was deferred; enqueues nothing."""

    def __init__(self) -> None:
        self.deferred: list[str] = []

    def prune_pings(self) -> UUID:
        self.deferred.append("prune_pings")
        return uuid4()

    def heartbeat(self) -> UUID:
        self.deferred.append("heartbeat")
        return uuid4()


def test_job_names_are_readable_without_an_instance() -> None:
    names = ContJobsCron.job_names()
    assert names, "a clock adapter with no job names implements nothing"
    assert sorted(names) == sorted(set(names)), "job names must be unique"


def test_job_names_match_the_dispatch_table() -> None:
    cron = ContJobsCron(service=_StubJobs())
    # The class tuple and the instance map must agree. If they drift, any
    # binding check answers about the wrong set.
    assert set(cron.job_names()) == set(ContJobsCron.JOB_NAMES)
    for name in ContJobsCron.job_names():
        assert cron.fire(name) is not None


def test_fire_translates_a_name_into_one_port_call() -> None:
    stub = _StubJobs()
    cron = ContJobsCron(service=stub)
    cron.fire("prune_pings")
    assert stub.deferred == ["prune_pings"]


def test_fire_rejects_an_unbound_name() -> None:
    cron = ContJobsCron(service=_StubJobs())
    try:
        cron.fire("no_such_job")
    except KeyError:
        return
    raise AssertionError("firing an unbound job name must raise")
