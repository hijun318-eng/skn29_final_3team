#!/usr/bin/env sh
# 책임: application migration/runtime/catalog publisher role을 분리하고 각 identity에
# 필요한 table 권한만 부여한다. identifier·secret 처리나 grant 조정 실패는 즉시 중단한다.
set -eu

provision_mode="${1:-full}"
case "$provision_mode" in
  full|publisher-only|ownership-only) ;;
  *)
    echo 'Usage: provision-app-postgres.sh [full|publisher-only|ownership-only]' >&2
    exit 1
    ;;
esac

reconcile_migration_ownership() {
  psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=migration_user="$APP_MIGRATION_USER" <<'SQL'
SELECT format(
  'GRANT CREATE ON DATABASE %I TO %I',
  current_database(),
  :'migration_user'
) \gexec

-- Base DDL은 bootstrap admin으로 실행되지만 이후 ALTER/constraint migration은
-- 전용 role이 소유해야 한다. application schema와 현재 table/sequence만 이관하고
-- database/public schema/pgcrypto extension 소유권은 admin에 남긴다.
SELECT format('ALTER SCHEMA %I OWNER TO %I', namespace.nspname, :'migration_user')
FROM pg_namespace AS namespace
WHERE namespace.nspname IN (
  'analytics','artifact','chat','connection','context','governance','model',
  'query','reference','report','tooling','rag','ml'
)
\gexec
SELECT format(
  'ALTER TABLE %I.%I OWNER TO %I', namespace.nspname, relation.relname,
  :'migration_user'
)
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname IN (
  'analytics','artifact','chat','connection','context','governance','model',
  'query','reference','report','tooling','rag','ml'
)
  AND relation.relkind IN ('r','p')
\gexec
SELECT format(
  'ALTER SEQUENCE %I.%I OWNER TO %I', namespace.nspname, relation.relname,
  :'migration_user'
)
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname IN (
  'analytics','artifact','chat','connection','context','governance','model',
  'query','reference','report','tooling','rag','ml'
)
  AND relation.relkind = 'S'
\gexec
GRANT USAGE,CREATE ON SCHEMA
  analytics,artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  TO :"migration_user" WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA
  analytics,artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  TO :"migration_user" WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA
  analytics,artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  TO :"migration_user" WITH GRANT OPTION;
SQL
}

if [ "$APP_DB_USER" = "$APP_MIGRATION_USER" ] || \
   [ "$APP_DB_USER" = "$APP_CATALOG_PUBLISHER_USER" ] || \
   [ "$APP_MIGRATION_USER" = "$APP_CATALOG_PUBLISHER_USER" ]; then
  echo 'App PostgreSQL runtime, migration, and catalog publisher roles must differ.' >&2
  exit 1
fi

# 기존 volume에 publisher 경계만 추가하는 upgrade는 runtime grant를 재조정하지 않는다.
# 비밀번호 값은 psql argv가 아니라 상속된 child environment에서만 읽는다. 이 mode는
# role/password/CONNECT까지만 맡고 table 권한은 해당 Alembic migration이 부여한다.
if [ "$provision_mode" = 'publisher-only' ]; then
  if [ "${#APP_CATALOG_PUBLISHER_PASSWORD}" -lt 12 ]; then
    echo 'App catalog publisher password must contain at least 12 characters.' >&2
    exit 1
  fi
  psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=publisher_user="$APP_CATALOG_PUBLISHER_USER" <<'SQL'
\set publisher_password `printf %s "$APP_CATALOG_PUBLISHER_PASSWORD"`
SELECT format('CREATE ROLE %I LOGIN', :'publisher_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'publisher_user')
\gexec
ALTER ROLE :"publisher_user" PASSWORD :'publisher_password';
SELECT format(
  'GRANT CONNECT ON DATABASE %I TO %I',
  current_database(),
  :'publisher_user'
) \gexec
SQL
  echo 'APP_CATALOG_PUBLISHER_ROLE_PROVISIONED'
  exit 0
fi

# 기존 runtime ACL을 보존한 채 과거 admin-owned relation만 migration owner 계약으로
# 정규화한다. migration 재시도 전용이며 role credential이나 application grant는 바꾸지 않는다.
if [ "$provision_mode" = 'ownership-only' ]; then
  reconcile_migration_ownership
  echo 'APP_MIGRATION_OWNERSHIP_RECONCILED'
  exit 0
fi

# psql variables distinguish identifiers (%I) from secret literals (%L); this
# prevents environment-provided role names or passwords from changing the SQL
# structure while keeping migration and runtime accounts separate.
psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=runtime_user="$APP_DB_USER" \
  --set=migration_user="$APP_MIGRATION_USER" \
  --set=publisher_user="$APP_CATALOG_PUBLISHER_USER" \
  --set=runtime_password="$APP_DB_PASSWORD" \
  --set=migration_password="$APP_MIGRATION_PASSWORD" \
  --set=publisher_password="$APP_CATALOG_PUBLISHER_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'runtime_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'runtime_user')
\gexec
SELECT format('CREATE ROLE %I LOGIN', :'migration_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'migration_user')
\gexec
SELECT format('CREATE ROLE %I LOGIN', :'publisher_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'publisher_user')
\gexec

ALTER ROLE :"runtime_user" PASSWORD :'runtime_password';
ALTER ROLE :"migration_user" PASSWORD :'migration_password';
ALTER ROLE :"publisher_user" PASSWORD :'publisher_password';

SELECT format(
  'GRANT CONNECT ON DATABASE %I TO %I, %I, %I',
  current_database(),
  :'runtime_user',
  :'migration_user',
  :'publisher_user'
) \gexec

-- 과거 bootstrap이 runtime role에 부여한 schema-wide DML을 매 실행마다 회수한다.
-- 이 목록은 base DDL과 현재 migration-created table을 모두 포함하며, 아래의
-- table/operation allowlist가 재부여되기 전에는 runtime이 어떤 row도 읽지 못한다.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA
  analytics,artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  FROM :"runtime_user";
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA
  analytics,artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  FROM :"runtime_user";
REVOKE USAGE ON SCHEMA
  analytics,artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  FROM :"runtime_user";

-- Publisher는 과거 또는 수동 grant를 모두 회수한 뒤 두 immutable relation에만
-- append/read 권한을 복원한다. pointer와 activation receipt에는 접근하지 않는다.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA
  analytics,artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  FROM :"publisher_user";
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA
  analytics,artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  FROM :"publisher_user";
REVOKE USAGE ON SCHEMA
  analytics,artifact,chat,connection,context,governance,model,query,reference,report,tooling,rag,ml
  FROM :"publisher_user";

-- Runtime API가 실제로 접근하는 base relation만 operation 단위로 복원한다.
-- connection/model/reference/legacy report schema는 application code가 사용하지
-- 않으므로 권한이 없고, 새 기능은 migration에서 명시 grant를 추가해야 한다.
GRANT USAGE ON SCHEMA artifact,chat,context,governance,query,tooling
  TO :"runtime_user";
GRANT USAGE ON SCHEMA governance TO :"publisher_user";
GRANT SELECT,INSERT,UPDATE ON chat.analysis_requests TO :"runtime_user";
GRANT SELECT,INSERT ON query.query_executions TO :"runtime_user";
GRANT SELECT,INSERT ON artifact.analysis_artifacts TO :"runtime_user";
GRANT SELECT,INSERT ON governance.audit_events TO :"runtime_user";
GRANT SELECT,INSERT,UPDATE ON context.context_records TO :"runtime_user";
GRANT SELECT,INSERT,UPDATE ON context.context_releases TO :"runtime_user";
GRANT SELECT,INSERT ON context.context_packages TO :"runtime_user";

-- 이 script는 Alembic 전후 모두 실행될 수 있다. 존재하는 migration relation만
-- 조건부로 재부여해 first boot는 허용하면서 restart 시 최소권한을 보존한다.
SELECT format('GRANT SELECT ON governance.alembic_version TO %I', :'runtime_user')
WHERE to_regclass('governance.alembic_version') IS NOT NULL
\gexec
SELECT format('GRANT SELECT ON context.analysis_templates TO %I', :'runtime_user')
WHERE to_regclass('context.analysis_templates') IS NOT NULL
\gexec
SELECT format(
  'GRANT SELECT, INSERT ON chat.analysis_state_transitions TO %I', :'runtime_user'
)
WHERE to_regclass('chat.analysis_state_transitions') IS NOT NULL
\gexec
SELECT format('GRANT SELECT ON tooling.tool_registry TO %I', :'runtime_user')
WHERE to_regclass('tooling.tool_registry') IS NOT NULL
\gexec
SELECT format('GRANT SELECT, INSERT ON tooling.tool_runs TO %I', :'runtime_user')
WHERE to_regclass('tooling.tool_runs') IS NOT NULL
\gexec
SELECT format('GRANT SELECT ON governance.alembic_version TO %I', :'publisher_user')
WHERE to_regclass('governance.alembic_version') IS NOT NULL
\gexec
SELECT format(
  'GRANT SELECT, INSERT ON governance.runtime_catalog_projections TO %I',
  :'publisher_user'
)
WHERE to_regclass('governance.runtime_catalog_projections') IS NOT NULL
\gexec
SELECT format(
  'GRANT SELECT, INSERT ON governance.product_release_manifests TO %I',
  :'publisher_user'
)
WHERE to_regclass('governance.product_release_manifests') IS NOT NULL
\gexec
SQL
reconcile_migration_ownership
