"""Entrypoint for the `worker` core service of the `api` codebase.

Owns four things a loop-owning core service owes and an adapter must not: the
poll loop itself, the signal handling that stops it, the **tick file** that the
container probe stats from another process, and the runtime host for this core
service's `rpc` surface.

**The two numbers, and which file owns each.** The loop's CADENCE lives here —
at least one tick every 10 s even when idle, which `_POLL_INTERVAL_SECONDS`
satisfies with room to spare — because the loop is the only thing that can
honour it. The staleness THRESHOLD (30 s) lives in `health.sh`, because the
probe is the only thing that judges it. Both are doctrine-fixed with no
per-project knob and no env var; do not add one. **They only mean something as
a pair:** 30 is three times 10, so a healthy loop misses two consecutive ticks
before it is called stale. A reader who finds one number without the other
cannot see that, which is why each file names the other half
(healthchecks.md § What the probe must actually check).
"""

from __future__ import annotations

import logging
import signal
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from root import VERSION, build_job_runner, build_job_runner_http, build_processor


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("entrypoints.worker")

# The receive must be *bounded* so the tick keeps arriving while idle. One
# second is comfortably inside the 10 s ceiling; the 30 s threshold this has to
# stay inside lives in health.sh.
_POLL_INTERVAL_SECONDS = 1.0

# `api.worker`'s `rpc` surface. Must match infra.yml's `port: 8081` on this core
# service — nothing injects it, so the two are coupled by convention, as in
# web.py.
_RPC_PORT = 8081

# The tick is a FILE, not an in-memory float: the probe is `./health.sh worker`,
# which docker and ECS run as a SEPARATE PROCESS, so the tick has to live
# somewhere that process can stat (healthchecks.md § What the probe must
# actually check). `/tmp` is tmpfs-backed wherever the core service declares
# `disk:`, so this is a memory write rather than a disk write once a second.
_TICK_PATH = Path("/tmp/worker.tick")


class _Tick:
    """The loop's liveness signal, observable from another process."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def bump(self) -> None:
        # `touch` both creates the file and re-stamps its mtime, which is the
        # whole of the signal — the CONTENT is never read.
        self._path.touch()


# WHY the file is NOT created here. The in-memory version seeded itself with
# `time.monotonic()` at import, which pre-declared the loop alive before it had
# run once. `health.sh`'s absent-file arm is what catches a loop that never
# started, and pre-creating the file would disarm it.
_tick = _Tick(_TICK_PATH)
_stop = threading.Event()


def _on_signal(signum: int, _frame: object) -> None:
    logger.info("processor: caught signal %d, stopping after current iteration", signum)
    _stop.set()


def main() -> None:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    # WHY this thread exists, because the shape is easy to misread: it is NOT a
    # health server. Liveness is the tick file and does not involve this thread
    # at all — kill this server and `./health.sh worker` still tells the truth
    # about the loop. The thread is here because `api.web` CALLS this boundary
    # (POST /drain on the `rpc` surface), which is an application call, not a
    # probe. `api.clock`, which declares no surface, runs no server at all.
    #
    # WHY the loop is in the MAIN thread and the server in the daemon thread,
    # not the other way round: signals are only delivered to the main thread,
    # and it is the loop that has to hear SIGTERM to shut down cleanly; a
    # daemon thread also needs no join on the way out.
    #
    # The app is built HERE and not in the composition root because the runtime
    # host is not an adapter (internal_dependency_rules.md § Entrypoints,
    # rule 2). The root constructs the router; this file serves it.
    runner_http = build_job_runner_http()
    rpc_app = FastAPI(title="api-worker-rpc", version=VERSION)
    rpc_app.include_router(runner_http.router)
    server = uvicorn.Server(
        uvicorn.Config(
            rpc_app, host="0.0.0.0", port=_RPC_PORT, log_level="warning",
        ),
    )
    threading.Thread(target=server.run, name="rpc", daemon=True).start()

    cli = build_processor()
    job_runner = build_job_runner()
    logger.info(
        "processor: starting loop (interval=%.2fs, tick=%s, rpc on :%d); "
        "each pass processes pings and drains the deferred-job queue",
        _POLL_INTERVAL_SECONDS, _TICK_PATH, _RPC_PORT,
    )
    while not _stop.is_set():
        try:
            cli.run_once()
            # The perform side of the clock's queue. Same `try`, same
            # interval, and ONE tick for the pair below — a failure in
            # either half must withhold the tick, because a worker that
            # cannot drain the queue is not doing its job even if pings
            # still move.
            job_runner.run_once()
        except Exception:
            # A transient database error must not take the worker down; the
            # next iteration retries. Real projects would alert here.
            #
            # WHY: the tick is NOT bumped on this path. A loop that fails
            # every single iteration is not alive in any useful sense, and
            # bumping here would keep the probe green forever while no work
            # moves — defeating the entire point of the probe.
            logger.exception("processor: iteration failed")
        else:
            _tick.bump()
        # `wait` rather than `sleep` so SIGTERM shortens the last interval.
        _stop.wait(_POLL_INTERVAL_SECONDS)
    logger.info("processor: stopped")


if __name__ == "__main__":
    main()
