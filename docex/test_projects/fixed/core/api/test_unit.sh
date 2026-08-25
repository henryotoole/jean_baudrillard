#!/bin/sh
# test_unit.sh — no-infra test tier for the `api` codebase.
# Domain / alogic / adapter-unit tests under tests/unit/ (stub-backed: no
# postgres, no live stack). Globs the folder; the folder is the authority.
#
# DOCEX_TEST_SELECTOR (optional, injected by `docex test unit [subset]`): a
# pytest-args FRAGMENT (a path under tests/unit and/or a -m/-k expression),
# forwarded UNQUOTED so multiple tokens word-split into separate args. When set
# it replaces the default whole-tier target; unset runs the whole tier.
set -eu
if [ -n "${DOCEX_TEST_SELECTOR:-}" ]; then
    # shellcheck disable=SC2086
    exec pytest -q $DOCEX_TEST_SELECTOR
fi
exec pytest -q /service/tests/unit
