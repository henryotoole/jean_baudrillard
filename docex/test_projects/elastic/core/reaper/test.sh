#!/bin/sh
# test.sh — canonical test entry point for the `reaper` codebase.
set -eu
exec pytest -q /service/tests
