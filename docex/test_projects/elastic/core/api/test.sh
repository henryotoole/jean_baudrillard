#!/bin/sh
# test.sh — canonical test entry point for the `api` codebase.
# One suite per codebase, not per core service: this globs the whole
# tests/ folder, covering api.web (test_smoke.py), api.worker
# (test_processor_smoke.py, test_jobs_smoke.py, test_jobs_concurrency.py)
# and api.clock (test_clock_smoke.py) in one run.
set -eu
exec pytest -q /service/tests
