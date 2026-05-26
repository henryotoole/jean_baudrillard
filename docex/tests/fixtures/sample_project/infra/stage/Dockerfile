# Ephemeral stage-tester image.
#
# ``docex stagetest`` builds this image, runs it with the project
# bind-mounted at /project and ``$STAGING_URL`` exported, and reports
# the exit code. The container's only job is to run pytest against the
# deployed staging URL.
FROM python:3.12-slim

RUN pip install --no-cache-dir pytest httpx

# The project is bind-mounted in by docex at runtime; tests run from
# /project/infra/stage/tests via stage_test.sh.
WORKDIR /project

ENTRYPOINT ["/bin/sh"]
