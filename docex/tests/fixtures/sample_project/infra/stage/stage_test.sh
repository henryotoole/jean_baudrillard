#!/bin/sh
# Stage-test shim. Invoked by ``docex stagetest`` inside the
# ephemeral stage-tester container. Runs the project's stage-tests
# against $STAGING_URL.
set -eu
exec pytest -q /project/infra/stage/tests
