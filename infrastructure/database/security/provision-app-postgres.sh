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
