from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config
database_url = os.getenv("APP_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True, include_schemas=True, version_table_schema="governance")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section) or {}, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS governance")
        connection.commit()
        context.configure(connection=connection, include_schemas=True, version_table_schema="governance")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
