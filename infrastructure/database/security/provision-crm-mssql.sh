#!/usr/bin/env sh
# 책임: 외부 CRM query principal을 검증해 SQL Server provisioning batch에 전달한다.
# identifier 또는 secret 형식이 안전하지 않으면 sqlcmd를 호출하지 않는다.
set -eu

# Identifier syntax is validated before sqlcmd substitution. Password quotes
# are doubled as SQL literals; neither value originates in a tracked JSON.
case "$CRM_READONLY_USER" in
  ''|[0-9]*|*[!A-Za-z0-9_]*)
    echo 'CRM_READONLY_USER must be a simple SQL identifier.' >&2
    exit 2
    ;;
esac
if [ "${#CRM_READONLY_USER}" -lt 3 ] || [ "${#CRM_READONLY_USER}" -gt 64 ]; then
  echo 'CRM_READONLY_USER length must be between 3 and 64.' >&2
  exit 2
fi
crm_password=$(printf '%s' "$CRM_READONLY_PASSWORD" | sed "s/'/''/g")
# SQLCMDPASSWORD와 일반 sqlcmd scripting environment는 argv에 secret을 남기지
# 않으면서 checked-in batch의 identifier/literal 경계를 유지한다.
export SQLCMDPASSWORD="$MSSQL_SA_PASSWORD"
export QueryUser="$CRM_READONLY_USER"
export QueryPassword="$crm_password"

/opt/mssql-tools18/bin/sqlcmd \
  -S localhost -U sa -C -b \
  -i /security/provision-crm-mssql.sql
