#!/bin/sh
# Stage-test shim invoked by `docex stagetest`. Exit code propagates.
set -eu
exec pytest -q /project/infra/stage/tests
