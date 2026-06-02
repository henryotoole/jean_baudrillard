# Ephemeral stage-tester image for docex_smoke_fixed.
#
# `docex stagetest` builds this, runs it with the project bind-mounted at
# /project, $STAGING_URL and $PROJECT_VERSION exported, and reports the
# exit code.

FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1

WORKDIR /project

ENTRYPOINT ["/bin/sh"]
