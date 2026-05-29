#!/bin/sh
# test.sh — canonical test entry point for `worker`.
set -eu
exec pytest -q /service/tests
