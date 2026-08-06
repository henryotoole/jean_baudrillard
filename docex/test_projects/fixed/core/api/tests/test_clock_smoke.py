"""Tests for the `api.clock` core service's driving adapter.

**These deliberately touch NO database and never import `root`.** That is
the whole point: `ContJobsCron.job_names()` is a class-level, instance-free
accessor so that "what jobs does this image implement?" can be answered
with no service instance, no DSN, and no DATABASE_* in the environment.
The binding-coverage check `entrypoints/clock.py` runs at startup reads
exactly that accessor, through `ContJobsCron.unbound()`, so this file
exists to keep it from silently regressing into an instance property.

The two `unbound()` tests below cover **both directions** of that check,
and the asymmetry between them is the load-bearing part: a scheduled name
with no binding is fatal, a binding with no schedule is fine.
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


def test_a_scheduled_name_with_no_binding_is_reported() -> None:
    # A plausible TYPO, not a placeholder name: this test should look like
    # the failure it defends against. `entrypoints/clock.py` turns a
    # non-empty result into SystemExit(1) before the cron loop starts, so
    # this schedule fails the deploy rather than firing at 03:00.
    #
    # Called straight off the CLASS — no instance, no service, no DSN.
    # That is the property `job_names()` was made class-level for, and the
    # one a future refactor to an instance attribute would silently break.
    assert ContJobsCron.unbound(["heartbeat", "nightly_cleanupp"]) == ("nightly_cleanupp",)


def test_a_binding_with_no_schedule_is_not_reported() -> None:
    # The reverse direction is DELIBERATELY benign. `prune_pings` is
    # implemented and unscheduled here, and that is a legitimate design:
    # the driving port is shared, so a job reachable only over HTTP or CLI
    # is intentional. See the asymmetry note in `ContJobsCron.unbound()` —
    # do not "fix" this by making the check symmetric.
    assert "prune_pings" in ContJobsCron.job_names()
    assert ContJobsCron.unbound(["heartbeat"]) == ()


def test_fire_rejects_an_unbound_name() -> None:
    cron = ContJobsCron(service=_StubJobs())
    try:
        cron.fire("no_such_job")
    except KeyError:
        return
    raise AssertionError("firing an unbound job name must raise")
