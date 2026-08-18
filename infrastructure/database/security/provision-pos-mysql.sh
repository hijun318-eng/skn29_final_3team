#!/usr/bin/env sh
# 책임: POS MySQL read-only principal을 외부 credential로 생성·회전한다. SQL literal
# escaping이나 grant 적용이 실패하면 기존 계정으로 fallback하지 않는다.
set -eu

sql_literal() {
  # MySQL string literal escaping is centralized so credentials never become
  # executable SQL when the provisioning command is expanded.
  printf '%s' "$1" | sed "s/\\\\/\\\\\\\\/g; s/'/''/g"
}

readonly_user=$(sql_literal "$POS_READONLY_USER")
readonly_password=$(sql_literal "$POS_READONLY_PASSWORD")

# MYSQL_PWD는 child environment로만 전달돼 root secret이 argv에 노출되지 않는다.
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE" <<SQL
CREATE USER IF NOT EXISTS '${readonly_user}'@'%' IDENTIFIED BY '${readonly_password}';
ALTER USER '${readonly_user}'@'%' IDENTIFIED BY '${readonly_password}' ACCOUNT UNLOCK;
GRANT 'pos_readonly' TO '${readonly_user}'@'%';
SET DEFAULT ROLE 'pos_readonly' TO '${readonly_user}'@'%';
SQL
