#!/bin/sh
# test.sh — canonical test entry point for `web`.
set -eu
exec pytest -q /service/tests
