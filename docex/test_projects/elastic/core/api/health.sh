#!/bin/sh
# health.sh — the `api` codebase's container health probe.
#
# The fourth codebase shim, beside build.sh / test.sh / migrate.sh, and the only
# one invoked PER CORE SERVICE: the compiler emits
# `["CMD", "./health.sh", "<service>"]` as the container probe on both
# foundations, so this script never has to guess where it is running
# (healthchecks.md § The probe). `./health.sh` resolves against WORKDIR /service.
#
# THE EXIT CODE IS THE ENTIRE CONTRACT. 0 means this core service is working;
# anything else means it is not. Nothing reads stdout — docker captures probe
# output and ECS does not, so it can never be a cross-foundation channel
# (healthchecks.md § Version). The messages below go to stderr for a human
# reading `docker inspect` and promise nothing.
#
# POSIX sh, not bash: python:3.12-slim ships dash as /bin/sh and no bash.

set -eu

svc="${1:-}"
if [ -z "$svc" ]; then
    echo "health.sh: usage: ./health.sh <core-service>" >&2
    exit 2
fi

# The staleness THRESHOLD is doctrine-fixed at 30s and lives here, because this
# script is the only thing that judges it. The loop CADENCE — at least one tick
# every 10s even when idle — is doctrine-fixed too and lives in
# src/entrypoints/{worker,clock}.py, because the loop is the only thing that can
# honour it. THE TWO NUMBERS ARE MEANINGLESS APART: 30 is three times 10, so a
# healthy loop misses two consecutive ticks before it is called stale — enough
# slack for scheduling jitter and one slow iteration without flapping, while
# still failing a wedged loop inside the window the orchestrator acts on. There
# is no per-project knob for either
# (healthchecks.md § What the probe must actually check).
STALENESS_SECONDS=30

# Must match infra.yml's `port:` on api.web. Nothing injects it, so the two are
# coupled by convention — exactly as src/entrypoints/web.py's default is.
WEB_PORT=8080

check_tick() {
    # A loop-owning core service's liveness is sourced FROM THE LOOP: the loop
    # touches this file at the end of each iteration and this stats it from a
    # separate process. Checking that the process exists would prove nothing (a
    # deadlocked process exists), and checking a separate liveness thread would
    # prove less than nothing — it answers healthy forever while no work moves,
    # converting a loud failure into a silent one
    # (healthchecks.md § What the probe must actually check).
    tick="/tmp/$1.tick"

    # An ABSENT tick file FAILS. A loop that has never completed an iteration
    # has never been alive, and reporting healthy until the first tick would
    # hide a loop that never started — the exact failure this probe exists for.
    # On elastic the role tables' `startPeriod: 10` is what keeps this from
    # killing a task during normal startup; on fixed docker only reports, so
    # nothing acts on it early.
    if [ ! -f "$tick" ]; then
        echo "health.sh: $1: no tick file at $tick — the loop has not completed an iteration" >&2
        exit 1
    fi

    age=$(( $(date +%s) - $(stat -c %Y "$tick") ))
    if [ "$age" -gt "$STALENESS_SECONDS" ]; then
        echo "health.sh: $1: loop tick is ${age}s stale (threshold ${STALENESS_SECONDS}s)" >&2
        exit 1
    fi
}

case "$svc" in
    web)
        # A service driven by a REQUEST CYCLE is nearly self-checking: if it
        # accepts a connection and routes a trivial request, it is serving.
        # Curling its own route is legitimate here and nowhere else in this file
        # (healthchecks.md § What the probe must actually check). `curl` is in
        # the image FOR THIS LINE — see the Dockerfile.
        curl -fsS -m 3 "http://localhost:${WEB_PORT}/health" >/dev/null
        ;;
    worker|clock)
        # Both own a loop. A clock is not exempt from anything: it wakes, checks
        # its schedule, and sleeps, which is a loop in exactly this sense.
        check_tick "$svc"
        ;;
    *)
        # A typo in the emitted argv must be LOUD. Falling through to exit 0
        # would report every core service healthy forever, which is the one
        # outcome worse than a wrong probe.
        echo "health.sh: unknown core service '$svc' (expected web, worker or clock)" >&2
        exit 2
        ;;
esac
