#!/bin/sh
# test_unit.sh — no-infra test tier for the `api` codebase.
# Domain / alogic / adapter-unit tests under tests/unit/ (stub-backed: no
# postgres, no live stack). Globs the folder; the folder is the authority.
set -eu
exec pytest -q /service/tests/unit
