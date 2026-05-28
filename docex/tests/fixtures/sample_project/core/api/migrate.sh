#!/bin/sh
# migrate.sh — apply database migrations for the api service.
#
# Uses plain psql to keep the fixture dependency footprint minimal.
# Real projects would typically use dbmate or alembic.
#
# Expects the connection parts the service itself uses at runtime:
# DATABASE_HOST, DATABASE_USER, DATABASE_PASSWORD, DATABASE_NAME — the
# same env vars the app binds from the database backing service's
# provided parts. The compose stack injects these via the rendered .env.
set -eu

cd "$(dirname "$0")"

: "${DATABASE_HOST:?DATABASE_HOST must be set}"
: "${DATABASE_USER:?DATABASE_USER must be set}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set}"
: "${DATABASE_NAME:=${DATABASE_USER}}"

export PGPASSWORD="$DATABASE_PASSWORD"

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
            host=os.environ["DATABASE_HOST"],
            user=os.environ["DATABASE_USER"],
            password=os.environ["DATABASE_PASSWORD"],
            dbname=os.environ.get("DATABASE_NAME", os.environ["DATABASE_USER"]),
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
