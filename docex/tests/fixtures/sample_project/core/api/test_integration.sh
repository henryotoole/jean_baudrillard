#!/bin/sh
# test_integration.sh — stack-backed test tier for the api core service.
# Exits 0 on pass, non-zero on failure.
set -eu

exec pytest -q /service/tests/integration
