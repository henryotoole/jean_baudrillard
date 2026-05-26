#!/bin/sh
# test.sh — canonical test entry point for the api core service.
# Exits 0 on pass, non-zero on failure.
set -eu

exec pytest -q /service/tests
