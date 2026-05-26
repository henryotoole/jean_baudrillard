#!/bin/sh
# migrate.sh — apply database migrations for the api service.
#
# Uses plain psql to keep the fixture dependency footprint minimal.
# Real projects would typically use dbmate or alembic.
#
# Expects the env vars the service itself uses: POSTGRES_HOST,
# POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB. The compose stack
# injects these via the rendered .env file.
set -eu

cd "$(dirname "$0")"

: "${POSTGRES_HOST:?POSTGRES_HOST must be set}"
: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
: "${POSTGRES_DB:=${POSTGRES_USER}}"

export PGPASSWORD="$POSTGRES_PASSWORD"

# We shell out to python+psycopg2 rather than installing psql, since
# psycopg2-binary is already in the image.
python3 - <<'PY'
import glob, os, sys, time
import psycopg2

# Real projects would use a tool like dbmate that handles this. For
# the fixture we hand-roll a short connect-with-retry loop so that a
# slow-to-start postgres in dev doesn't fail the first run.
last_exc = None
for attempt in range(15):
    try:
        conn = psycopg2.connect(
            host=os.environ["POSTGRES_HOST"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            dbname=os.environ.get("POSTGRES_DB", os.environ["POSTGRES_USER"]),
        )
        break
    except psycopg2.OperationalError as exc:
        last_exc = exc
        time.sleep(1)
else:
    raise SystemExit(f"could not connect to postgres after 15 tries: {last_exc}")

conn.autocommit = True
cur = conn.cursor()

files = sorted(glob.glob("/service/migrations/*.sql"))
for path in files:
    with open(path) as f:
        sql = f.read()
    print(f"applying {os.path.basename(path)}", file=sys.stderr)
    cur.execute(sql)

print(f"migrated {len(files)} file(s)", file=sys.stderr)
PY
