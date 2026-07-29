#!/usr/bin/env sh
set -eu

sql_literal() {
  # MySQL string literals use doubled single quotes and escaped backslashes.
  printf '%s' "$1" | sed "s/\\\\/\\\\\\\\/g; s/'/''/g"
}

readonly_user=$(sql_literal "$POS_READONLY_USER")
readonly_password=$(sql_literal "$POS_READONLY_PASSWORD")

mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" <<SQL
CREATE USER IF NOT EXISTS '${readonly_user}'@'%' IDENTIFIED BY '${readonly_password}';
ALTER USER '${readonly_user}'@'%' IDENTIFIED BY '${readonly_password}' ACCOUNT UNLOCK;
GRANT 'pos_readonly' TO '${readonly_user}'@'%';
SET DEFAULT ROLE 'pos_readonly' TO '${readonly_user}'@'%';
SQL
