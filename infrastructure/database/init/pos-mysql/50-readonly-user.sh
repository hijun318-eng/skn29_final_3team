#!/usr/bin/env bash
(
set -Eeuo pipefail

[[ "$POS_DB_NAME" =~ ^[A-Za-z0-9_]+$ ]] || {
  echo "POS_DB_NAME must contain only letters, numbers, and underscores" >&2
  exit 1
}
[[ "$POS_READONLY_USER" =~ ^[A-Za-z0-9_]+$ ]] || {
  echo "POS_READONLY_USER must contain only letters, numbers, and underscores" >&2
  exit 1
}
[[ "$POS_READONLY_PASSWORD" =~ ^[A-Za-z0-9!_.+=-]+$ ]] || {
  echo "POS_READONLY_PASSWORD contains an unsupported character" >&2
  exit 1
}

mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
DROP USER IF EXISTS '${POS_READONLY_USER}'@'%';
CREATE USER '${POS_READONLY_USER}'@'%' IDENTIFIED BY '${POS_READONLY_PASSWORD}';
GRANT SELECT, SHOW VIEW ON \`${POS_DB_NAME}\`.* TO '${POS_READONLY_USER}'@'%';
SQL
)
