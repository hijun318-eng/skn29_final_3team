#!/usr/bin/env bash
set -euo pipefail
mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --protocol=socket <<SQL
CREATE USER IF NOT EXISTS '$RO_USER'@'%' IDENTIFIED BY '$RO_PASSWORD';
GRANT SELECT, SHOW VIEW ON \`$MYSQL_DATABASE\`.* TO '$RO_USER'@'%';
FLUSH PRIVILEGES;
SQL
