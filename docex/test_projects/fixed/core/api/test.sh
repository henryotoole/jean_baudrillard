#!/bin/sh
# test.sh — canonical test entry point for the `api` codebase.
# One suite per codebase, not per core service: this globs the whole
# tests/ folder, covering api.web (test_smoke.py), api.worker
# (test_processor_smoke.py, test_jobs_smoke.py, test_jobs_concurrency.py,
# test_jobs_alogic.py), api.clock (test_clock_smoke.py), and the
# api.web -> api.worker drain boundary (test_jobs_drain.py) in one run.
# The glob is the authority: this list is orientation, not a manifest.
set -eu
exec pytest -q /service/tests
