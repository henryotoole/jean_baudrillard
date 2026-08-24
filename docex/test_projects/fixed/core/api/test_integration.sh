#!/bin/sh
# test_integration.sh — stack-backed test tier for the `api` codebase.
# Module-integration / flow / contract tests under tests/integration/, run
# against the live test-env stack (real postgres, sibling core services).
# Globs the folder; the folder is the authority.
set -eu
exec pytest -q /service/tests/integration
