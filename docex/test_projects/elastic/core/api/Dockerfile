# api — Python codebase, multi-stage build per doctrine
# (infrastructure.md § Core Service Containers).
#
# ONE image, THREE core services: `api.web` (uvicorn edge), `api.worker`
# (poll loop + an `rpc` surface) and `api.clock` (a cron loop, and nothing
# else — it listens on nothing). All three start this same artifact with a
# different `command`, so every dependency any of them needs is installed
# here.

FROM python:3.12-slim AS base
WORKDIR /service
# curl is here for exactly ONE line: `health.sh`'s `web` arm, which curls
# `http://localhost:8080/health` to check that the request cycle is serving.
# An image needs whatever its OWN probe needs and nothing more
# (healthchecks.md § The probe) — the emitted container probe is
# `["CMD", "./health.sh", "<service>"]` on both foundations, so what the
# probe depends on is this project's choice of shim implementation rather
# than anything the compiler dictates. The `worker` and `clock` arms stat a
# tick file and need no network tool at all.
#
# Still true and still the reason this line exists: python:3.12-slim does
# not include curl.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
# fastapi + uvicorn serve SURFACES, not liveness: `api.web`'s `rest` surface
# and `api.worker`'s `rpc` surface (entrypoints/{web,worker}.py). They are no
# longer a liveness dependency anywhere — liveness is `health.sh` — and
# `api.clock` needs neither, receiving them only because one image carries
# one dependency set.
#
# pyyaml + croniter are the clock's: it parses the compiler-delivered
# `DOCEX_SCHEDULES_YAML` literal and evaluates plain 5-field UTC cron
# expressions itself. There is NO DIALECT TRANSLATION ANYWHERE — the
# compiler passes the expression through unchanged, because the clock is
# project code rather than a cloud primitive (clock.md § Cron format), so
# whatever cron library the codebase pins parses it directly.
RUN pip install --no-cache-dir \
        fastapi==0.115.5 \
        uvicorn==0.32.1 \
        psycopg2-binary==2.9.9 \
        pydantic==2.10.2 \
        pyyaml==6.0.2 \
        croniter==5.0.1

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
COPY build.sh migrate.sh test_unit.sh test_integration.sh health.sh /service/
COPY src/ /service/src/
COPY tests/ /service/tests/
COPY migrations/ /service/migrations/
RUN chmod +x /service/*.sh && /service/build.sh
# 8080 for api.web's `rest` surface, 8081 for api.worker's `rpc` surface.
# api.clock listens on nothing — it declares no port and no surface.
EXPOSE 8080 8081
ENV PYTHONPATH=/service/dist
# WHY: this CMD is never what runs. `command` is required on every core
# service and supersedes the Dockerfile CMD (cicl.md § Core Services), which
# is deliberately irrelevant for core services — with three core services on
# one image, at most one could have inherited it. Kept only as a sane
# default for `docker run` by hand.
CMD ["python", "/service/dist/entrypoints/web.py"]

# ----------------------------------------------------------------------
# prod: receives the built artifact from `build`.
# ----------------------------------------------------------------------
FROM base AS prod
COPY --from=build /service/dist /service/dist
# health.sh is load-bearing HERE above all: `prod` is the image that `stage`
# and `prod` actually run, and the container probe on both foundations is
# `./health.sh <service>`. Without this COPY the probe is missing from the
# only image whose liveness anybody acts on. (`test` derives FROM prod and
# inherits it.)
COPY migrate.sh health.sh /service/
COPY migrations/ /service/migrations/
RUN chmod +x /service/migrate.sh /service/health.sh
EXPOSE 8080 8081
ENV PYTHONPATH=/service/dist
# See the WHY on the dev stage: overridden by each core service's `command`.
CMD ["python", "/service/dist/entrypoints/web.py"]

# ----------------------------------------------------------------------
# test: extends prod with pytest + test sources.
#
# CMD is `sleep infinity` so the container stays up and `docex test`
# can `compose run` the shims against it (mirroring the fixture pattern).
# One test suite per codebase, run by two shims — test_unit.sh (no-infra
# tier) and test_integration.sh (stack-backed tier, incl. contract).
# ----------------------------------------------------------------------
FROM prod AS test
RUN pip install --no-cache-dir pytest==8.3.4 httpx==0.28.1
COPY test_unit.sh test_integration.sh /service/
COPY tests/ /service/tests/
RUN chmod +x /service/test_unit.sh /service/test_integration.sh
CMD ["sleep", "infinity"]
