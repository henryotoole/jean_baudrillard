#!/bin/sh
# test.sh — canonical test entry point for the `api` codebase.
# One suite per codebase, not per core service: this runs both
# tests/test_smoke.py (api.web) and tests/test_processor_smoke.py
# (api.worker).
set -eu
exec pytest -q /service/tests
