#!/bin/sh
# test_integration.sh — stack-backed test tier for the `api` codebase.
# Module-integration / flow / contract tests under tests/integration/, run
# against the live test-env stack (real postgres, sibling core services).
# Globs the folder; the folder is the authority.
#
# DOCEX_TEST_SELECTOR (optional, injected by `docex test integration [subset]`):
# a pytest-args FRAGMENT, forwarded UNQUOTED (see test_unit.sh). Set → replaces
# the default whole-tier target; unset → whole tier.
#
# DOCEX_TEST_SLOT / DOCEX_TEST_SLOTS (optional, injected by `docex test --slots
# N`): this shard's 1-based index and the shard count N. A REFERENCE only — the
# doctrine recommends but does not mandate this pattern (tests.md § Injected
# environment); a project may shard however is idiomatic to its runner. Unset or
# N=1 ⇒ whole tier, byte-identical to before. N>1 ⇒ this slot runs only its
# deterministic 1/N share of the collected node-ids, so the union of the N
# shards is exactly the whole tier.
set -eu

# Base target: a selector fragment replaces the whole-tier default (unchanged).
if [ -n "${DOCEX_TEST_SELECTOR:-}" ]; then
    TARGET="$DOCEX_TEST_SELECTOR"
else
    TARGET="/service/tests/integration"
fi

if [ "${DOCEX_TEST_SLOTS:-1}" -gt 1 ]; then
    # Collect node-ids for this tier (respecting any selector already spliced
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
