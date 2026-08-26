#!/bin/sh
# test.sh — canonical test entry point for the `api` codebase.
# One suite per codebase, not per core service: this globs the whole
# tests/ folder, covering api.web (test_smoke.py), api.worker
# (test_processor_smoke.py, test_jobs_smoke.py, test_jobs_concurrency.py,
# test_jobs_alogic.py), api.clock (test_clock_smoke.py), and the
# api.web -> api.worker drain boundary (test_jobs_drain.py) in one run.
# The glob is the authority: this list is orientation, not a manifest.
#
# DOCEX_TEST_SELECTOR (optional, injected by `docex test [subset]`): a
# pytest-args FRAGMENT (a path and/or a -m/-k expression), forwarded UNQUOTED
# so multiple tokens word-split into separate args. Set → replaces the default
# whole-suite target; unset → whole suite.
#
# DOCEX_TEST_SLOT / DOCEX_TEST_SLOTS (optional, injected by `docex test --slots
# N`): this shard's 1-based index and the shard count N. A REFERENCE only — the
# doctrine recommends but does not mandate this pattern (tests.md § Injected
# environment); a project may shard however is idiomatic to its runner. Unset or
# N=1 ⇒ whole suite, byte-identical to before. N>1 ⇒ this slot runs only its
# deterministic 1/N share of the collected node-ids, so the union of the N
# shards is exactly the whole suite.
set -eu

# Base target: a selector fragment replaces the whole-suite default.
if [ -n "${DOCEX_TEST_SELECTOR:-}" ]; then
    TARGET="$DOCEX_TEST_SELECTOR"
else
    TARGET="/service/tests"
fi

if [ "${DOCEX_TEST_SLOTS:-1}" -gt 1 ]; then
    # Collect node-ids for the suite (respecting any selector already spliced
    # into TARGET), then keep index % SLOTS == (SLOT-1).
    # shellcheck disable=SC2086
    NODES="$(pytest $TARGET --collect-only -q | grep '::' || true)"
    SHARD_ARGS="$(printf '%s\n' "$NODES" \
        | awk -v s="$DOCEX_TEST_SLOT" -v n="$DOCEX_TEST_SLOTS" \
              'NR % n == (s-1) % n')"
    # If this shard collected nothing (more slots than tests), pass cleanly.
    if [ -z "$SHARD_ARGS" ]; then
        echo "slot $DOCEX_TEST_SLOT/$DOCEX_TEST_SLOTS: no tests in this shard"
        exit 0
    fi
    # shellcheck disable=SC2086
    exec pytest -q $SHARD_ARGS
fi

# shellcheck disable=SC2086
exec pytest -q $TARGET
