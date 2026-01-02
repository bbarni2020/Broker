#!/bin/sh
set -e

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

PGHOST=${PGHOST:-db}
PGPORT=${PGPORT:-5432}
PGUSER=${POSTGRES_USER:-broker}
PGDATABASE=${POSTGRES_DB:-broker}

until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE"; do
  sleep 1
done

psql "$DATABASE_URL" -c "drop table if exists alembic_version cascade;" || true
alembic upgrade head
exec "$@"
