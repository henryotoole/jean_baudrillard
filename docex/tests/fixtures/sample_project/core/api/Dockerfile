# Sample fixture: minimal multi-stage Dockerfile for a Python core service.
# Provides the four stages the doctrine requires: build, dev, prod, test.
# See infrastructure.md § Core Service Containers.

FROM python:3.12-slim AS base
WORKDIR /service
# Tiny dep set — fastapi + uvicorn would be heavier than this needs to be.
# bare http.server is enough for the smoke endpoint.
RUN pip install --no-cache-dir psycopg2-binary==2.9.9

# ----------------------------------------------------------------------
# build: runs build.sh, deposits artifacts in /service/dist
# ----------------------------------------------------------------------
FROM base AS build
COPY src/ /service/src/
COPY build.sh /service/build.sh
RUN chmod +x /service/build.sh && /service/build.sh

# ----------------------------------------------------------------------
# dev: carries source + build tools; expects /service/src and
# /service/dist to be bind-mounted from the host at runtime.
# ----------------------------------------------------------------------
FROM base AS dev
COPY build.sh /service/build.sh
COPY migrate.sh /service/migrate.sh
COPY test.sh /service/test.sh
COPY health.sh /service/health.sh
COPY src/ /service/src/
COPY tests/ /service/tests/
COPY migrations/ /service/migrations/
RUN chmod +x /service/*.sh && /service/build.sh
EXPOSE 8080
# The dev command re-reads source on each request via stdlib http.server.
CMD ["python", "/service/dist/app.py"]

# ----------------------------------------------------------------------
# prod: receives the built artifact from the build stage.
# ----------------------------------------------------------------------
FROM base AS prod
COPY --from=build /service/dist /service/dist
COPY migrate.sh /service/migrate.sh
COPY health.sh /service/health.sh
COPY migrations/ /service/migrations/
RUN chmod +x /service/migrate.sh /service/health.sh
EXPOSE 8080
CMD ["python", "/service/dist/app.py"]

# ----------------------------------------------------------------------
# test: extends prod with pytest + test sources.
#
# CMD is `sleep infinity` so the container stays up and ``docex test``
# can `compose exec` test.sh and migrate.sh against it. Running the
# tests as CMD would short-circuit the container before we could exec
# the migration step against it.
# ----------------------------------------------------------------------
FROM prod AS test
RUN pip install --no-cache-dir pytest==8.3.3
COPY test.sh /service/test.sh
COPY tests/ /service/tests/
RUN chmod +x /service/test.sh
CMD ["sleep", "infinity"]
