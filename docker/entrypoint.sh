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
PGPASSWORD=${POSTGRES_PASSWORD:-}
PSQL_URL="postgresql://${PGUSER}${PGPASSWORD:+:${PGPASSWORD}}@${PGHOST}:${PGPORT}/${PGDATABASE}"

until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE"; do
  sleep 1
done

exec "$@"
