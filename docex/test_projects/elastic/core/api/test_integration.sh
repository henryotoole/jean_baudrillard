#!/bin/sh
# test_integration.sh — stack-backed test tier for the `api` codebase.
# Module-integration / flow / contract tests under tests/integration/, run
# against the live test-env stack (real postgres, sibling core services).
# Globs the folder; the folder is the authority.
#
# DOCEX_TEST_SELECTOR (optional, injected by `docex test integration [subset]`):
# a pytest-args FRAGMENT, forwarded UNQUOTED (see test_unit.sh). Set → replaces
# the default whole-tier target; unset → whole tier.
set -eu
if [ -n "${DOCEX_TEST_SELECTOR:-}" ]; then
    # shellcheck disable=SC2086
    exec pytest -q $DOCEX_TEST_SELECTOR
fi
exec pytest -q /service/tests/integration
