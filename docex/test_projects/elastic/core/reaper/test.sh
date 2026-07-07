#!/bin/sh
# test.sh — canonical test entry point for `reaper`.
set -eu
exec pytest -q /service/tests
