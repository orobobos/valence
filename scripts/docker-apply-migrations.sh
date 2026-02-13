#!/bin/bash
# Applied by docker-entrypoint-initdb.d after schema.sql and procedures.sql.
# Runs all SQL migration files in order.

MIGRATION_DIR="/docker-entrypoint-initdb.d/migrations"

if [ ! -d "$MIGRATION_DIR" ]; then
    echo "No migrations directory found, skipping."
    exit 0
fi

for f in "$MIGRATION_DIR"/*.sql; do
    [ -f "$f" ] || continue
    echo "Applying migration: $(basename "$f")"
    psql -v ON_ERROR_STOP=0 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done

echo "All migrations applied."
