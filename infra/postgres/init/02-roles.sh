#!/bin/sh
# Least-privilege database roles. Passwords come from container environment.
set -eu

psql -v ON_ERROR_STOP=1 \
     -v readonly_db="$POSTGRES_DB" \
     -v grafana_password="$GRAFANA_DB_PASSWORD" \
     -v api_password="$API_DB_PASSWORD" \
     -v exporter_password="$EXPORTER_DB_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
-- Read-only group used by Grafana and the Pit Wall API.
CREATE ROLE f1_readonly NOLOGIN;
GRANT CONNECT ON DATABASE :"readonly_db" TO f1_readonly;
GRANT USAGE ON SCHEMA public TO f1_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO f1_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO f1_readonly;

CREATE ROLE grafana_reader LOGIN PASSWORD :'grafana_password' IN ROLE f1_readonly;
CREATE ROLE pitwall_api LOGIN PASSWORD :'api_password' IN ROLE f1_readonly;

-- Metrics collector for postgres-exporter.
CREATE ROLE postgres_exporter LOGIN PASSWORD :'exporter_password' IN ROLE pg_monitor;
EOSQL
