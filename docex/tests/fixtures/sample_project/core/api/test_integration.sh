#!/bin/sh
# test_integration.sh — stack-backed test tier for the api core service.
# Exits 0 on pass, non-zero on failure.
# DOCEX_TEST_SELECTOR (optional): a pytest-args fragment, forwarded UNQUOTED;
# set → replaces the whole-tier target.
set -eu
if [ -n "${DOCEX_TEST_SELECTOR:-}" ]; then
    # shellcheck disable=SC2086
    exec pytest -q $DOCEX_TEST_SELECTOR
fi
exec pytest -q /service/tests/integration
