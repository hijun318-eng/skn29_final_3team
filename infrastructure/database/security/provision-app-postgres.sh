#!/usr/bin/env sh
set -eu

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=runtime_user="$APP_DB_USER" \
  --set=migration_user="$APP_MIGRATION_USER" \
  --set=runtime_password="$APP_DB_PASSWORD" \
  --set=migration_password="$APP_MIGRATION_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'runtime_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'runtime_user')
\gexec
SELECT format('CREATE ROLE %I LOGIN', :'migration_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'migration_user')
\gexec

ALTER ROLE :"runtime_user" PASSWORD :'runtime_password';
ALTER ROLE :"migration_user" PASSWORD :'migration_password';

SELECT format(
  'GRANT CONNECT ON DATABASE %I TO %I, %I',
  current_database(),
  :'runtime_user',
  :'migration_user'
) \gexec
GRANT USAGE ON SCHEMA
  artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  TO :"runtime_user";
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA
  artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  TO :"runtime_user";
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA
  artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  TO :"runtime_user";

SELECT format(
  'GRANT CREATE ON DATABASE %I TO %I',
  current_database(),
  :'migration_user'
) \gexec

SELECT format('ALTER TABLE %I.%I OWNER TO %I', n.nspname, c.relname, :'migration_user')
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY (ARRAY[
  'analysis_v1','analytics','artifact','chat','connection','context','governance','model','query','reference','report','report_v1','tooling','rag','ml'
])
  AND c.relkind IN ('r', 'p')
ORDER BY n.nspname, c.relname
\gexec

SELECT format('ALTER SEQUENCE %I.%I OWNER TO %I', n.nspname, c.relname, :'migration_user')
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY (ARRAY[
  'analysis_v1','analytics','artifact','chat','connection','context','governance','model','query','reference','report','report_v1','tooling','rag','ml'
])
  AND c.relkind = 'S'
ORDER BY n.nspname, c.relname
\gexec

SELECT format('ALTER SCHEMA %I OWNER TO %I', nspname, :'migration_user')
FROM pg_namespace
WHERE nspname = ANY (ARRAY[
  'analysis_v1','analytics','artifact','chat','connection','context','governance','model','query','reference','report','report_v1','tooling','rag','ml'
])
ORDER BY nspname
\gexec

GRANT USAGE,CREATE ON SCHEMA
  artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  TO :"migration_user";
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA
  artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  TO :"migration_user";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA
  artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  TO :"migration_user";
SQL
