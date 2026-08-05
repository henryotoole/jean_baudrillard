"""Entrypoint for the `worker` core service of the `api` codebase.

Owns the three things a loop-owning core service owes and an adapter must
not: the poll loop itself, the signal handling that stops it, and the
liveness surface that proves it is still turning.

The thresholds below are **doctrine-fixed** (contracts.md § Health Checks)
— the loop must tick at least every 10 s even when idle, `/health` must
503 once the tick is 30 s stale. There is deliberately no per-project knob
and no env var; do not add one.
"""

from __future__ import annotations

import logging
import signal
import threading
import time

import uvicorn
from fastapi import FastAPI, HTTPException

from root import VERSION, build_processor


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("entrypoints.worker")

# Doctrine-fixed. 30 is three times 10, so a healthy loop misses two
# consecutive ticks before it is called stale — enough slack for scheduling
# jitter and one slow iteration without flapping.
_STALENESS_SECONDS = 30.0

# The receive must be *bounded* so the tick keeps arriving while idle. One
# second is comfortably inside the 10 s ceiling.
_POLL_INTERVAL_SECONDS = 1.0

# Health port. Must match infra.yml's `port: 8081` on this core service —
# nothing injects it, so the two are coupled by convention, as in web.py.
_HEALTH_PORT = 8081


class _Tick:
    """The loop's liveness signal: when it last completed an iteration."""

    def __init__(self) -> None:
        self.at = time.monotonic()

    def bump(self) -> None:
        # WHY: no lock. This is one `STORE_ATTR` of a float, written by the
        # loop thread and read by the health thread; the GIL makes it
        # atomic, so a reader can never observe a torn value. A lock here
        # would add contention and buy nothing — do not add one.
        self.at = time.monotonic()


_tick = _Tick()
_stop = threading.Event()


def _build_health_app() -> FastAPI:
    app = FastAPI(title="api-worker", version=VERSION)

    @app.get("/health")
    def health() -> dict[str, str]:
        # WHY: liveness is sourced from the LOOP's tick, never from this
        # thread's own aliveness. A separate liveness thread will cheerfully
        # answer 200 while nothing is being processed, and that is exactly
        # what the doctrine forbids — a wedged consumer must fail its own
        # probe (contracts.md § Self health).
        age = time.monotonic() - _tick.at
        if age > _STALENESS_SECONDS:
            raise HTTPException(
                503, f"processor loop tick is {age:.1f}s stale "
                     f"(threshold {_STALENESS_SECONDS:.0f}s)",
            )
        return {"version": VERSION}

    return app


def _on_signal(signum: int, _frame: object) -> None:
    logger.info("processor: caught signal %d, stopping after current iteration", signum)
    _stop.set()


def main() -> None:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    # WHY: the health server runs in a daemon thread and the poll loop in the
    # MAIN thread, not the other way round. Signals are only delivered to the
    # main thread, and it is the loop that has to hear SIGTERM to shut down
    # cleanly; a daemon thread also needs no join on the way out.
    server = uvicorn.Server(
        uvicorn.Config(
            _build_health_app(), host="0.0.0.0", port=_HEALTH_PORT,
            log_level="warning",
        ),
    )
    threading.Thread(target=server.run, name="health", daemon=True).start()

    cli = build_processor()
    logger.info(
        "processor: starting loop (interval=%.2fs, health on :%d)",
        _POLL_INTERVAL_SECONDS, _HEALTH_PORT,
    )
    while not _stop.is_set():
        try:
            cli.run_once()
        except Exception:
            # A transient database error must not take the worker down; the
            # next iteration retries. Real projects would alert here.
            #
            # WHY: the tick is NOT bumped on this path. A loop that fails
            # every single iteration is not alive in any useful sense, and
            # bumping here would report 200 forever while no work moves —
            # defeating the entire point of the probe.
            logger.exception("processor: iteration failed")
        else:
            _tick.bump()
        # `wait` rather than `sleep` so SIGTERM shortens the last interval.
        _stop.wait(_POLL_INTERVAL_SECONDS)
    logger.info("processor: stopped")


if __name__ == "__main__":
    main()
