# api — Python codebase, multi-stage build per doctrine
# (infrastructure.md § Core Service Containers).
#
# ONE image, TWO core services: `api.web` (uvicorn edge) and `api.worker`
# (poll loop + liveness server). Both start this same artifact with a
# different `command`, so every dependency either needs is installed here.

FROM python:3.12-slim AS base
WORKDIR /service
# curl: needed by the doctrine-emitted docker healthcheck (the
# `health_check_path: /health` field translation in transfer tables
# `web/container` and `worker/container` emits
# `CMD curl -f http://localhost:${port}${path}`).
# python:3.12-slim does not include curl; without it the container is
# perpetually marked unhealthy, and traefik 3.x's docker provider
# filters out unhealthy containers from its router config — so the
# service is unreachable. Doctrine improvement TODO: switch the
# emit to a tool-free probe (traefik HTTP healthcheck via service
# labels) so the container's package list doesn't matter.
#
# BOTH core services need it now: `api.worker` also declares
# `health_check_path`, and the `docex check` gate keys off that field with
# no network filter, so it requires curl for the worker too.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
# fastapi + uvicorn are not web-only: `api.worker` serves its liveness
# tick over the same stack (entrypoints/worker.py).
RUN pip install --no-cache-dir \
        fastapi==0.115.5 \
        uvicorn==0.32.1 \
        psycopg2-binary==2.9.9 \
        pydantic==2.10.2

# dbmate — migrate.sh runs this. We copy the binary out of its official
# image rather than installing Go. Once per CODEBASE, not per core service:
# `api` owns the appdb schema (`schema_owned_by: api`) and `migrate.sh`
# runs once for the codebase regardless of how many ways it is invoked.
COPY --from=amacneil/dbmate:2.21.0 /usr/local/bin/dbmate /usr/local/bin/dbmate

# ----------------------------------------------------------------------
# build: runs build.sh against /service/src, deposits artifacts in
# /service/dist. Per cicd.md § Build Step, this is the canonical entry.
# ----------------------------------------------------------------------
FROM base AS build
COPY src/ /service/src/
COPY build.sh /service/build.sh
RUN chmod +x /service/build.sh && /service/build.sh

# ----------------------------------------------------------------------
# dev: carries source + build tools; /service/src and /service/dist
# bind-mount in at runtime.
# ----------------------------------------------------------------------
FROM base AS dev
COPY build.sh migrate.sh test.sh /service/
COPY src/ /service/src/
COPY tests/ /service/tests/
COPY migrations/ /service/migrations/
RUN chmod +x /service/*.sh && /service/build.sh
# 8080 for api.web, 8081 for api.worker's liveness server.
EXPOSE 8080 8081
ENV PYTHONPATH=/service/dist
# WHY: this CMD is never what runs. `command` is required on every core
# service and supersedes the Dockerfile CMD (cicl.md § Core Services), which
# is deliberately irrelevant for core services — with two core services on
# one image, at most one could have inherited it. Kept only as a sane
# default for `docker run` by hand.
CMD ["python", "/service/dist/entrypoints/web.py"]

# ----------------------------------------------------------------------
# prod: receives the built artifact from `build`.
# ----------------------------------------------------------------------
FROM base AS prod
COPY --from=build /service/dist /service/dist
COPY migrate.sh /service/migrate.sh
COPY migrations/ /service/migrations/
RUN chmod +x /service/migrate.sh
EXPOSE 8080 8081
ENV PYTHONPATH=/service/dist
# See the WHY on the dev stage: overridden by each core service's `command`.
CMD ["python", "/service/dist/entrypoints/web.py"]

# ----------------------------------------------------------------------
# test: extends prod with pytest + test sources.
#
# CMD is `sleep infinity` so the container stays up and `docex test`
# can `compose exec test.sh` against it (mirroring the fixture pattern).
# One test suite per codebase — test.sh runs both core services' tests.
# ----------------------------------------------------------------------
FROM prod AS test
RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1
COPY test.sh /service/test.sh
COPY tests/ /service/tests/
RUN chmod +x /service/test.sh
CMD ["sleep", "infinity"]
