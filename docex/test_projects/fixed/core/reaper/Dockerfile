# reaper — Python scheduler core service, multi-stage build per doctrine.
# One codebase, one process type: `reaper.prune`, a run-to-completion job
# (prune expired processed pings), not a server. No HTTP surface, no
# /health (scheduler process types are exempt from the health model), no
# migrate.sh (the `api` codebase owns the appdb schema).
#
# Every stage must carry its own /service/dist. The trigger — Ofelia on
# fixed, an EventBridge Scheduler → ECS RunTask on elastic — launches the
# job with a bare `docker run` / RunTask and NO bind-mounts, so a stage
# that expected source to be mounted in would start with an empty dist.
#
# Which stage the trigger uses follows the environment, because the job
# runs the CODEBASE's image tag rather than an image of its own: mod 074's
# separate self-contained job image was retired by mod 103, since a second
# consumer of one tag has to agree with the first about what is inside it.
# So `dev` runs the `dev` stage and stage/prod run the `prod` stage — which
# is why both bake the artifact rather than only one of them.

FROM python:3.12-slim AS base
WORKDIR /service
RUN pip install --no-cache-dir psycopg2-binary==2.9.9

# ----------------------------------------------------------------------
# build
# ----------------------------------------------------------------------
FROM base AS build
COPY src/ /service/src/
COPY build.sh /service/build.sh
RUN chmod +x /service/build.sh && /service/build.sh

# ----------------------------------------------------------------------
# dev — carries source + build tools, and (per the header) a baked
# /service/dist, because in `dev` this is the stage the trigger launches.
# ----------------------------------------------------------------------
FROM base AS dev
COPY build.sh test.sh /service/
COPY src/ /service/src/
COPY tests/ /service/tests/
RUN chmod +x /service/*.sh && /service/build.sh
ENV PYTHONPATH=/service/dist
# WHY: never what runs. `command` is required on every process type and
# supersedes the Dockerfile CMD (cicl.md § Process Types); for a scheduler
# it is the trigger's `command =` that launches the job. Kept as a sane
# default for `docker run` by hand.
CMD ["python", "/service/dist/entrypoints/prune.py"]

# ----------------------------------------------------------------------
# prod — receives the built artifact from `build`. Self-contained.
# ----------------------------------------------------------------------
FROM base AS prod
COPY --from=build /service/dist /service/dist
ENV PYTHONPATH=/service/dist
# See the WHY on the dev stage: overridden by the process type's `command`.
CMD ["python", "/service/dist/entrypoints/prune.py"]

# ----------------------------------------------------------------------
# test — extends prod with pytest + test sources.
# ----------------------------------------------------------------------
FROM prod AS test
RUN pip install --no-cache-dir pytest==8.3.4
COPY test.sh /service/test.sh
COPY tests/ /service/tests/
RUN chmod +x /service/test.sh
CMD ["sleep", "infinity"]
