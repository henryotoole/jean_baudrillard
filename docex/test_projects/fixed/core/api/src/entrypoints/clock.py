"""Entrypoint for the `clock` core service of the `api` codebase.

**This file is the doctrine's reference implementation of a clock runtime
host.** Downstream projects copy it, so it is commented to that standard.
It is modelled directly on `entrypoints/worker.py`, which is already the
liveness reference — a cron loop is the same species as a broker's consume
loop, and the runtime host belongs to the entrypoint either way
(internal_dependency_rules.md § Entrypoints, rule 2).

It owns the three things a loop-owning core service owes and an adapter
must not: the loop itself, the signal handling that stops it, and the
**tick file** that the container probe stats from another process. The
job-name → port dispatch and the fired/deferred/failed translation belong
to `ContJobsCron`, which is what keeps this file thin enough to satisfy the
standing rule that an entrypoint needing its own test is doing too much.

**A clock runs NO HTTP SERVER AT ALL.** It takes no ingress, nothing
addresses it, and it declares no `port` and no surface — so there is
nothing for it to listen on and nothing for a caller to reach. Its probe is
`./health.sh clock`, which reads the loop's tick file and nothing else.
That is the whole of its liveness.

**The clock defers; it does not work.** Every fire below enqueues and
returns. See clock.md § The clock defers; it does not work.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml
from croniter import croniter

from root import build_clock


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("entrypoints.clock")

# The wait must be *bounded* so the tick keeps arriving while nothing is
# due. Five seconds is comfortably inside the doctrine-fixed 10 s cadence
# ceiling, and it is also the whole of the liveness mechanism: clock.md
# notes that "a cron loop with a bounded ≤10 s wait is the natural way to
# write one", meaning the cadence rule is satisfied BY THE LOOP'S SHAPE
# rather than by a separate keepalive thread bolted on beside it. A minutely
# job fires within five seconds of its minute, which is the accuracy a cron
# expression promises anyway.
#
# What has changed is only what the tick IS: a touched file rather than a
# served route. The staleness THRESHOLD this cadence has to stay inside
# lives in `health.sh`, because the probe is the only thing that judges it;
# neither number is a per-project knob
# (healthchecks.md § What the probe must actually check).
_TICK_INTERVAL_SECONDS = 5.0

# The tick is a FILE, not an in-memory float: the probe is `./health.sh clock`,
# which docker and ECS run as a SEPARATE PROCESS, so the tick has to live
# somewhere that process can stat (healthchecks.md § What the probe must
# actually check). `/tmp` is tmpfs-backed wherever the core service declares
# `disk:`, so this is a memory write rather than a disk write every five
# seconds.
_TICK_PATH = Path("/tmp/clock.tick")

# The one variable through which the compiler delivers this clock's job
# table, identical on BOTH foundations. Its value is the LITERAL rendered
# YAML — never a path to a file, never a mount.
_SCHEDULES_ENV_KEY = "DOCEX_SCHEDULES_YAML"


class _Tick:
    """The loop's liveness signal, observable from another process."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def bump(self) -> None:
        # `touch` both creates the file and re-stamps its mtime, which is the
        # whole of the signal — the CONTENT is never read.
        self._path.touch()


# WHY the file is NOT created here. The in-memory version seeded itself with
# `time.monotonic()` at import, which pre-declared the loop alive before it
# had run once. `health.sh`'s absent-file arm is what catches a loop that
# never started, and pre-creating the file would disarm it.
_tick = _Tick(_TICK_PATH)
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
        # nothing while the tick keeps the probe green.
        logger.error("clock: %s is absent or empty", _SCHEDULES_ENV_KEY)
        raise SystemExit(1)
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict) or not parsed:
        logger.error("clock: %s did not parse to a non-empty map", _SCHEDULES_ENV_KEY)
        raise SystemExit(1)
    return {str(job): str(expr) for job, expr in parsed.items()}


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
        "clock: starting loop (tick=%.1fs, tick file=%s); listens on nothing",
        _TICK_INTERVAL_SECONDS, _TICK_PATH,
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
        # withheld tick. Bumping there would keep the probe green forever
        # while nothing is ever deferred.
        if not due or failures < len(due):
            _tick.bump()

        # `wait` rather than `sleep` so SIGTERM shortens the last interval.
        _stop.wait(_TICK_INTERVAL_SECONDS)
    logger.info("clock: stopped")


if __name__ == "__main__":
    main()
