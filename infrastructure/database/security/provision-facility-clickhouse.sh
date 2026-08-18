#!/usr/bin/env sh
# 책임: ClickHouse facility read-only principal을 검증된 identifier와 escaped secret으로
# 조정한다. 입력 검증이나 CREATE/ALTER/GRANT 중 하나라도 실패하면 즉시 중단한다.
set -eu

# Identifier는 SQL 구조에 들어가기 전에 제한하고 secret은 ClickHouse string literal
# 규칙으로 escape한다. password는 stdin batch와 child environment로만 이동해 argv에는
# 나타나지 않는다. fixed role은 DB security contract이며 데이터 시나리오 분기가 아니다.
case "$FACILITY_READONLY_USER" in
  ''|[0-9]*|*[!A-Za-z0-9_]*)
    echo 'FACILITY_READONLY_USER must be a simple ClickHouse identifier.' >&2
    exit 2
    ;;
esac
if [ "${#FACILITY_READONLY_USER}" -lt 3 ] || [ "${#FACILITY_READONLY_USER}" -gt 64 ]; then
  echo 'FACILITY_READONLY_USER length must be between 3 and 64.' >&2
  exit 2
fi
escaped_password=$(printf '%s' "$FACILITY_READONLY_PASSWORD" | sed "s/\\\\/\\\\\\\\/g; s/'/''/g")

CLICKHOUSE_PASSWORD="$CLICKHOUSE_PASSWORD" clickhouse-client \
  --user "$CLICKHOUSE_USER" --multiquery <<SQL
CREATE USER IF NOT EXISTS \`${FACILITY_READONLY_USER}\`
IDENTIFIED WITH sha256_password BY '${escaped_password}';
ALTER USER \`${FACILITY_READONLY_USER}\`
IDENTIFIED WITH sha256_password BY '${escaped_password}';
GRANT facility_readonly TO \`${FACILITY_READONLY_USER}\`;
SET DEFAULT ROLE facility_readonly TO \`${FACILITY_READONLY_USER}\`;
ALTER USER \`${FACILITY_READONLY_USER}\` SETTINGS readonly=1;
SQL
