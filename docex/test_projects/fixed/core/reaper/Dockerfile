# reaper — Python scheduler core service, multi-stage build per doctrine.
# A run-to-completion job (prune expired processed pings), not a server:
# no HTTP surface, no /health, no migrate.sh (web owns the schema).
#
# The `prod` stage is self-contained (artifact baked in via COPY --from=
# build). This matters for the scheduler: the trigger (Ofelia on fixed,
# EventBridge RunTask on elastic) launches the job with a bare `docker
# run` / RunTask and NO bind-mounts, so the image must carry its own
# /service/dist. `docex up dev` builds this `prod` stage locally (mod
# 074) so Ofelia can launch it in dev.

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
# dev — carries source + build tools (bind-mounted in a long-running dev
# service; for the reaper it is only used by `docex build`-style
# iteration, never at job-run time — Ofelia runs the `prod` image).
# ----------------------------------------------------------------------
FROM base AS dev
COPY build.sh test.sh /service/
COPY src/ /service/src/
COPY tests/ /service/tests/
RUN chmod +x /service/*.sh && /service/build.sh
ENV PYTHONPATH=/service/dist
CMD ["python", "/service/dist/root.py"]

# ----------------------------------------------------------------------
# prod — receives the built artifact from `build`. Self-contained.
# ----------------------------------------------------------------------
FROM base AS prod
COPY --from=build /service/dist /service/dist
ENV PYTHONPATH=/service/dist
CMD ["python", "/service/dist/root.py"]

# ----------------------------------------------------------------------
# test — extends prod with pytest + test sources.
# ----------------------------------------------------------------------
FROM prod AS test
RUN pip install --no-cache-dir pytest==8.3.4
COPY test.sh /service/test.sh
COPY tests/ /service/tests/
RUN chmod +x /service/test.sh
CMD ["sleep", "infinity"]
