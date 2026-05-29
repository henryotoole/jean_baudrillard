# worker — Python core service, multi-stage build per doctrine.
# No HTTP surface; no /health endpoint; no migrate.sh (web owns the schema).

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
# dev
# ----------------------------------------------------------------------
FROM base AS dev
COPY build.sh test.sh /service/
COPY src/ /service/src/
COPY tests/ /service/tests/
RUN chmod +x /service/*.sh && /service/build.sh
ENV PYTHONPATH=/service/dist
CMD ["python", "/service/dist/root.py"]

# ----------------------------------------------------------------------
# prod
# ----------------------------------------------------------------------
FROM base AS prod
COPY --from=build /service/dist /service/dist
ENV PYTHONPATH=/service/dist
CMD ["python", "/service/dist/root.py"]

# ----------------------------------------------------------------------
# test
# ----------------------------------------------------------------------
FROM prod AS test
RUN pip install --no-cache-dir pytest==8.3.4
COPY test.sh /service/test.sh
COPY tests/ /service/tests/
RUN chmod +x /service/test.sh
CMD ["sleep", "infinity"]
