"""Entrypoint for the `clock` core service of the `api` codebase.

**This file is the doctrine's reference implementation of a clock runtime
host.** Downstream projects copy it, so it is commented to that standard.
It is modelled directly on `entrypoints/worker.py`, which is already the
liveness reference — a cron loop is the same species as a broker's consume
loop, and the runtime host belongs to the entrypoint either way
(internal_dependency_rules.md § Entrypoints, rule 2).

It owns the three things a loop-owning core service owes and an adapter
must not: the loop itself, the signal handling that stops it, and the
liveness surface that proves it is still turning. The job-name → port
dispatch and the fired/deferred/failed translation belong to
`ContJobsCron`, which is what keeps this file thin enough to satisfy the
standing rule that an entrypoint needing its own test is doing too much.

**The clock defers; it does not work.** Every fire below enqueues and
returns. See clock.md § The clock defers; it does not work.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone

import uvicorn
import yaml
from croniter import croniter
from fastapi import FastAPI, HTTPException

from root import VERSION, build_clock


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("entrypoints.clock")

# Doctrine-fixed (contracts.md § Health Checks): the loop must tick at
# least every 10 s even when idle, and /health must 503 once the tick is
# 30 s stale. 30 is three times 10, so a healthy loop misses two
# consecutive ticks before it is called stale. There is deliberately no
# per-project knob and no env var; do not add one.
_STALENESS_SECONDS = 30.0

# The wait must be *bounded* so the tick keeps arriving while nothing is
# due. Five seconds is comfortably inside the 10 s ceiling, and it is also
# the whole of the liveness mechanism: clock.md notes that "a cron loop
# with a bounded ≤10 s wait is the natural way to write one", meaning the
# 10 s/30 s rule is satisfied BY THE LOOP'S SHAPE rather than by a
# separate keepalive thread bolted on beside it. A minutely job fires
# within five seconds of its minute, which is the accuracy a cron
# expression promises anyway.
_TICK_INTERVAL_SECONDS = 5.0

# Health port. Must match infra.yml's `port: 8082` on this core service —
# nothing injects it, so the two are coupled by convention, as in web.py
# and worker.py.
_HEALTH_PORT = 8082

# The one variable through which the compiler delivers this clock's job
# table, identical on BOTH foundations. Its value is the LITERAL rendered
# YAML — never a path to a file, never a mount.
_SCHEDULES_ENV_KEY = "DOCEX_SCHEDULES_YAML"


class _Tick:
    """The loop's liveness signal: when it last completed an iteration."""

    def __init__(self) -> None:
        self.at = time.monotonic()

    def bump(self) -> None:
        # WHY: no lock. This is one `STORE_ATTR` of a float, written by the
        # loop thread and read by the health thread; the GIL makes it
        # atomic, so a reader can never observe a torn value.
        self.at = time.monotonic()


_tick = _Tick()
_stop = threading.Event()


def _load_schedules() -> dict[str, str]:
    """Parse this clock's job table out of the environment.

    WHY one variable holding literal YAML, and no file fallback: the
    single-variable, literal-value design IS the point
    (clock.md § How the schedule reaches the container). One mechanism on
    both foundations means a clock entrypoint reads one variable and
    parses it — no file to locate, no mount to arrange, and no
    per-foundation branch anywhere in application code. Do not add a path
    fallback "just in case"; the case does not exist, and the fallback
    would be the branch this design was built to delete.
    """
    raw = os.environ.get(_SCHEDULES_ENV_KEY)
    if not raw or not raw.strip():
        # A clock with no schedule is misconfigured, not idle. Validation
        # forbids it upstream (a `clock` must declare a non-empty
        # `schedules:` map), so reaching here means the delivery seam
        # itself is broken — fail loudly rather than spin forever doing
        # nothing while answering 200 on /health.
        logger.error("clock: %s is absent or empty", _SCHEDULES_ENV_KEY)
        raise SystemExit(1)
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict) or not parsed:
        logger.error("clock: %s did not parse to a non-empty map", _SCHEDULES_ENV_KEY)
        raise SystemExit(1)
    return {str(job): str(expr) for job, expr in parsed.items()}


def _build_health_app() -> FastAPI:
    app = FastAPI(title="api-clock", version=VERSION)

    @app.get("/health")
    def health() -> dict[str, str]:
        # WHY: liveness is sourced from the LOOP's tick, never from this
        # thread's own aliveness. A separate liveness thread will cheerfully
        # answer 200 while nothing is being fired, and that is exactly what
        # the doctrine forbids — a wedged clock must fail its own probe
        # (contracts.md § Self health).
        #
        # This probe is the ONLY enforcement a clock gets. Nothing `uses`
        # it and it is not on the `web` network, so no fan-out and no stage
        # test can reach it (clock.md § Caveats) — only the container
        # healthcheck, which restarts it.
        age = time.monotonic() - _tick.at
        if age > _STALENESS_SECONDS:
            raise HTTPException(
                503, f"clock loop tick is {age:.1f}s stale "
                     f"(threshold {_STALENESS_SECONDS:.0f}s)",
            )
        return {"version": VERSION}

    return app


def _on_signal(signum: int, _frame: object) -> None:
    logger.info("clock: caught signal %d, stopping after current iteration", signum)
    _stop.set()


def main() -> None:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    schedules = _load_schedules()
    cron = build_clock()

    logger.info(
        "clock: %d scheduled job(s): %s; image implements: %s",
        len(schedules), ", ".join(sorted(schedules)),
        ", ".join(sorted(cron.job_names())),
    )

    # WHY FATAL: a schedule naming a job this image cannot dispatch is a
    # typo (`nightly_cleanupp`), and it is unrunnable. It fails the DEPLOY
    # rather than a `docex check` gate — the image is the only thing that
    # knows what it implements, so the image is what asserts it.
    #
    # WHY HERE, and not on first fire: a clock that starts, answers its
    # health probe, and then dies at 03:00 is strictly worse than one that
    # never starts. The failure must land while someone is watching the
    # deploy, so it goes before the health server and before `next_at`.
    #
    # WHY BOTH HALVES ARE LOGGED: an operator reading a crash-looping
    # container needs the offending name AND the implemented set to see the
    # typo. Either alone sends them to the source tree.
    #
    # Only this direction is checked. A bound job with no schedule is
    # legitimate — see the asymmetry note in `ContJobsCron.unbound()`.
    missing = cron.unbound(schedules)
    if missing:
        logger.error(
            "clock: %d scheduled job(s) have no binding: %s; image implements: %s",
            len(missing), ", ".join(missing), ", ".join(sorted(cron.job_names())),
        )
        raise SystemExit(1)

    # WHY: the health server runs in a daemon thread and the cron loop in
    # the MAIN thread, not the other way round. Signals are only delivered
    # to the main thread, and it is the loop that has to hear SIGTERM to
    # shut down cleanly; a daemon thread also needs no join on the way out.
    server = uvicorn.Server(
        uvicorn.Config(
            _build_health_app(), host="0.0.0.0", port=_HEALTH_PORT,
            log_level="warning",
        ),
    )
    threading.Thread(target=server.run, name="health", daemon=True).start()

    # WHY next_at is seeded from PROCESS START and never from a persisted
    # position: the clock is forward-only and does not backfill
    # (clock.md § Caveats). A clock that was down for six hours must not
    # come up and stampede six hours of missed fires at the queue.
    started = datetime.now(timezone.utc)
    next_at = {
        job: croniter(expr, start_time=started).get_next(datetime)
        for job, expr in schedules.items()
    }

    logger.info(
        "clock: starting loop (tick=%.1fs, health on :%d)",
        _TICK_INTERVAL_SECONDS, _HEALTH_PORT,
    )
    while not _stop.is_set():
        now = datetime.now(timezone.utc)
        due = sorted(job for job, at in next_at.items() if at <= now)
        failures = 0
        for job in due:
            try:
                cron.fire(job)
            except Exception:
                # One bad job must not kill the loop; the next fire retries
                # on its own schedule.
                logger.exception("clock: firing %r failed", job)
                failures += 1
            # Recomputed from `now`, not from the missed slot — forward
            # only, so a slow pass never queues a backlog.
            next_at[job] = croniter(schedules[job], start_time=now).get_next(datetime)

        # The tick is bumped on every iteration, fired or not: a clock with
        # nothing due is perfectly alive, and that is what makes the
        # bounded wait above sufficient for the 10 s rule.
        #
        # WHY the exception: a pass on which EVERY fire raised is not a
        # live clock in any useful sense — same reasoning as worker.py's
        # withheld tick. Bumping there would answer 200 forever while
        # nothing is ever deferred.
        if not due or failures < len(due):
            _tick.bump()

        # `wait` rather than `sleep` so SIGTERM shortens the last interval.
        _stop.wait(_TICK_INTERVAL_SECONDS)
    logger.info("clock: stopped")


if __name__ == "__main__":
    main()
